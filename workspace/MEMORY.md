# Memory

## User preferences
- Reports must be TEXT ONLY; never send images or charts. Plain text with emojis and spacing.
- System Upgrades: Generate a structured "System Upgrade Report" (Status, Location, Capabilities, Operational Impact) for the team anytime a new tool or system is downloaded.
- Oracle bankroll is $500.
- NY session opens at 13:30 UTC (9:30 AM EDT) during daylight saving time.

## Current system state
- Crisp: paper_balance fix deployed; wait_for_session_open fixed with >= logic; DST corrected to 13:30 UTC.
- Blade: Full ORB strategy implemented; DST corrected.
- Oracle: resolve_picks.py reads from /root/.openclaw/dashboard/oracle_picks.json and appends to oracle_resolved.json.
- Lens: Tavily key hardcoded in search.mjs; stale session history cleared.
- Agent Hub: backend live at /hq/hub; all 5 agents wired to post.
- Bet sync: sync_bet_log.py runs every 5 min via cron.
- Kalshi bot: live 15M crypto momentum bot at /root/kalshi-bot/; systemd service kalshi-bot.service; starting bankroll $20.64 (Mar 2026). Full details in docs/kalshi_setup.md.
- Model: Codex is primary; re-auth via openclaw configure when OAuth expires.
- Memory: flush prompt customized; session indexing enabled; memorySearch sources set to memory+sessions.
