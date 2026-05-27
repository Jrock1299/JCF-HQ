#!/bin/bash
set -euo pipefail
SRC_DIR="/root/.openclaw/dashboard"
PUB_DIR="/root/.openclaw/dashboard/public"

# Ensure public dir
mkdir -p "$PUB_DIR"

# Core HTML
cp "$SRC_DIR/jcf_hq.html" "$PUB_DIR/jcf_hq.html"

# JSON feeds required by HQ
for f in \
  tradelocker_trades.json \
  agent_trades.json \
  agent_pnl.json \
  oracle_picks.json \
  market_bias.json \
  bet_log.json \
  robinhood_data.json \
  trustwallet_data.json \
  net_worth.json \
  sports_intel.json \
  capper_intel.json \
  morning_report.json \
  picks_feed.json \
  oracle_bankroll.json \
  oracle_resolved.json \
  bball_stats.json \
  politics_dashboard.html \
  sports_dashboard.html \
  trading_dashboard.html \
  oracle_dashboard.html; do
  if [ -f "$SRC_DIR/$f" ]; then
    cp "$SRC_DIR/$f" "$PUB_DIR/$f"
  fi
 done

echo "sync_dashboard_public: ok"