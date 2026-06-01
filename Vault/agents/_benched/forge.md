# Forge — Benched

**Internal id:** `forge`
**Status:** **Benched** 2026-06-01. Code preserved on disk. Not on cron.
Not in systemd.

## What Forge was
HTML dashboard and Excel spreadsheet builder. Used Claude API to generate
product code directly (no web search). Built premium dashboards for
ad-hoc projects.

## Why benched
- Idle since 2026-04-17 (~1.5 months at the time of benching)
- Non-trading focus — JCF HQ is consolidating around the trading system
- Never had a cron entry; only ran on demand via hub_collab routing

## Key files (preserved)
- `agents/forge/forge_brain.py`
- `agents/forge/forge_config.py`
- `agents/forge/forge_reviewer.py`
- `agents/forge/templates/`
- `agents/forge/builds/` — past outputs
- `logs/forge_api_costs.json`

## Revival path
1. Restore an on-demand invocation route (Telegram command or hub_collab)
2. Update its skills imports (might benefit from the
   [[../../infrastructure/model-routing|skills methodology approach]] we
   adopted 2026-06-01)
3. Connect to [[../jerry]] or [[../victoria]] as a product-generation backend
   if useful (dashboard builders for them)

## Cross-agent connections
- Was a sibling to [[naomi]] (Naomi wrote Etsy listings for Forge's product
  outputs — they were a creator/e-commerce pair)

## Decision log
See [[../../decisions/decision-log#forge-naomi-advisor-benched-2026-06-01]].
