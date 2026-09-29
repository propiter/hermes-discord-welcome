# discord-welcome (Hermes plugin)

Greets every new member of a Discord server, **in the channel of the invite they used**.

- Detects the invite by comparing invite use counts before/after the join (the only way Discord
  allows). If it can't tell (two joins at once, no permission), greets in a fallback channel.
- Only greets in a channel the newcomer can actually see and the bot can post in.
- ✏️ **Set your name** button: the newcomer sets their server nickname from a form.
- 🆕 **Staff notice** (optional, private channel): who joined, invite, who created it, account age.
- ⚠️ **Join-wave guard**: over N joins in a window, greetings pause and staff are told once.
- No LLM calls. Nothing runs on a timer: everything is triggered by the join or a click.

## Requirements

1. **Server Members Intent** enabled for the bot (Developer Portal → Bot → Privileged Gateway
   Intents).
2. **Manage Server** permission to read invites. Without it, every greeting goes to the fallback
   channel.
3. **Manage Nicknames** for the name button (and the bot's role above the newcomer's roles).

## How it works

Hermes' Discord adapter doesn't request the Server Members intent unless an allowlist needs it, so
`on_member_join` never reaches it. The plugin opens a second, minimal gateway session with the same
token, subscribed to guilds, members and invites only. It never receives messages, so the bot can
never answer twice.

## Install

```bash
hermes plugins install propiter/hermes-discord-welcome --enable
hermes config set plugins.entries.discord-welcome.settings.language es
hermes config set plugins.entries.discord-welcome.settings.notify_channel <staff-channel-id>
# restart the gateway
```

## Settings (`plugins.entries.discord-welcome.settings`)

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Master switch |
| `language` | `en` | Built-in texts: `en`, `es` |
| `message` | built-in | Placeholders: `{mention} {name} {server} {bot} {member_count}` |
| `greet_in_invite_channel` | `true` | Greet where the invite points |
| `greet_channel` | — | Always greet here (overrides invite routing) |
| `fallback_channel` | system channel | When the invite can't be identified |
| `notify_channel` | — (off) | Private staff notices |
| `nickname_button` | `true` | "Set your name" button |
| `raid_threshold` / `raid_window_seconds` | `5` / `60` | Join-wave guard (`0` = off) |
| `ignore_bots` | `true` | Don't greet bots |
| `guilds` | all | Restrict to these server IDs |

## Tests

```bash
uv run --no-project --with pytest --with discord.py python -m pytest -q
```

License: MIT
