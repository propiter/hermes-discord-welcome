import asyncio
from types import SimpleNamespace

import discord
import pytest

from discord_welcome.client import WelcomeClient, pick_channel
from discord_welcome.logic import InviteInfo
from discord_welcome.settings import Settings


ME = SimpleNamespace(mention="<@bot>")


class Chan:
    def __init__(self, cid, bot_ok=True, member_ok=True):
        self.id, self.bot_ok, self.member_ok, self.sent = cid, bot_ok, member_ok, []

    def permissions_for(self, who):
        ok = self.bot_ok if who is ME else self.member_ok
        return SimpleNamespace(view_channel=ok, send_messages=ok)

    async def send(self, content, **kw):
        self.sent.append((content, kw))

    def __str__(self):
        return f"c{self.id}"


class Guild:
    def __init__(self, channels, system=None, invites=()):
        self.id, self.name, self.member_count = 1, "Acme", 10
        self.channels = {c.id: c for c in channels}
        self.system_channel = system
        self.me = ME
        self._invites = list(invites)

    def get_channel(self, cid):
        return self.channels.get(cid)

    async def invites(self):
        return self._invites


def member(guild):
    return SimpleNamespace(id=5, mention="<@5>", display_name="Ana", bot=False, guild=guild,
                           created_at=None)


def test_pick_channel_order():
    inv_ch, fb, sysc, fixed = Chan(10), Chan(20), Chan(30), Chan(40)
    g = Guild([inv_ch, fb, sysc, fixed], system=sysc)
    invite = InviteInfo("x", 1, channel_id=10)
    m = "member"
    assert pick_channel(g, m, ME, Settings(), invite) is inv_ch
    assert pick_channel(g, m, ME, Settings(greet_channel=40), invite) is fixed
    assert pick_channel(g, m, ME, Settings(fallback_channel=20), None) is fb
    assert pick_channel(g, m, ME, Settings(), None) is sysc
    assert pick_channel(g, m, ME, Settings(greet_in_invite_channel=False), invite) is sysc


def test_pick_channel_skips_unusable():
    hidden_for_member, no_bot_perm, sysc = Chan(10, member_ok=False), Chan(11, bot_ok=False), Chan(30)
    g = Guild([hidden_for_member, no_bot_perm, sysc], system=sysc)
    assert pick_channel(g, "m", ME, Settings(), InviteInfo("x", 1, channel_id=10)) is sysc
    assert pick_channel(g, "m", ME, Settings(), InviteInfo("y", 1, channel_id=11)) is sysc
    assert pick_channel(Guild([]), "m", ME, Settings(), None) is None


def _client(settings):
    return WelcomeClient(lambda: settings)


def _invite(code, uses, channel):
    return SimpleNamespace(code=code, uses=uses, max_uses=0, channel=SimpleNamespace(id=channel),
                           inviter=SimpleNamespace(id=77))


@pytest.fixture
def loop():
    lp = asyncio.new_event_loop()
    yield lp
    lp.close()


def test_join_greets_in_invite_channel_and_notifies(loop):
    vg, general, staff = Chan(10), Chan(30), Chan(50)
    g = Guild([vg, general, staff], system=general, invites=[_invite("vg", 1, 10)])
    client = _client(Settings(notify_channel=50, language="es"))
    client.invites[1] = {"vg": InviteInfo("vg", 0, channel_id=10)}
    loop.run_until_complete(client._handle_join(member(g)))
    (text, kw), = vg.sent
    assert "<@5>" in text and "Acme" in text and "<@bot>" in text
    assert isinstance(kw["view"], discord.ui.View) and len(kw["view"].children) == 1
    assert not general.sent
    (notice, _), = staff.sent
    assert "`vg`" in notice and "<#10>" in notice and "<@77>" in notice
    loop.run_until_complete(client.close())


def test_join_wave_pauses_greetings(loop):
    general, staff = Chan(30), Chan(50)
    g = Guild([general, staff], system=general)
    client = _client(
        Settings(notify_channel=50, raid_threshold=2, nickname_button=False))
    for _ in range(4):
        loop.run_until_complete(client._handle_join(member(g)))
    assert len(general.sent) == 1  # first join only; 2nd starts the wave, rest are suppressed
    assert any("2" in t for t, _ in staff.sent)
    loop.run_until_complete(client.close())


def test_disabled_and_bots_are_ignored(loop):
    general = Chan(30)
    g = Guild([general], system=general)
    client = _client(Settings(enabled=False))
    loop.run_until_complete(client._handle_join(member(g)))
    bot_member = member(g)
    bot_member.bot = True
    client.get_settings = lambda: Settings()
    loop.run_until_complete(client._handle_join(bot_member))
    assert general.sent == []
    loop.run_until_complete(client.close())
