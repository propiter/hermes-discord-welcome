"""Pure decision logic: no discord.py imports, so it is unit-testable without a gateway."""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, Dict, Iterable, Mapping, Optional


@dataclass(frozen=True)
class InviteInfo:
    """What we remember about one invite between two joins."""

    code: str
    uses: int
    max_uses: int = 0  # 0 = unlimited
    channel_id: Optional[int] = None
    inviter_id: Optional[int] = None


def detect_invite(
    before: Mapping[str, InviteInfo],
    after: Mapping[str, InviteInfo],
    deleted: Iterable[str] = (),
) -> Optional[InviteInfo]:
    """Return the invite a new member used, or ``None`` when it cannot be told apart.

    Candidates are invites whose use count went up, plus invites that disappeared since the last
    snapshot while one use short of their limit (Discord deletes an invite as soon as its last use
    is consumed). More than one candidate means two joins raced: we refuse to guess.
    """
    candidates = []
    for code, now in after.items():
        prev = before.get(code)
        if now.uses > (prev.uses if prev else 0):
            candidates.append(now)
    gone = set(deleted) | (set(before) - set(after))
    for code in gone:
        prev = before.get(code)
        if prev and prev.max_uses and prev.uses + 1 >= prev.max_uses:
            candidates.append(InviteInfo(prev.code, prev.uses + 1, prev.max_uses, prev.channel_id,
                                         prev.inviter_id))
    return candidates[0] if len(candidates) == 1 else None


@dataclass
class RaidGuard:
    """Sliding-window join counter. ``threshold <= 0`` disables it."""

    threshold: int = 5
    window: float = 60.0
    clock: Callable[[], float] = time.monotonic
    _joins: Deque[float] = field(default_factory=deque)
    active: bool = False
    suppressed: int = 0

    def record(self) -> str:
        """Register one join. Returns ``"normal"``, ``"start"`` (raid just detected), ``"ongoing"``
        or ``"ended"`` (first join after a quiet window; ``suppressed`` holds the skipped count
        until the next call)."""
        now = self.clock()
        if self.threshold <= 0:
            return "normal"
        quiet = not self._joins or now - self._joins[-1] > self.window
        while self._joins and now - self._joins[0] > self.window:
            self._joins.popleft()
        self._joins.append(now)
        if self.active:
            if quiet:
                self.active = False
                return "ended"
            self.suppressed += 1
            return "ongoing"
        if len(self._joins) >= self.threshold:
            self.active = True
            self.suppressed = 1
            return "start"
        self.suppressed = 0
        return "normal"


def render(template: str, values: Mapping[str, object]) -> str:
    """``str.format_map`` that leaves unknown ``{placeholders}`` untouched instead of raising."""

    class _Safe(dict):
        def __missing__(self, key: str) -> str:
            return "{" + key + "}"

    try:
        return template.format_map(_Safe(values))
    except (ValueError, IndexError):  # a stray brace in user text: send it verbatim
        return template


def account_age_days(created_ts: float, now_ts: Optional[float] = None) -> int:
    return max(0, int(((now_ts if now_ts is not None else time.time()) - created_ts) // 86400))


def parse_id(value: object) -> Optional[int]:
    """Accept ``123``, ``"123"``, ``"<#123>"``; anything else is ``None``."""
    text = str(value or "").strip().lstrip("<#@&!").rstrip(">")
    return int(text) if text.isdigit() else None


STRINGS: Dict[str, Dict[str, str]] = {
    "en": {
        "message": "👋 Welcome {mention} to **{server}**! If you need anything, just mention {bot} "
                   "and I'll be here for you.",
        "nick_button": "Set your name",
        "nick_title": "What should we call you?",
        "nick_label": "Your name (first and last)",
        "nick_done": "Done, you now appear as **{nick}** ✅",
        "nick_not_yours": "This button is for {mention}.",
        "nick_forbidden": "I can't change your name (missing permission or you rank above me). "
                          "Please ask an admin.",
        "notify": "🆕 {mention} (`{name}`) joined · account {age} days old · {source}",
        "source_invite": "invite `{code}` → {channel}{inviter}",
        "source_inviter": " by {inviter}",
        "source_unknown": "invite not identified",
        "raid_start": "⚠️ {count} joins in under {window}s. Greetings paused until things calm "
                      "down.",
        "raid_end": "✅ Join wave over: {count} greetings were skipped. Greetings resumed.",
    },
    "es": {
        "message": "👋 ¡Bienvenid@ {mention} a **{server}**! Cualquier cosa, escríbeme con {bot} y "
                   "estaré para ti.",
        "nick_button": "Pon tu nombre",
        "nick_title": "¿Cómo te llamamos?",
        "nick_label": "Tu nombre (nombre y apellido)",
        "nick_done": "Listo, ahora apareces como **{nick}** ✅",
        "nick_not_yours": "Este botón es para {mention}.",
        "nick_forbidden": "No puedo cambiarte el nombre (me falta permiso o tu rol está por encima "
                          "del mío). Pídeselo a un admin.",
        "notify": "🆕 {mention} (`{name}`) entró · cuenta de {age} días · {source}",
        "source_invite": "invitación `{code}` → {channel}{inviter}",
        "source_inviter": " creada por {inviter}",
        "source_unknown": "invitación no identificada",
        "raid_start": "⚠️ {count} ingresos en menos de {window}s. Pauso los saludos hasta que se "
                      "calme.",
        "raid_end": "✅ Terminó la ola de ingresos: omití {count} saludos. Los saludos siguen.",
    },
}


def strings(language: str) -> Dict[str, str]:
    return STRINGS.get((language or "en").lower()[:2], STRINGS["en"])
