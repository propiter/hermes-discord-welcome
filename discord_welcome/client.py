"""discord.py glue.

Hermes' Discord adapter only requests the Server Members intent when a username/role allowlist
needs it, so ``on_member_join`` never reaches the main client. This module opens a *second*,
minimal gateway session with the same token that subscribes to guilds, members and invites ONLY.
It never receives messages, so it can never make the bot answer twice. The nickname button and its
modal are also handled here: component interactions reach every session of the bot, and the main
client ignores ``custom_id`` values it does not know.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

import discord

from .logic import InviteInfo, RaidGuard, account_age_days, detect_invite, render, strings
from .settings import Settings

log = logging.getLogger("discord_welcome")

NICK_ID = r"dwelcome:nick:(?P<uid>\d+)"


def _invite_info(inv: Any) -> InviteInfo:
    return InviteInfo(
        code=inv.code,
        uses=int(inv.uses or 0),
        max_uses=int(inv.max_uses or 0),
        channel_id=getattr(inv.channel, "id", None),
        inviter_id=getattr(inv.inviter, "id", None),
    )


def pick_channel(guild: Any, member: Any, me: Any, settings: Settings,
                 invite: Optional[InviteInfo]) -> Any:
    """Where to greet: fixed channel > invite channel (if both the bot can post and the newcomer can
    see it) > fallback channel > the server's system channel. ``None`` = nowhere usable."""

    def usable(channel: Any, need_member_view: bool) -> bool:
        if channel is None or not hasattr(channel, "send") or isinstance(channel, discord.ForumChannel):
            return False
        mine = channel.permissions_for(me)
        if not (mine.view_channel and mine.send_messages):
            return False
        return not need_member_view or channel.permissions_for(member).view_channel

    if settings.greet_channel:
        channel = guild.get_channel(settings.greet_channel)
        if usable(channel, False):
            return channel
    if settings.greet_in_invite_channel and invite and invite.channel_id:
        channel = guild.get_channel(invite.channel_id)
        if usable(channel, True):
            return channel
    for candidate in (guild.get_channel(settings.fallback_channel) if settings.fallback_channel
                      else None, guild.system_channel):
        if usable(candidate, False):
            return candidate
    return None


class NickModal(discord.ui.Modal):
    def __init__(self, text: Dict[str, str]) -> None:
        super().__init__(title=text["nick_title"][:45], custom_id="dwelcome:nickmodal")
        self.text = text
        self.nick = discord.ui.TextInput(label=text["nick_label"][:45], min_length=2, max_length=32)
        self.add_item(self.nick)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        value = str(self.nick.value).strip()
        try:
            await interaction.user.edit(nick=value, reason="discord-welcome: self-service nickname")
        except (discord.Forbidden, AttributeError):
            await interaction.response.send_message(self.text["nick_forbidden"], ephemeral=True)
            return
        await interaction.response.send_message(render(self.text["nick_done"], {"nick": value}),
                                                ephemeral=True)


def make_nick_button(get_settings: Callable[[], Settings]) -> type:
    class NickButton(discord.ui.DynamicItem[discord.ui.Button], template=NICK_ID):
        def __init__(self, user_id: int, label: str = "Set your name") -> None:
            super().__init__(discord.ui.Button(label=label[:80], emoji="✏️",
                                               style=discord.ButtonStyle.secondary,
                                               custom_id=f"dwelcome:nick:{user_id}"))
            self.user_id = user_id

        @classmethod
        async def from_custom_id(cls, interaction: discord.Interaction, item: Any,
                                 match: re.Match[str]) -> "NickButton":
            return cls(int(match["uid"]))

        async def callback(self, interaction: discord.Interaction) -> None:
            text = strings(get_settings().language)
            if interaction.user.id != self.user_id:
                await interaction.response.send_message(
                    render(text["nick_not_yours"], {"mention": f"<@{self.user_id}>"}), ephemeral=True)
                return
            await interaction.response.send_modal(NickModal(text))

    return NickButton


class WelcomeClient(discord.Client):
    def __init__(self, get_settings: Callable[[], Settings], **kwargs: Any) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.members = True  # privileged: GUILD_MEMBER_ADD
        intents.invites = True  # INVITE_CREATE / INVITE_DELETE keep the cache fresh
        super().__init__(intents=intents, **kwargs)
        self.get_settings = get_settings
        self.invites: Dict[int, Dict[str, InviteInfo]] = {}
        self.deleted: Dict[int, set] = {}
        self.locks: Dict[int, asyncio.Lock] = {}
        self.raid: Dict[int, RaidGuard] = {}
        self.NickButton = make_nick_button(get_settings)

    async def setup_hook(self) -> None:
        self.add_dynamic_items(self.NickButton)

    # ---- invite cache -------------------------------------------------------------------------
    async def snapshot(self, guild: discord.Guild) -> Optional[Dict[str, InviteInfo]]:
        try:
            return {inv.code: _invite_info(inv) for inv in await guild.invites()}
        except (discord.Forbidden, discord.HTTPException) as exc:
            log.info("discord-welcome: cannot read invites in %s (%s); greeting in fallback channel",
                     guild.name, exc)
            return None

    def wanted(self, guild: discord.Guild) -> bool:
        allowed = self.get_settings().guilds
        return not allowed or guild.id in allowed

    async def on_ready(self) -> None:
        for guild in self.guilds:
            if self.wanted(guild):
                snap = await self.snapshot(guild)
                if snap is not None:
                    self.invites[guild.id] = snap
        log.info("discord-welcome: listening for joins as %s in %d server(s)", self.user,
                 len(self.guilds))

    async def on_guild_join(self, guild: discord.Guild) -> None:
        snap = await self.snapshot(guild)
        if snap is not None:
            self.invites[guild.id] = snap

    async def on_invite_create(self, invite: discord.Invite) -> None:
        if invite.guild is not None:
            self.invites.setdefault(invite.guild.id, {})[invite.code] = _invite_info(invite)

    async def on_invite_delete(self, invite: discord.Invite) -> None:
        if invite.guild is not None:
            self.deleted.setdefault(invite.guild.id, set()).add(invite.code)

    # ---- the event ----------------------------------------------------------------------------
    async def on_member_join(self, member: discord.Member) -> None:
        try:
            await self._handle_join(member)
        except Exception:  # a plugin bug must never surface as a listener error storm
            log.exception("discord-welcome: failed to handle join of %s", member)

    async def _handle_join(self, member: discord.Member) -> None:
        settings = self.get_settings()
        guild = member.guild
        if not settings.enabled or not self.wanted(guild):
            return
        if settings.ignore_bots and member.bot:
            return
        text = strings(settings.language)
        async with self.locks.setdefault(guild.id, asyncio.Lock()):
            before = self.invites.get(guild.id, {})
            after = await self.snapshot(guild)
            invite = None
            if after is not None:
                invite = detect_invite(before, after, self.deleted.pop(guild.id, set()))
                self.invites[guild.id] = after

        guard = self.raid.get(guild.id)
        if guard is None or guard.threshold != settings.raid_threshold or \
                guard.window != settings.raid_window_seconds:
            guard = self.raid[guild.id] = RaidGuard(settings.raid_threshold,
                                                    float(settings.raid_window_seconds))
        state = guard.record()
        notify = guild.get_channel(settings.notify_channel) if settings.notify_channel else None
        quiet = discord.AllowedMentions.none()
        if state == "start":
            log.warning("discord-welcome: join wave in %s, greetings paused", guild.name)
            if notify is not None:
                await notify.send(render(text["raid_start"], {"count": settings.raid_threshold,
                                                              "window": settings.raid_window_seconds}),
                                  allowed_mentions=quiet)
            return
        if state == "ongoing":
            return
        if state == "ended" and notify is not None:
            await notify.send(render(text["raid_end"], {"count": guard.suppressed}),
                              allowed_mentions=quiet)

        me = guild.me
        channel = pick_channel(guild, member, me, settings, invite)
        values = {"mention": member.mention, "name": member.display_name, "server": guild.name,
                  "bot": me.mention, "member_count": guild.member_count or ""}
        if channel is None:
            log.warning("discord-welcome: no channel to greet %s in %s", member, guild.name)
        else:
            view = None
            if settings.nickname_button:
                view = discord.ui.View(timeout=None)
                view.add_item(self.NickButton(member.id, text["nick_button"]))
            await channel.send(render(settings.message or text["message"], values), view=view,
                               allowed_mentions=discord.AllowedMentions(users=[member], roles=False,
                                                                        everyone=False))
            log.info("discord-welcome: greeted %s in #%s (invite %s)", member, channel,
                     invite.code if invite else "unknown")

        if notify is not None:
            if invite is not None:
                inviter = (render(text["source_inviter"], {"inviter": f"<@{invite.inviter_id}>"})
                           if invite.inviter_id else "")
                where = f"<#{invite.channel_id}>" if invite.channel_id else "?"
                source = render(text["source_invite"], {"code": invite.code, "channel": where,
                                                        "inviter": inviter})
            else:
                source = text["source_unknown"]
            created = member.created_at or datetime.now(timezone.utc)
            await notify.send(render(text["notify"], {
                "mention": member.mention, "name": str(member),
                "age": account_age_days(created.timestamp()), "source": source}),
                allowed_mentions=quiet)
