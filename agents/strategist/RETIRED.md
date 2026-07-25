# RETIRED — JARVIS (`strategist`)

**Retired:** 2026-07-25
**Absorbed by:** Lens
**What moved:** regime detection, Time-Based Edge Mapping, Multi-Timeframe Convergence, pre-session briefings
**Where it lives now:** agents/lens/lens_regime.py + agents/lens/run_lens_regime.sh

## Status
Parked, not deleted — same treatment as Crisp. This directory is preserved
intact so the agent can be revived or its history audited. Nothing here runs:

- All cron lines for this agent are marked `#HOLD RETIRED` (held permanently,
  not paused — see the crontab and CLAUDE.md §5).
- The agent is removed from the active roster in `hq-app/src/data/agentConfig.ts`
  and marked RETIRED in CLAUDE.md §2/§3.
- Message history and past reports are retained, not purged.

## Do not
- Do not re-enable the cron lines. The absorbing agent now owns this function;
  running both would double-post and, for JARVIS's outputs, would race on the
  same dashboard JSON.
- Do not import from this directory. Code here is the archived original and
  will not receive fixes. Import from the absorbing agent's module instead.
