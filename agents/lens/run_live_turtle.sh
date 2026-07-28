#!/usr/bin/env bash
# run_live_turtle.sh — one 15-minute tick of the live turtle executor.
# Invoked from cron every 15 minutes during killzones. Exits fast if no
# deployable entries or no killzone match — safe to fire even on off-hours.
#
# Usage:
#   run_live_turtle.sh                   # live paper
#   DRY_RUN=1 run_live_turtle.sh         # detect only, place no orders
#
# Cron:
#   */15 * * * 1-5  bash /root/.openclaw/agents/lens/run_live_turtle.sh \
#       >> /root/.openclaw/logs/live_turtle.log 2>&1
#
# The executor is stateless per-tick; a missed tick loses at most one
# candle's opportunity, not a position. OANDA holds the SL+TP brackets
# server-side.
set -euo pipefail

cd /root/.openclaw

# Load env for OANDA + Telegram creds
set -a
[ -f .env ] && source .env
set +a

DRY=""
if [ "${DRY_RUN:-0}" = "1" ]; then
  DRY="--dry-run"
fi

exec python3 agents/lens/live_turtle_executor.py --agent blade $DRY
