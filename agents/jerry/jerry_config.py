"""
jerry_config.py — Shared config, helpers, and Alpaca API instance for Jerry.
"""

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
import sys
sys.path.insert(0, "/root/.openclaw/scripts")
from telegram_personalities import wrap_message

import requests
from dotenv import load_dotenv
from alpaca_trade_api import REST

load_dotenv('/root/.openclaw/.env')

# ── Alpaca ─────────────────────────────────────────────────────────────────────

api = REST(
    os.getenv('ALPACA_API_KEY'),
    os.getenv('ALPACA_API_SECRET'),
    base_url='https://paper-api.alpaca.markets',
)

# ── Constants ─────────────────────────────────────────────────────────────────

STARTING_BALANCE   = 100_000.0
SAFETY_FLOOR_PCT   = 0.25
SAFETY_FLOOR       = STARTING_BALANCE * SAFETY_FLOOR_PCT   # $25,000

MAIN_LOOP_SECS     = 300   # 5 minutes

# Market hours in UTC
DISCOVERY_HOUR_UTC = 13   # 9:00 AM ET
MARKET_OPEN_UTC    = (13, 30)   # 9:30 AM ET
MARKET_CLOSE_UTC   = (20, 0)    # 4:00 PM ET
REVIEW_HOUR_UTC    = 20
REVIEW_MIN_UTC     = 30         # 4:30 PM ET

# ── Paths ─────────────────────────────────────────────────────────────────────

BASE_DIR         = Path(__file__).parent
DATA_DIR         = BASE_DIR / 'data'
LOG_PATH         = BASE_DIR / 'jerry.log'

STRATEGIES_PATH  = DATA_DIR / 'strategies.json'   # active watchlist
TRADE_HISTORY_PATH = DATA_DIR / 'trade_history.json'
WATCHLIST_PATH   = DATA_DIR / 'watchlist.json'
PERFORMANCE_PATH = DATA_DIR / 'performance.json'

SENTINEL_DATA    = Path('/root/.openclaw/dashboard/sentinel_data.json')
DASHBOARD_PATH   = Path('/root/.openclaw/dashboard/jerry_portfolio.json')
API_COSTS_PATH   = Path('/root/.openclaw/logs/jerry_api_costs.json')

# Claude model
DISCOVER_MODEL   = 'claude-sonnet-4-6'
REVIEW_MODEL     = 'claude-sonnet-4-6'

# ── Telegram ──────────────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID   = '797062420'
TG_MAX             = 4000


def send_telegram(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN:
        return
    chunks = _split_telegram(text)
    for chunk in chunks:
        try:
            resp = requests.post(
                f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
                json={'chat_id': TELEGRAM_CHAT_ID, 'text': chunk},
                timeout=15,
            )
            resp.raise_for_status()
        except Exception as e:
            print(f'[jerry] Telegram error: {e}')


def _split_telegram(text: str) -> list[str]:
    if len(text) <= TG_MAX:
        return [text]
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
    return chunks


# ── Logger ────────────────────────────────────────────────────────────────────

def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(f'jerry.{name}')
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter('%(asctime)s [%(name)s] %(levelname)s  %(message)s')

    fh = logging.FileHandler(LOG_PATH)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


# ── JSON helpers ──────────────────────────────────────────────────────────────

def load_json(path, default=None):
    try:
        p = Path(path)
        if p.exists():
            return json.loads(p.read_text())
    except Exception as e:
        print(f'[jerry] load_json {path}: {e}')
    return default if default is not None else {}


def save_json(path, data) -> None:
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2, default=str))
    except Exception as e:
        print(f'[jerry] save_json {path}: {e}')


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
                    last_complete = json.loads(text[json_start:i + 1])
                except json.JSONDecodeError:
                    pass
    return last_complete


# ── API cost tracking ─────────────────────────────────────────────────────────

# claude-sonnet-4-6: $3/MTok input, $15/MTok output
_INPUT_COST_PER_TOKEN  = 3  / 1_000_000
_OUTPUT_COST_PER_TOKEN = 15 / 1_000_000
_SEARCH_COST           = 0.01   # ~$0.01 per web search


def save_api_cost(call_type: str, input_tokens: int, output_tokens: int,
                  web_searches: int = 0) -> float:
    cost = round(
        input_tokens  * _INPUT_COST_PER_TOKEN +
        output_tokens * _OUTPUT_COST_PER_TOKEN +
        web_searches  * _SEARCH_COST,
        6,
    )
    entry = {
        'timestamp':     datetime.now(timezone.utc).isoformat(),
        'date':          datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'call_type':     call_type,
        'input_tokens':  input_tokens,
        'output_tokens': output_tokens,
        'web_searches':  web_searches,
        'cost_usd':      cost,
    }
    costs = load_json(API_COSTS_PATH, [])
    if not isinstance(costs, list):
        costs = []
    costs.append(entry)
    save_json(API_COSTS_PATH, costs)
    return cost


# ── Market hours helpers ───────────────────────────────────────────────────────

def is_weekday(dt: datetime = None) -> bool:
    if dt is None:
        dt = datetime.now(timezone.utc)
    return dt.weekday() < 5   # 0=Mon … 4=Fri


def is_market_hours(dt: datetime = None) -> bool:
    if dt is None:
        dt = datetime.now(timezone.utc)
    if not is_weekday(dt):
        return False
    open_  = dt.replace(hour=MARKET_OPEN_UTC[0],  minute=MARKET_OPEN_UTC[1],  second=0, microsecond=0)
    close_ = dt.replace(hour=MARKET_CLOSE_UTC[0], minute=MARKET_CLOSE_UTC[1], second=0, microsecond=0)
    return open_ <= dt < close_


def is_discovery_window(dt: datetime = None) -> bool:
    """True from 13:00 UTC onwards on weekdays (before market open)."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    if not is_weekday(dt):
        return False
    discovery_ = dt.replace(hour=DISCOVERY_HOUR_UTC, minute=0, second=0, microsecond=0)
    return dt >= discovery_


def is_review_window(dt: datetime = None) -> bool:
    """True from 20:30 UTC onwards on weekdays (after market close)."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    if not is_weekday(dt):
        return False
    review_ = dt.replace(hour=REVIEW_HOUR_UTC, minute=REVIEW_MIN_UTC, second=0, microsecond=0)
    return dt >= review_
