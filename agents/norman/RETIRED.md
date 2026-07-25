# RETIRED — NORMAN (`norman`)

**Retired:** 2026-07-25
**Absorbed by:** Lens (Blade, Edge) and Victoria (Jerry, Chad)
**What moved:** Monte Carlo validation, sample-size gate, verdict synthesis
**Where it lives now:** scripts/risk_validation.py + agents/lens/lens_validator.py + agents/victoria/victoria_validator.py

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
  running both would double-post and, for NORMAN's outputs, would race on the
  same dashboard JSON.
- Do not import from this directory. Code here is the archived original and
  will not receive fixes. Import from the absorbing agent's module instead.
