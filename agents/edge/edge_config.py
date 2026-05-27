"""
Edge — Configuration
Constants for the 1H SMA 8/21 crossover strategy.
"""

# ─────────────────────────────────────────────────────────────────────────────
# IDENTITY
# ─────────────────────────────────────────────────────────────────────────────

AGENT_NAME      = "edge"
INSTRUMENT      = "SPX500_USD"

GRANULARITY_H1  = "H1"
GRANULARITY_H4  = "H4"
SMA_FAST        = 8
SMA_SLOW        = 21

CANDLE_COUNT_H1 = 50         # 50 H1 candles covers ~2 days of trend context
CANDLE_COUNT_H4 = 50

UNITS              = 2       # OANDA units per position; cluster = 3 × UNITS = 6 total
POLL_INTERVAL_SECS = 300     # 5 minutes between ticks

# Cluster TPs (points from entry)
TP1_PTS = 15
TP2_PTS = 25

# 4H trend filter — only take longs if H4 SMA8 > SMA21, shorts if <.
USE_H4_FILTER = True

# Don't trade during the first N minutes after the US cash open.
# 13:30 UTC = 9:30 ET during DST (matches current strategy window).
MARKET_OPEN_UTC          = (13, 30)
MARKET_OPEN_BLACKOUT_MIN = 15

# ─────────────────────────────────────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────────────────────────────────────

LOG_PATH           = '/root/.openclaw/agents/edge/edge_v5.log'
TRADE_HISTORY_PATH = '/root/.openclaw/agents/edge/data/trade_history.json'
DAILY_STATS_PATH   = '/root/.openclaw/agents/edge/data/daily_stats.json'
PORTFOLIO_PATH     = '/root/.openclaw/agents/edge/data/edge_portfolio.json'
PORTFOLIO_DASH     = '/root/.openclaw/dashboard/edge_portfolio.json'
AGENT_TRADES_PATH  = '/root/.openclaw/dashboard/agent_trades.json'
AGENT_PNL_PATH     = '/root/.openclaw/dashboard/agent_pnl.json'

# ─────────────────────────────────────────────────────────────────────────────
# OANDA
# ─────────────────────────────────────────────────────────────────────────────

OANDA_ACCOUNT_ID   = '101-001-22502524-002'   # Scalper account
OANDA_ENVIRONMENT  = 'practice'
AUTH_PROFILES_PATH = '/root/.openclaw/agents/main/agent/auth-profiles.json'

# ─────────────────────────────────────────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────────────────────────────────────────

TELEGRAM_UID = "797062420"

# ─────────────────────────────────────────────────────────────────────────────
# RISK MANAGEMENT (preserved from prior strategy)
# ─────────────────────────────────────────────────────────────────────────────

MAX_DAILY_LOSSES   = 5       # Halt new entries after N losing clusters
MAX_DAILY_LOSS_PCT = 2.0     # Halt if intraday drawdown >= N% of balance
MAX_HOLD_MINUTES   = 1440    # Force-close any cluster held > 24h (safety net)
