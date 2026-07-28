#!/usr/bin/env bash
# run_edge_live_turtle.sh — Edge's tick of the live turtle executor.
# Edge trades SPX500_USD only (its historical scope). It uses its own OANDA
# practice account 101-001-22502524-002 so its book is separate from Blade's.
# Same shared executor as Blade — one behaviour, one code path.
#
# Edge's original 1H SMA 8/21 strategy was never validated through the
# library gate; this replaces it with the deployable turtle_soup entry for
# SPX500_USD. If turtle_soup is ever un-deployed for SPX500_USD the
# executor logs NO_DEPLOYABLE_ENTRIES and Edge idles — the correct behaviour.
#
# Uncovered instruments (Edge might one day add DE30/XAU): the same script
# will pick them up automatically once library entries exist. No config edit.
set -euo pipefail

cd /root/.openclaw
set -a
[ -f .env ] && source .env
set +a

DRY=""
if [ "${DRY_RUN:-0}" = "1" ]; then
  DRY="--dry-run"
fi

# Edge's OANDA practice account (the Scalper account per edge_config.py).
EDGE_ACCOUNT_ID="${EDGE_ACCOUNT_ID:-101-001-22502524-002}"

exec python3 agents/lens/live_turtle_executor.py \
    --agent edge \
    --instrument SPX500_USD \
    --account-id "$EDGE_ACCOUNT_ID" \
    $DRY
