from discord_welcome.logic import InviteInfo, RaidGuard, detect_invite, parse_id, render
from discord_welcome.settings import Settings


def inv(code, uses, max_uses=0, channel=1):
    return InviteInfo(code, uses, max_uses, channel, 99)


def test_detects_the_invite_whose_uses_went_up():
    before = {"a": inv("a", 1), "b": inv("b", 0, channel=2)}
    after = {"a": inv("a", 1), "b": inv("b", 1, channel=2)}
    assert detect_invite(before, after).code == "b"


def test_new_invite_used_right_away_counts():
    assert detect_invite({}, {"n": inv("n", 1)}).code == "n"


def test_last_use_deletes_the_invite():
    before = {"x": inv("x", 0, max_uses=1, channel=7)}
    found = detect_invite(before, {}, deleted=["x"])
    assert found.code == "x" and found.channel_id == 7


def test_ambiguous_or_unknown_returns_none():
    before = {"a": inv("a", 0), "b": inv("b", 0)}
    assert detect_invite(before, {"a": inv("a", 1), "b": inv("b", 1)}) is None
    assert detect_invite(before, dict(before)) is None
    # deleted by a moderator (not at its limit) is not a use
    assert detect_invite({"a": inv("a", 3)}, {}, deleted=["a"]) is None


def test_raid_guard_lifecycle():
    now = [0.0]
    guard = RaidGuard(threshold=3, window=60, clock=lambda: now[0])
    assert [guard.record() for _ in range(2)] == ["normal", "normal"]
    assert guard.record() == "start"
    assert guard.record() == "ongoing"
    now[0] = 200.0
    assert guard.record() == "ended" and guard.suppressed == 2
    assert guard.record() == "normal"


def test_raid_guard_disabled():
    guard = RaidGuard(threshold=0)
    assert all(guard.record() == "normal" for _ in range(20))


def test_render_is_forgiving():
    assert render("hi {mention} {nope}", {"mention": "@a"}) == "hi @a {nope}"
    assert render("broken {", {}) == "broken {"


def test_parse_id():
    assert parse_id("<#123>") == 123 and parse_id(" 45 ") == 45 and parse_id("") is None
    assert parse_id("general") is None


def test_settings_load_types():
    raw = {"greet_channel": "<#10>", "raid_threshold": "7", "nickname_button": "false",
           "guilds": "1, 2", "language": "es"}
    s = Settings.load(lambda k, d=None: raw.get(k, d))
    assert s.greet_channel == 10 and s.raid_threshold == 7 and not s.nickname_button
    assert s.guilds == frozenset({1, 2}) and s.language == "es" and s.notify_channel is None
    assert Settings.load(lambda k, d=None: d).enabled
