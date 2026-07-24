# 💬 Discord Integration

**Added:** 2026-07-24. Agents broadcast to Discord **alongside** Telegram (never
replacing it) via `scripts/discord_notify.py`. Webhooks live in `.env`
(gitignored) as `DISCORD_WEBHOOK_<CHANNEL>`; avatars via `DISCORD_AVATAR_BASE`.

## Channel layout (Jase's 6-category plan + 2 adds = ~21)

| Category | Channels |
|---|---|
| 📢 GENERAL | morning-report, alerts, jcf-hq-updates, **system-status** ⬅ add |
| 🌐 MARKET INTEL | lens, jarvis, sentinel |
| 💹 TRADING | blade, edge, jerry, chad |
| 💰 FINANCE & RISK | victoria, norman, portfolio-thesis, council-theses, **net-worth** ⬅ add |
| 🔍 RESEARCH & GROWTH | lucy, tao, business-ideas |
| 💬 DISCUSSION | general-chat, ask-the-team |

`#trades`/`#fills` was considered and **skipped** for now (per-agent channels
already carry fills; revisit if a consolidated feed is wanted).

## Webhook env-var names (`.env`)
`DISCORD_WEBHOOK_MORNING_REPORT`, `_ALERTS`, `_JCF_HQ_UPDATES`, `_SYSTEM_STATUS`,
`_LENS`, `_JARVIS`, `_SENTINEL`, `_BLADE_SIGNALS`, `_EDGE`, `_JERRY_PAPER`,
`_CHAD`, `_VICTORIA`, `_NORMAN`, `_PORTFOLIO_THESIS`, `_COUNCIL_THESES`,
`_NET_WORTH`, `_LUCY`, `_TAO`, `_BUSINESS_IDEAS`, `_GENERAL_CHAT`, `_ASK_THE_TEAM`.
Add each to `.env`; the agent posts there automatically (no-op until it exists).

## The two new posters (built, cron HELD until webhooks exist)

### `#net-worth` — `scripts/net_worth_report.py` (daily 11:00 UTC)
- **Real net worth** = Robinhood `total_equity` + Kraken `total_usd` + TrustWallet
  `total_usd` + HYSA/life-insurance (`net_worth.json` manual) + Plaid banks (only
  if fresh ≤5d) + Mercury (if >0).
- **Alpaca (Jerry) is PAPER** — shown separately, NOT counted as net worth.
- Stale/unwired feeds (Plaid last synced Apr, Mercury placeholder) are **flagged**,
  never silently counted.
- Current sample: real **$26,401** (RH $12.9k / Kraken $13.4k / TW $1) · paper
  Alpaca $100k · goal $10M (0.3%).

### `#system-status` — `scripts/system_status_report.py` (daily 07:00 + 19:00 UTC)
- Classifies every agent 🟢 Live / ⏸️ Held / 🔴 Down from the **live crontab**
  (active vs `#HOLD`), **systemd** (jerry/edge/crisp-v5), and output freshness.
- Positive "what's running" glance — distinct from `#alerts` (breakage only).
- Current sample: 🟢 12 live · ⏸️ 1 held (Chad) · 🔴 1 down (Edge — OANDA auth).

**To activate both:** add the webhook to `.env`, then remove `#HOLD` from their
cron lines.

## What to mirror from the React app (vs keep in-app)
- **Mirror → Discord:** headline numbers (net worth, P&L, MTD), account balances,
  agent status roster, each agent's report text, alerts — the *push-to-pocket* stuff.
- **Keep in React:** interactive charts, sparklines, editable values, drill-downs.
  Discord is glances + notifications, not an interactive dashboard.

## Phase 2 — `#ask-the-team` two-way (OpenClaw Discord bot connector)
Webhooks are **one-way** (post only) — they cannot read Jase's questions. True
`#ask-the-team` (Jase asks → relevant agents answer, mirroring the dashboard
Agent Hub broadcast) needs a **read-capable Discord bot**. Plan:

1. **Use OpenClaw's built-in Discord channel connector** (`openclaw channels add
   discord` — same system that runs Huncho on Telegram). It gives a real bot
   token with read+write, not just a webhook.
2. **Bind it to `#ask-the-team`** (and `#general-chat`). Inbound messages route to
   Huncho/the main agent, which fans the question out to the relevant sub-agents
   and posts their replies back — reusing the existing Agent-Hub broadcast logic.
3. **Auth:** bot token in `.env` / gateway config (gitignored), not a webhook.
4. **Scope guard:** read/reply only in the two discussion channels; the other ~19
   channels stay webhook-only (one-way agent broadcasts).
5. **Effort:** medium — mostly wiring the connector + a fan-out handler; no new
   agent logic. Not blocking the 19 posting channels, which work on webhooks now.

## Related
- [[../../CLAUDE.md]] §4f (Discord broadcast) · `scripts/discord_notify.py`.
- Wiring status: **Lens** is the pilot (posts to `#lens`); the rest of the roster
  gets wired once Jase provides webhooks + the first live delivery is confirmed.
