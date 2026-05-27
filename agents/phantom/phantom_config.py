"""
phantom_config.py — Exchange connection, constants, and shared helpers for Phantom.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import ccxt
import requests
from dotenv import load_dotenv

load_dotenv('/root/.openclaw/agents/phantom/.env')

# ── Exchange — Phemex Perpetuals Testnet ───────────────────────────────────────
#
# Keys are generated at https://testnet.phemex.com  (create a testnet account).
# They are DIFFERENT from Phemex mainnet keys.
#
# Testnet base: https://testnet-api.phemex.com
# ccxt enables testnet by replacing the api URLs with the test URLs.

PHEMEX_API_KEY    = os.getenv('PHEMEX_API_KEY', '')
PHEMEX_API_SECRET = os.getenv('PHEMEX_API_SECRET', '')

# Detect whether real credentials have been pasted in
_CREDS_READY = (
    bool(PHEMEX_API_KEY) and
    PHEMEX_API_KEY not in ('PASTE_HERE', 'YOUR_KEY_HERE', '') and
    bool(PHEMEX_API_SECRET) and
    PHEMEX_API_SECRET not in ('PASTE_HERE', 'YOUR_SECRET_HERE', '')
)

# Build exchange — include credentials only when they're real keys.
_exchange_params: dict = {
    'enableRateLimit': True,
    'options': {
        'defaultType': 'swap',   # perpetual futures
    },
}
if _CREDS_READY:
    _exchange_params['apiKey'] = PHEMEX_API_KEY
    _exchange_params['secret'] = PHEMEX_API_SECRET

exchange = ccxt.phemex(_exchange_params)

# Switch all API endpoints to the Phemex testnet
exchange.urls['api'] = exchange.urls['test']

# ── Instruments ────────────────────────────────────────────────────────────────
# USDT-margined perpetuals available on Phemex testnet.

INSTRUMENTS = [
    'BTC/USDT:USDT',
    'ETH/USDT:USDT',
    'XRP/USDT:USDT',
    'SOL/USDT:USDT',
    'LINK/USDT:USDT',   # OHLCV/backtest OK; live ticker unavailable on Phemex testnet
]

# ── Risk ───────────────────────────────────────────────────────────────────────

STARTING_BALANCE  = 10_000.0   # testnet notional USDT
SAFETY_FLOOR_PCT  = 0.25       # halt at 25% of starting balance

# ── Backtest quality gates ─────────────────────────────────────────────────────

BACKTEST_MIN_TRADES   = 10
BACKTEST_MIN_WIN_RATE = 40.0   # %
BACKTEST_MIN_PF       = 1.1
BACKTEST_MAX_RUIN     = 15.0   # %
BACKTEST_MIN_SHARPE   = 0.3

# ── Cycle timings ──────────────────────────────────────────────────────────────
#
# Execution ticks every 5 minutes (continuous). Review and discovery are
# wall-clock scheduled inside the main loop — no cron required.

MAIN_LOOP_SECS         = 300    # 5 minutes between market/execution checks

# Daily review: each UTC day once we pass DAILY_REVIEW_HOUR.
DAILY_REVIEW_HOUR      = 21     # 21:00 UTC

# Weekly discovery: each ISO week on WEEKLY_DISCOVERY_WEEKDAY once past the hour.
# weekday(): Monday=0 … Saturday=5, Sunday=6. Scheduled for 11:00 UTC so
# Norman's 10:00 UTC report is guaranteed to be on disk before we read it.
WEEKLY_DISCOVERY_WEEKDAY = 5    # Saturday
WEEKLY_DISCOVERY_HOUR    = 11   # 11:00 UTC

# ── Telegram ───────────────────────────────────────────────────────────────────

TELEGRAM_TOKEN   = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_ALERT_CHAT_ID') or os.getenv('TELEGRAM_CHAT_ID', '')
TG_MAX           = 4000

# ── Paths ──────────────────────────────────────────────────────────────────────

PHANTOM_DIR      = Path('/root/.openclaw/agents/phantom')
DATA_DIR         = PHANTOM_DIR / 'data'
LOG_PATH         = PHANTOM_DIR / 'phantom.log'
STRATEGIES_PATH  = DATA_DIR / 'strategies.json'
TRADE_HISTORY_PATH = DATA_DIR / 'trade_history.json'
DISCOVERY_LOG_PATH = DATA_DIR / 'discovery_log.json'
PERFORMANCE_PATH   = DATA_DIR / 'performance.json'
DASHBOARD_PATH     = Path('/root/.openclaw/dashboard/phantom_portfolio.json')
API_COSTS_PATH     = Path('/root/.openclaw/logs/phantom_api_costs.json')
NORMAN_REPORT_PATH = Path('/root/.openclaw/dashboard/norman_report.json')
SCHEDULE_STATE_PATH = DATA_DIR / 'schedule_state.json'

# ── Models ─────────────────────────────────────────────────────────────────────

DISCOVER_MODEL  = 'claude-sonnet-4-6'
REVIEW_MODEL    = 'claude-sonnet-4-6'
CONDITION_MODEL = 'claude-sonnet-4-6'


# ── Logging ────────────────────────────────────────────────────────────────────

def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        fh = logging.FileHandler(LOG_PATH)
        fh.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)-8s [%(name)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)-8s [%(name)s] %(message)s',
            datefmt='%H:%M:%S'
        ))
        logger.addHandler(fh)
        logger.addHandler(sh)
    return logger


# ── Telegram ───────────────────────────────────────────────────────────────────

def _tg_send_chunk(text: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print('[phantom] Telegram not configured')
        return False
    try:
        resp = requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={'chat_id': TELEGRAM_CHAT_ID, 'text': text},
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f'[phantom] Telegram error: {e}')
        return False


def send_telegram(text: str) -> None:
    if len(text) <= TG_MAX:
        _tg_send_chunk(text)
        return
    chunks, current = [], ''
    for line in text.split('\n'):
        candidate = current + ('\n' if current else '') + line
        if len(candidate) > TG_MAX:
            if current:
                chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    for chunk in chunks:
        _tg_send_chunk(chunk)


# ── API cost tracking ──────────────────────────────────────────────────────────

def save_api_cost(module: str, input_tokens: int, output_tokens: int,
                  web_searches: int = 0) -> float:
    cost_usd = round(
        (input_tokens  * 3  / 1_000_000) +
        (output_tokens * 15 / 1_000_000),
        6,
    )
    entry = {
        'date':          datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'timestamp':     datetime.now(timezone.utc).isoformat(),
        'module':        module,
        'input_tokens':  input_tokens,
        'output_tokens': output_tokens,
        'web_searches':  web_searches,
        'cost_usd':      cost_usd,
    }
    try:
        costs = json.loads(API_COSTS_PATH.read_text()) if API_COSTS_PATH.exists() else []
        costs.append(entry)
        API_COSTS_PATH.write_text(json.dumps(costs, indent=2))
    except Exception as e:
        print(f'[phantom] cost log error: {e}')
    return cost_usd


# ── JSON helpers ───────────────────────────────────────────────────────────────

def load_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception as e:
        print(f'[phantom] JSON load error {path}: {e}')
    return default


def save_json(path: Path, data) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, default=str))
    except Exception as e:
        print(f'[phantom] JSON save error {path}: {e}')


# ── JSON extraction (for Claude responses) ─────────────────────────────────────

import re

def extract_json(text: str) -> dict | None:
    if not text or not text.strip():
        return None
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    code_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
    if code_match:
        try:
            return json.loads(code_match.group(1))
        except json.JSONDecodeError:
            pass
    brace_depth, json_start, last_complete = 0, -1, None
    for i, ch in enumerate(text):
        if ch == '{':
            if brace_depth == 0:
                json_start = i
            brace_depth += 1
        elif ch == '}':
            brace_depth -= 1
            if brace_depth == 0 and json_start != -1:
                try:
                    last_complete = json.loads(text[json_start:i+1])
                except json.JSONDecodeError:
                    pass
    return last_complete


# ── Ensure data directory exists ───────────────────────────────────────────────

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
