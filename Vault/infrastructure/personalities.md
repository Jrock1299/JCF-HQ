# Telegram Personalities

How JCF HQ agents speak to Jase.

## The wrapper system

`scripts/telegram_personalities.py` provides `wrap_message(agent_id, body)`.

Every outbound Telegram message goes through this function. It produces:

```
{emoji} {DISPLAY_NAME}
{body}
— via H
```

Huncho's own messages skip the `— via H` footer (his messages already
sign with `— H`).

## Internal id → display name aliases

`AGENT_DISPLAY` map handles cases where the internal id differs from the
Telegram-facing name:

```python
AGENT_DISPLAY = {
    'strategist': 'JARVIS',   # internal id stays 'strategist' for backward compat
}
```

This means:
- `wrap_message('strategist', body)` → `♟️ JARVIS` header + `— via H` footer
- Code paths, JSON keys, file names still use `strategist` everywhere else

**Why aliasing instead of renaming the internal id:** the rename would
break historical JSON / log queries / cron entries / module paths. The
alias map is a thin layer that only affects user-facing text.

## Emoji + voice per agent

| Agent | Emoji | Display | Voice |
|---|---|---|---|
| [[../agents/huncho]] | 👑 | HUNCHO | NY mob-boss. Terse, knowing, slightly amused. *"Aye." "My guy." "— H"* |
| [[../agents/jarvis]] | ♟️ | JARVIS | Calm right-hand-man. Composed. Three steps ahead. *"Morning read is in. — Jarvis"* |
| [[../agents/blade]] | 🔪 | BLADE | Stoic military report. *"LONG SPX500 @ 7600 \| SL 7582"* |
| [[../agents/edge]] | 📡 | EDGE | Clinical, laconic. |
| [[../agents/jerry]] | 📊 | JERRY | Professional money manager. |
| [[../agents/lens]] | 🌐 | LENS | Macro analyst — measured, sources its claims. |
| [[../agents/norman]] | ⚠️ | NORMAN | Brutally honest, cold. *"FAIL. Suspend live trading."* |
| [[../agents/victoria]] | 🧛‍♀️ | VICTORIA | Gothic queen — owns the operation. *"The coffers neither grew nor shrank."* |
| [[../agents/tao]] | ☯️ | TAO | Zen. |
| [[../agents/lucy]] | 🔍 | LUCY | Curious researcher. |

[[../agents/sentinel|Sentinel]] has no Telegram personality — it's a data
pipeline. Its outputs surface through other agents.

## Format example

A typical [[../agents/blade]] session-end summary:

```
🔪 BLADE
LONDON SESSION COMPLETE
Date: 2026-06-02 | 08:00 – 12:00 UTC

Trades taken:
- SPX500 LONG → TP1 ✅ TP2 ✅ TRAIL ✅ | +$138.00

Session P&L: +$138.00
Running balance: $5,138.00
Sessions today: 1/3 complete
— via H
```

## Recent changes (2026-06-01)
- Removed the `━━━━━━━━━━━━━━━━━━━━━━` separator bars on every line.
  Cleaner conversational format.
- "reported to H" → "— via H" footer.
- Added Jarvis (♟️) alias.
- Removed Oracle (🔮) entry — Oracle deleted.

See [[../sessions/2026-06-01]].

## Related
- [[../agents/huncho]] — owner of the wrapper system + Telegram routing
- [[system-architecture]]
