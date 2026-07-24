# Discord Bot — Two-Way (#ask-the-team + #risk-calculator)

**Status: LIVE (2026-07-24).** pm2 `jcf-discord-bot`, watching 2/2 channels.
Verified end-to-end in Discord — Norman graded a risk scenario in
#risk-calculator; Lens + Jarvis answered a concentration question in
#ask-the-team, each under their own name via the channel webhook.

A gateway bot ("Hunxho Bot") that **listens** on two channels and replies as
the relevant JCF HQ agents. Separate from the one-way broadcast webhooks in
[[discord-broadcast]] / CLAUDE.md §4f — this is the interactive half.

## What it does

| Channel | Trigger | Behavior |
|---|---|---|
| `#ask-the-team` | Jase asks any question | The relevant agents each answer **in their own voice**, posted under their own name+avatar. "Individual named agents" design (not a single synthesis). |
| `#risk-calculator` | "risking $X on [asset] to gain $Y" (natural phrasing) | **Norman** grades the risk — real R-multiple + %-of-account math against his rails — with tone that shifts on the framing (quick-money vs disciplined). |

## Identity model (important)

The bot's own login is used **only for listening**. Every visible reply is
posted through a **channel webhook** with a per-message `username`+`avatar_url`
override (reusing `scripts/discord_notify.py`'s `_DISPLAY` / `_avatar_url`), so
replies appear to come from **Norman / Lens / Victoria / Blade / Jarvis…** by
name — never the bot's generic identity.

A Discord webhook is bound to one channel, so a broadcast-channel webhook can't
be reused to post into `#ask-the-team`. The bot needs a webhook that lives *in*
each interaction channel. Two ways to provide it:

- **Path A (auto):** give the bot **Manage Webhooks** in the two channels; on
  startup it creates/reuses a webhook named `JCF HQ Agents` in each.
- **Path B (manual):** create one webhook per channel by hand and set
  `DISCORD_ASK_TEAM_WEBHOOK` / `DISCORD_RISK_CALC_WEBHOOK` in `.env`. The bot
  posts to those directly — **no permission needed**. Overrides Path A.

## Files

| Path | Role |
|---|---|
| `agents/discord_bot/bot.py` | Gateway listener (discord.py), scoped to the 2 channel ids. |
| `agents/discord_bot/fanout.py` | `#ask-the-team` router + per-agent in-voice replies (reuses `hub_collab` context gatherers). |
| `agents/discord_bot/risk_calc.py` | Norman's risk parser + math + voice. Deterministic; optional Codex phrasing pass. |
| `agents/discord_bot/agent_llm.py` | Shared Codex-gateway call helper (Norman/Lucy `_run_codex` pattern, `openai/gpt-5.6-terra`). |
| `agents/discord_bot/run_bot.sh` | Launcher — sources `.env`, runs the openclaw venv python, `PYTHONUNBUFFERED=1`. |
| `agents/discord_bot/ecosystem.config.js` | pm2 process def (`jcf-discord-bot`). |

## Config (`.env`, gitignored)

```
DISCORD_BOT_TOKEN=…                       # bot login (listen only)
DISCORD_ASK_TEAM_CHANNEL_ID=1530249469864579243
DISCORD_RISK_CALC_CHANNEL_ID=1447202000327540766
# DISCORD_ASK_TEAM_WEBHOOK=  / DISCORD_RISK_CALC_WEBHOOK=   # Path B (optional)
# DISCORD_AVATAR_BASE=       # public <agent>.png host for reply avatars (else name-only)
# DISCORD_RISK_USE_LLM=0     # 1 = phrase Norman's reply via Codex; 0 = deterministic
```

Bot **Application/Client ID:** `1426900644660514847`.
**Invite URL** (scopes `bot applications.commands`; perms View Channels, Send
Messages, Embed Links, Read Message History, Manage Webhooks):
`https://discord.com/api/oauth2/authorize?client_id=1426900644660514847&permissions=536955904&scope=bot%20applications.commands`

## Run / operate

```
pm2 start   agents/discord_bot/ecosystem.config.js
pm2 restart jcf-discord-bot     # after granting Manage Webhooks or setting webhook URLs
pm2 logs    jcf-discord-bot
pm2 save
```

## Requirements / gotchas

- **Message Content intent** (privileged) must be ON in the Developer Portal →
  Bot → Privileged Gateway Intents. (Verified ON 2026-07-24.) Without it,
  message text arrives empty and the bot logs a warning.
- **Manage Webhooks** (or Path B webhook URLs) is required to post agent-identity
  replies. Granted 2026-07-24 (Path A — Manage Webhooks on the "Hunxho Hoot"
  role); the bot now auto-creates a `JCF HQ Agents` webhook in each channel and
  watches 2/2. Note: re-running the OAuth invite for an already-present bot does
  NOT refresh its role perms — toggle the role permission directly, or re-invite
  fresh.
- **Avatars:** reply *names* always work; *avatars* need `DISCORD_AVATAR_BASE`
  (a public host for `<agent>.png` — the repo is private, so GitHub-raw won't do).
- The bot ignores its own and all webhook/bot messages (loop-safe) and only acts
  on the two configured channels.
