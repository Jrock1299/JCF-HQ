# Advisor — Retired

**Internal id:** `advisor`
**Status:** **Retired** 2026-04-15. Replaced by [[../victoria]]. Code on
disk but no scheduled runs. Cron entries fully removed 2026-06-01.

## What Advisor was
Pre-session strategy briefer and session-prep alerter. Two cron jobs:
- `0 22 * * 1-5` — daily advisor run
- `53 17 / 53 7 * * 1-5` — session prep for NY_PM and LONDON

## Why retired
Victoria absorbed the strategic-summary role. Session prep moved to the
new [[../huncho|Huncho]] session_prep_ping pipeline.

## Cleanup
- All 3 cron entries deleted (not just commented) on 2026-06-01
- No systemd service existed
- Code dir preserved: `agents/advisor/` with the legacy reports and prep
  scripts

## Key files (preserved)
- `agents/advisor/collect_data.py`
- `agents/advisor/session_prep.py`
- `agents/advisor/run_advisor.sh`
- `agents/advisor/strategy_redesign_report.md`
- `agents/advisor/spx500_strategy_report.md` / `spx500_strategy_v2_report.md`
- `agents/advisor/CLAUDE.md`

## Decision log
See [[../../decisions/decision-log#forge-naomi-advisor-benched-2026-06-01]].
