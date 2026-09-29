"""Typed view over ``plugins.entries.discord-welcome.settings`` (read fresh on every join)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, FrozenSet, Optional

from .logic import parse_id


@dataclass(frozen=True)
class Settings:
    enabled: bool = True
    language: str = "en"
    message: str = ""  # empty = built-in text for ``language``
    greet_in_invite_channel: bool = True
    greet_channel: Optional[int] = None  # fixed channel; overrides invite routing
    fallback_channel: Optional[int] = None  # empty = the server's system channel
    notify_channel: Optional[int] = None  # empty = no staff notice
    nickname_button: bool = True
    raid_threshold: int = 5
    raid_window_seconds: int = 60
    ignore_bots: bool = True
    guilds: FrozenSet[int] = frozenset()  # empty = every server the bot is in

    @classmethod
    def load(cls, get: Callable[[str, Any], Any]) -> "Settings":
        def _bool(key: str, default: bool) -> bool:
            value = get(key, default)
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "on", "si", "sí"}
            return bool(value)

        def _int(key: str, default: int) -> int:
            try:
                return int(get(key, default))
            except (TypeError, ValueError):
                return default

        raw_guilds = get("guilds", []) or []
        if isinstance(raw_guilds, str):
            raw_guilds = raw_guilds.split(",")
        return cls(
            enabled=_bool("enabled", True),
            language=str(get("language", "en") or "en"),
            message=str(get("message", "") or ""),
            greet_in_invite_channel=_bool("greet_in_invite_channel", True),
            greet_channel=parse_id(get("greet_channel", "")),
            fallback_channel=parse_id(get("fallback_channel", "")),
            notify_channel=parse_id(get("notify_channel", "")),
            nickname_button=_bool("nickname_button", True),
            raid_threshold=_int("raid_threshold", 5),
            raid_window_seconds=max(1, _int("raid_window_seconds", 60)),
            ignore_bots=_bool("ignore_bots", True),
            guilds=frozenset(g for g in (parse_id(x) for x in raw_guilds) if g),
        )
