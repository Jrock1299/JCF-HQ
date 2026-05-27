#!/usr/bin/env python3
"""
crisp_config.py — Shared configuration for Crisp v5.
Credentials, paths, constants, logging, Telegram.
"""

import json
import logging
import subprocess
import sys
import os
from datetime import datetime, timezone

# ─────────────────────────────────────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────────────────────────────────────

BASE_DIR          = '/root/.openclaw/agents/crisp'
DATA_DIR          = f'{BASE_DIR}/data'
LOG_FILE          = f'{BASE_DIR}/crisp_v5.log'
AUTH_PROFILES     = '/root/.openclaw/agents/main/agent/auth-profiles.json'

STRUCTURE_MAP_PATH   = f'{DATA_DIR}/structure_map.json'
SIGNAL_LOG_PATH      = f'{DATA_DIR}/signal_log.json'
SIGNAL_WEIGHTS_PATH  = f'{DATA_DIR}/signal_weights.json'
TRADE_HISTORY_PATH   = f'{DATA_DIR}/trade_history.json'
ACTIVE_POSITION_PATH = f'{DATA_DIR}/active_position.json'
CANDLE_CACHE_DIR     = f'{DATA_DIR}/candle_cache'
LEARNING_REPORTS_DIR = f'{DATA_DIR}/learning_reports'
DASHBOARD_TRADES     = '/root/.openclaw/dashboard/agent_trades.json'

# ─────────────────────────────────────────────────────────────────────────────
# CREDENTIALS
# ─────────────────────────────────────────────────────────────────────────────

def load_credentials():
    with open(AUTH_PROFILES) as f:
        auth = json.load(f)
    creds = auth['profiles']['binance_testnet:default']
    return creds['key'], creds['secret']

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────────

def setup_logging():
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s'
    )
    # Also log to stdout so systemd journal captures it
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logging.getLogger().addHandler(handler)

# ─────────────────────────────────────────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────────────────────────────────────────

TELEGRAM_UID = "797062420"

def send_telegram(message: str):
    try:
        subprocess.run(
            ["python3", "/root/.openclaw/scripts/telegram_monitor.py",
             "--channel", "telegram", "--target", TELEGRAM_UID,
             "--message", message],
            capture_output=True, timeout=10
        )
    except Exception as e:
        logging.warning(f"Telegram send failed: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# HUB
# ─────────────────────────────────────────────────────────────────────────────

sys.path.insert(0, '/root/.openclaw/scripts')
try:
    from hub_post import add_hub_message as hub_post
except Exception:
    def hub_post(agent, msg_type, message, tags=None):
        pass

AGENT_NAME = "crisp_v5"

# ─────────────────────────────────────────────────────────────────────────────
# TRADING CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

SYMBOL               = 'BTC/USDT'
PAPER_BALANCE_START  = 10_000.0
RISK_PER_TRADE_PCT   = 0.01        # 1% of balance per trade
MAX_DAILY_LOSS_PCT   = 0.03        # 3% daily loss limit → stop trading
MAX_CONSECUTIVE_LOSS = 4           # 4 losses in a row → 12h pause

# SL validation
MAX_SL_ATR_MULT      = 1.5         # Structural SL must be <= 1.5x H1 ATR
MIN_RR_RATIO         = 1.5         # TP must be >= 1.5x the SL distance

# Confluence thresholds
TRADE_THRESHOLD_BASE = 65          # Base minimum score to trade
TRADE_THRESHOLD_HIGH = 72          # During low-volume off-peak
TRADE_THRESHOLD_LOW  = 60          # During high-volume sessions
TRADE_THRESHOLD_LOSS_BOOST = 5     # +5 after a loss (for 2 hours)

# BE management
BE_ATR_MULT          = 0.5         # Move to BE after 0.5x H1 ATR profit

# Maximum hold times
MAX_HOLD_HOURS_NORMAL = 24
MAX_HOLD_HOURS_SWING  = 72

# Structure detection parameters
SWING_LOOKBACK        = 5          # Candles each side for swing detection
SR_ZONE_CLUSTER_PCT   = 0.002      # Swing points within 0.2% → same zone
SR_TOUCH_RADIUS_PCT   = 0.001      # 0.1% radius counts as a "touch"
LIQ_POOL_TOLERANCE    = 0.0005     # 0.05% tolerance for equal highs/lows
FVG_MIN_SIZE_PCT      = 0.0003     # Minimum FVG size (0.03% of price)

# Tiered polling windows (UTC hours)
ACTIVE_WINDOWS = [
    (6, 8),    # London open
    (13, 16),  # NY open
    (17, 20),  # NY afternoon
    (23, 1),   # Asia open (wraps midnight)
]
SCAN_INTERVAL_ACTIVE  = 300   # 5 minutes
SCAN_INTERVAL_QUIET   = 900   # 15 minutes

# Structure map recalculation interval
STRUCTURE_UPDATE_INTERVAL = 3600  # hourly

# ─────────────────────────────────────────────────────────────────────────────
# INITIAL SIGNAL WEIGHTS (written to signal_weights.json if not present)
# ─────────────────────────────────────────────────────────────────────────────

INITIAL_WEIGHTS = {
    "version": 1,
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "weights": {
        "liquidity_sweep": {
            "base_weight": 25,
            "max_contribution": 35,
            "min_score_alone": 70
        },
        "poc_reaction": {
            "base_weight": 20,
            "max_contribution": 30,
            "min_score_alone": 75
        },
        "fvg_fill": {
            "base_weight": 20,
            "max_contribution": 30,
            "min_score_alone": 75
        },
        "sr_reaction": {
            "base_weight": 18,
            "max_contribution": 28,
            "min_score_alone": 80
        },
        "trend_alignment": {
            "base_weight": 15,
            "max_contribution": 20,
            "min_score_alone": None
        },
        "orb_breakout": {
            "base_weight": 10,
            "max_contribution": 15,
            "min_score_alone": None
        },
        "volume_confirmation": {
            "base_weight": 8,
            "max_contribution": 12,
            "min_score_alone": None
        },
        "multi_timeframe": {
            "base_weight": 10,
            "max_contribution": 15,
            "min_score_alone": None
        }
    },
    "threshold": TRADE_THRESHOLD_BASE,
    "history": [
        {
            "version": 1,
            "date": datetime.now(timezone.utc).date().isoformat(),
            "changes": "Initial weights"
        }
    ]
}

def ensure_weights_file():
    if not os.path.exists(SIGNAL_WEIGHTS_PATH):
        with open(SIGNAL_WEIGHTS_PATH, 'w') as f:
            json.dump(INITIAL_WEIGHTS, f, indent=2)
        logging.info("Initialized signal_weights.json with default weights")

def ensure_signal_log():
    if not os.path.exists(SIGNAL_LOG_PATH):
        with open(SIGNAL_LOG_PATH, 'w') as f:
            json.dump({"signals": []}, f, indent=2)

def ensure_trade_history():
    if not os.path.exists(TRADE_HISTORY_PATH):
        with open(TRADE_HISTORY_PATH, 'w') as f:
            json.dump({"trades": [], "paper_balance": PAPER_BALANCE_START}, f, indent=2)

def init_data_files():
    ensure_weights_file()
    ensure_signal_log()
    ensure_trade_history()
