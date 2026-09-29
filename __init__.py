"""Hermes plugin entry point for ``discord-welcome``.

Greets every new member of a Discord server, in the channel of the invite they used.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent


def register(ctx: Any) -> None:
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    from discord_welcome.plugin import register as _register

    _register(ctx)
