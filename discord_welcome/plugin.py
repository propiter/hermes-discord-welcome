"""Wires the welcome client to Hermes: started from the Discord adapter's native-handler factory
(so it reuses the adapter's token and event loop) and closed on plugin unload."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from .settings import Settings

log = logging.getLogger("discord_welcome")


class _State:
    client: Any = None
    task: Optional[asyncio.Task] = None
    token: Optional[str] = None
    detached: bool = False


def register(ctx: Any) -> None:
    state = _State()

    def get_settings() -> Settings:
        return Settings.load(ctx.get_config)

    def factory(bot: Any, adapter: Any) -> None:
        if state.detached or not get_settings().enabled:
            return
        token = getattr(getattr(adapter, "config", None), "token", None)
        if not token:
            log.warning("discord-welcome: the Discord adapter has no token; not starting")
            return
        running = state.task is not None and not state.task.done()
        if running and state.token == token:
            return  # adapter reconnect: our own session is independent and still alive
        from .client import WelcomeClient  # discord.py imported only once Discord is in use

        if running:
            asyncio.ensure_future(state.client.close())
        state.client = WelcomeClient(get_settings)
        state.token = token
        state.task = asyncio.ensure_future(_run(state.client, token))

    async def _run(client: Any, token: str) -> None:
        import discord

        try:
            await client.start(token)
        except discord.PrivilegedIntentsRequired:
            log.error("discord-welcome: enable 'Server Members Intent' for this bot in the Discord "
                      "Developer Portal (Bot -> Privileged Gateway Intents), then restart the gateway")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("discord-welcome: welcome session stopped")

    def unload() -> None:
        state.detached = True
        if state.client is not None and not state.client.is_closed():
            try:
                asyncio.get_running_loop().create_task(state.client.close())
            except RuntimeError:
                pass
        if state.task is not None:
            state.task.cancel()

    ctx.register_platform_handler("discord", factory)
    if callable(getattr(ctx, "on_unload", None)):
        ctx.on_unload(unload)
