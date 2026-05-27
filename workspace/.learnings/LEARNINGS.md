## [LRN-20260303-001] correction

**Logged**: 2026-03-03T00:00:00Z
**Priority**: medium
**Status**: pending
**Area**: infra

### Summary
Oracle Kalshi scan should run via local kalshi_python script, not web_search/browser tools.

### Details
I assumed Oracle needed web_search/browser to access Kalshi data. User clarified Oracle already has direct Kalshi API access via kalshi_python and should be run with python3 /root/.openclaw/agents/oracle/bot/oracle_bot.py. Web_search is only for future sports research.

### Suggested Action
Run oracle_bot.py directly for Kalshi scans and treat web_search/browser as optional for external sports research only.

### Metadata
- Source: user_feedback
- Related Files: /root/.openclaw/agents/oracle/bot/oracle_bot.py
- Tags: oracle, kalshi, data-access
- Pattern-Key: kalshi.oracle.direct_script
- Recurrence-Count: 1
- First-Seen: 2026-03-03
- Last-Seen: 2026-03-03

---
## [LRN-20260304-001] correction

**Logged**: 2026-03-04T08:27:00Z
**Priority**: high
**Status**: pending
**Area**: ops

### Summary
Morning workflow should auto-funnel capper picks to Oracle, log results daily at 9AM, and update HQ under Oracle Intelligence by capper.

### Details
User clarified expected behavior: every sports pick sent should be routed to Oracle; Oracle should automatically log results every morning at 9AM; results must be entered in HQ under Oracle Intelligence aligned to the specific capper; if capper missing, add the capper.

### Suggested Action
Define the automation flow, schedule, and HQ integration steps; implement a consistent intake format and result logging process.

### Metadata
- Source: user_feedback
- Related Files: AGENTS.md, TOOLS.md
- Tags: sports-bets, oracle, automation, hq
- Pattern-Key: workflow.sports_picks_oracle
- Recurrence-Count: 1
- First-Seen: 2026-03-04
- Last-Seen: 2026-03-04

---
## [LRN-20260320-001] correction

**Logged**: 2026-03-20T07:01:00Z
**Priority**: high
**Status**: pending
**Area**: docs

### Summary
User reiterated that morning reports must not include pictures.

### Details
Jase corrected that I kept sending images in the morning report after he explicitly said no more pictures the night before.

### Suggested Action
Stop including any images in morning reports; send text-only updates by default.

### Metadata
- Source: user_feedback
- Related Files: MEMORY.md
- Tags: reporting, formatting, user_preference
- Recurrence-Count: 1
- First-Seen: 2026-03-20
- Last-Seen: 2026-03-20

---
