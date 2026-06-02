#!/usr/bin/env python3
"""
BLADE v5 — Pure 15m ORB Breakout Bot

No filters. No score. No bias gate.

SESSIONS (UTC):
  ASIA    opens 00:00 — closes 06:00  (cron 23:50)  | SPX500_USD
  LONDON  opens 08:00 — closes 12:00  (cron 07:55)  | SPX500_USD + DE30_EUR
  NY_PM   opens 18:00 — closes 21:00  (cron 17:55)  | SPX500_USD

LOGIC:
  1. Wait for session open.
  2. Wait for first 15m candle to close; record ORB_HIGH / ORB_LOW.
  3. Poll M1 candles every 30s. First M1 close above ORB_HIGH → long;
     below ORB_LOW → short. First breakout wins (one trade / instrument / session).
  4. Enter 3 paper positions. SL fixed 3 pts beyond opposite ORB level.
     TPs: pos1 +3, pos2 +5, pos3 +10 (points from entry).
     When pos1 TP hits → move pos2/pos3 SL to BE.
  5. At session end, close any remaining positions. Send Telegram summary.

Only blockers: open position on same instrument, session ended, balance < $100.
"""

import json
import time
import uuid
import logging
import signal
import subprocess
import sys
sys.path.insert(0, "/root/.openclaw/scripts")
from telegram_personalities import wrap_message
import sys
from datetime import datetime, timezone, timedelta

from oandapyV20 import API
from oandapyV20.endpoints.instruments import InstrumentsCandles

sys.path.insert(0, "/root/.openclaw/scripts")
from hub_post import add_hub_message as hub_post
from agent_config import load_strategy
import session_notify

try:
    from h4_read import generate_h4_read, summarize_h4_for_log
except Exception:
    generate_h4_read = None
    summarize_h4_for_log = lambda r: {}

# ─────────────────────────────────────────────────────────────────────────────
# SETUP
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    filename='/root/.openclaw/agents/blade/bot/blade.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)

with open('/root/.openclaw/agents/main/agent/auth-profiles.json') as f:
    creds = json.load(f)['profiles']['oanda:default']
client     = API(access_token=creds['key'], environment='practice')
ACCOUNT_ID = creds['account_id']

AGENT_NAME       = "blade"
TRADES_JSON_PATH = '/root/.openclaw/dashboard/agent_trades.json'
TELEGRAM_UID     = "797062420"

# Team-context data sources (read-only; never gate trades — used for logging only)
STRATEGIST_REC      = '/root/.openclaw/dashboard/strategy_recommendation.json'
LENS_BIAS_PATH      = '/root/.openclaw/dashboard/market_bias.json'
NORMAN_REPORT_PATH  = '/root/.openclaw/dashboard/norman_report.json'
BLADE_LEARNING_LOG  = '/root/.openclaw/dashboard/blade_learning_log.json'

LENS_KEY_MAP = {
    'SPX500_USD': ['SPX500_USD', 'US100'],
    'DE30_EUR':   ['DE30_EUR', 'DE40_EUR', 'DE40'],
    'CHF_JPY':    ['CHF/JPY', 'CHF_JPY'],
}

# Populated once at session start. Keyed by instrument. Logged with every trade.
# Phase 1: observation only — no behavior change. Phase 2 (post-Norman validation)
# may enable self-gating based on the patterns this log surfaces.
session_context = {}

_BLADE_CFG = load_strategy('blade', {
    # D3 redesign knobs
    'RISK_PCT_PER_CLUSTER':     0.02,
    'POSITION_WEIGHTS':         {'pos1': 0.20, 'pos2': 0.30, 'pos3': 0.50},
    'TP_R_MULTIPLES':           {'pos1': 1.0,  'pos2': 2.0,  'pos3': None},
    'POS3_TRAIL':               True,
    'POS3_TRAIL_DISTANCE_R':    1.0,
    'DAILY_DD_HALT_PCT':        0.04,
    'STARTING_BALANCE_DEFAULT': 5000.0,
    'SL_BUFFER_POINTS':         3,
    'MIN_BALANCE':              100.0,
    # Legacy fallbacks (unused under D3 — retained so a rollback works)
    'RISK_PCT':                 0.01,
    'TP_PIPS':                  {'pos1': 3, 'pos2': 5, 'pos3': 10},
})

# Active (D3) knobs
RISK_PCT_PER_CLUSTER     = _BLADE_CFG['RISK_PCT_PER_CLUSTER']
POSITION_WEIGHTS         = _BLADE_CFG['POSITION_WEIGHTS']
TP_R_MULTIPLES           = _BLADE_CFG['TP_R_MULTIPLES']
POS3_TRAIL               = _BLADE_CFG['POS3_TRAIL']
POS3_TRAIL_DISTANCE_R    = _BLADE_CFG['POS3_TRAIL_DISTANCE_R']
DAILY_DD_HALT_PCT        = _BLADE_CFG['DAILY_DD_HALT_PCT']
STARTING_BALANCE_DEFAULT = _BLADE_CFG['STARTING_BALANCE_DEFAULT']
SL_BUFFER_POINTS         = _BLADE_CFG['SL_BUFFER_POINTS']
MIN_BALANCE              = _BLADE_CFG['MIN_BALANCE']

# Legacy (no longer wired in trading paths — kept for downstream code that may
# still reference them, e.g. dry_run_today.py).
RISK_PCT = _BLADE_CFG['RISK_PCT']
TP_PIPS  = _BLADE_CFG['TP_PIPS']

# ── Compounding balance + daily DD persistence ────────────────────────────────
BLADE_BALANCE_PATH = '/root/.openclaw/dashboard/blade_balance.json'

def _load_paper_balance() -> float:
    """Read compounding balance. Default to STARTING_BALANCE_DEFAULT if missing."""
    try:
        with open(BLADE_BALANCE_PATH) as f:
            d = json.load(f)
        return float(d.get('balance', STARTING_BALANCE_DEFAULT))
    except Exception:
        return STARTING_BALANCE_DEFAULT

def _save_paper_balance(balance: float, last_session: str = None):
    """Persist compounding balance at session end."""
    try:
        with open(BLADE_BALANCE_PATH, 'w') as f:
            json.dump({
                'balance':       round(balance, 2),
                'last_session':  last_session,
                'updated':       datetime.now(timezone.utc).isoformat(),
            }, f, indent=2)
    except Exception as e:
        logging.warning(f"balance save failed: {e}")

paper_balance = _load_paper_balance()
open_positions = {}
session_trades = []

SESSION_INSTRUMENTS = {
    'ASIA':   ['SPX500_USD'],
    'LONDON': ['SPX500_USD', 'DE30_EUR', 'CHF_JPY'],
    'NY_PM':  ['SPX500_USD'],
}
# PIP_VALUE is the price-increment per "point" used for stop-placement math
# (SL = ORB ± SL_BUFFER_POINTS × PIP_VALUE) and for the sizing divisor. It is
# NOT the USD value of a pip — see usd_per_pt_per_unit() below for that.
PIP_VALUE = {'SPX500_USD': 1.0, 'DE30_EUR': 1.0, 'CHF_JPY': 0.01}

# Quote currency per instrument. Paper P&L is realized in this currency and
# converted to USD via live OANDA mid prices (locked in at entry time so FX
# noise doesn't smear strategy attribution after the position is open).
QUOTE_CURRENCY = {'SPX500_USD': 'USD', 'DE30_EUR': 'EUR', 'CHF_JPY': 'JPY'}
_fx_cache = {}

def _fx_to_usd(currency: str) -> float:
    """USD value of one unit of `currency`. EUR via EUR_USD mid; JPY via 1/USD_JPY mid.
    Cached per-process; refreshed only when blade_bot restarts (new session)."""
    if currency == 'USD':
        return 1.0
    if currency in _fx_cache:
        return _fx_cache[currency]
    try:
        if currency == 'EUR':
            rate = float(get_price('EUR_USD'))            # 1 EUR in USD
        elif currency == 'JPY':
            rate = 1.0 / float(get_price('USD_JPY'))      # 1 JPY in USD
        else:
            rate = 1.0
    except Exception as e:
        logging.warning(f"_fx_to_usd: rate fetch failed for {currency}: {e}; assuming 1.0")
        rate = 1.0
    _fx_cache[currency] = rate
    return rate

def usd_per_pt_per_unit(instrument: str) -> float:
    """USD value of 1 unit × 1 price-point of move. Used for P&L accounting only.
    SPX500_USD → 1.0 (USD-quoted). DE30_EUR → EUR/USD mid. CHF_JPY → 1/USD_JPY mid."""
    return _fx_to_usd(QUOTE_CURRENCY.get(instrument, 'USD'))

SESSION_TIMES = {
    'ASIA':   {'open': (0,  0), 'close': (6,  0)},
    'LONDON': {'open': (8,  0), 'close': (12, 0)},
    'NY_PM':  {'open': (18, 0), 'close': (21, 0)},
}

# ─────────────────────────────────────────────────────────────────────────────
# TEAM CONTEXT (Strategist regime + Lens bias) — read-only, never gates trades
# ─────────────────────────────────────────────────────────────────────────────

def load_session_context(instruments):
    """Read Strategist regime + Lens bias + Norman verdict once per session. Pure observation."""
    global session_context
    session_context = {}

    strategist_data = {}
    try:
        with open(STRATEGIST_REC) as f:
            strategist_data = json.load(f).get('instruments', {}) or {}
    except Exception as e:
        logging.warning(f"team-context: strategist unavailable: {e}")

    lens_data = {}
    try:
        with open(LENS_BIAS_PATH) as f:
            ld = json.load(f)
            lens_data = ld.get('assets', ld)
    except Exception as e:
        logging.warning(f"team-context: lens unavailable: {e}")

    norman_verdict = 'UNKNOWN'
    norman_ruin_prob = None
    norman_dated = None
    try:
        with open(NORMAN_REPORT_PATH) as f:
            nr = json.load(f)
        blade_report = (nr.get('agent_reports', {}) or {}).get('blade', {}) or {}
        norman_verdict = blade_report.get('verdict', 'UNKNOWN')
        norman_ruin_prob = (blade_report.get('monte_carlo', {}) or {}).get('ruin_probability')
        norman_dated = nr.get('date')
    except Exception as e:
        logging.warning(f"team-context: norman unavailable: {e}")

    for inst in instruments:
        strat = strategist_data.get(inst, {}) or {}
        lens_dir, lens_conf = 'neutral', 50.0
        for key in LENS_KEY_MAP.get(inst, [inst]):
            entry = lens_data.get(key) if isinstance(lens_data, dict) else None
            if isinstance(entry, dict):
                lens_dir = (entry.get('direction', 'neutral') or 'neutral').lower()
                try:
                    lens_conf = float(entry.get('confidence', 50))
                except Exception:
                    lens_conf = 50.0
                break
        session_context[inst] = {
            'regime':            strat.get('regime', 'unknown'),
            'strategist_bias':   (strat.get('bias', 'neutral') or 'neutral').lower(),
            'lens_bias':         lens_dir,
            'lens_confidence':   lens_conf,
            'norman_verdict':    norman_verdict,
            'norman_ruin_prob':  norman_ruin_prob,
            'norman_dated':      norman_dated,
        }

    # H4 technical read per instrument (observation only — never gates)
    if generate_h4_read is not None:
        for inst in instruments:
            try:
                read = generate_h4_read(inst)
                session_context[inst]['h4_read'] = summarize_h4_for_log(read)
                session_context[inst]['h4_narrative'] = read.get('narrative', '')
            except Exception as e:
                logging.warning(f"team-context: h4_read({inst}) failed: {e}")
                session_context[inst]['h4_read'] = {}
                session_context[inst]['h4_narrative'] = ''

    print(f"\n  TEAM CONTEXT (observation only — Blade does NOT gate on this):")
    print(f"    Norman verdict on Blade: {norman_verdict}"
          + (f" | ruin={norman_ruin_prob}%" if norman_ruin_prob is not None else "")
          + (f" | dated {norman_dated}" if norman_dated else ""))
    for inst, ctx in session_context.items():
        print(f"    [{inst}] regime={ctx['regime']} | strategist_bias={ctx['strategist_bias']} | "
              f"lens={ctx['lens_bias']} {ctx['lens_confidence']:.0f}%")
        h4 = ctx.get('h4_read') or {}
        if h4.get('bias'):
            print(f"           H4 read: trend={h4.get('trend')} | bias={h4.get('bias')} {h4.get('confidence')}% "
                  f"| swings {h4.get('swing_low')}↔{h4.get('swing_high')}")
    logging.info(f"team-context loaded: {session_context}")


def is_strategist_aligned(instrument, direction):
    """True iff Strategist's bias OR Lens bias matches trade direction."""
    ctx = session_context.get(instrument, {})
    dir_bull = direction == 'long'
    strat = ctx.get('strategist_bias', 'neutral')
    lens  = ctx.get('lens_bias', 'neutral')
    if dir_bull:
        return strat == 'bullish' or lens == 'bullish'
    return strat == 'bearish' or lens == 'bearish'


def append_learning_log(record):
    """Append a context-tagged closed trade to the Phase-1 learning dataset."""
    try:
        try:
            with open(BLADE_LEARNING_LOG) as f:
                store = json.load(f)
        except Exception:
            store = {'records': [], 'phase': 1, 'note': 'observation-only; no trading logic reads this file'}
        store.setdefault('records', []).append(record)
        with open(BLADE_LEARNING_LOG, 'w') as f:
            json.dump(store, f, indent=2)
    except Exception as e:
        logging.warning(f"append_learning_log: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# OANDA HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def get_candles(instrument, granularity, count):
    try:
        r = InstrumentsCandles(instrument, params={
            'granularity': granularity, 'count': count, 'price': 'M'
        })
        client.request(r)
        return r.response.get('candles', [])
    except Exception as e:
        logging.error(f"get_candles({instrument},{granularity}): {type(e).__name__}: {e}")
        return []

def get_price(instrument):
    c = get_candles(instrument, 'M1', 2)
    if c:
        return float(c[-1]['mid']['c'])
    raise ValueError(f"Cannot fetch price for {instrument}")

# ─────────────────────────────────────────────────────────────────────────────
# TIMING — session open + first 15m candle close
# ─────────────────────────────────────────────────────────────────────────────

def wait_for_session_open(session_name):
    """Sleep until session open. Handles the 23:55 → 00:00 midnight cross for ASIA."""
    open_h, open_m = SESSION_TIMES[session_name]['open']
    while True:
        now    = datetime.now(timezone.utc)
        target = now.replace(hour=open_h, minute=open_m, second=0, microsecond=0)
        if (now - target).total_seconds() > 1800:
            target += timedelta(days=1)  # midnight cross — open is tomorrow
        wait_s = (target - now).total_seconds()
        if wait_s <= 0:
            break
        print(f"Waiting for {session_name} ({open_h:02d}:{open_m:02d} UTC)... {int(wait_s/60)+1}m")
        time.sleep(min(wait_s, 60))
    msg = f"{session_name} session open — {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
    print(f"\n{'='*60}\n{msg}")
    logging.info(msg)

def wait_for_orb_close(session_open_time):
    """Wait until session_open + 15m (+ 3s OANDA finalization buffer)."""
    snap_min     = (session_open_time.minute // 15) * 15
    candle_start = session_open_time.replace(minute=snap_min, second=0, microsecond=0)
    candle_close = candle_start + timedelta(minutes=15)
    target       = candle_close + timedelta(seconds=3)
    wait_s       = (target - datetime.now(timezone.utc)).total_seconds()
    print(f"ORB candle {candle_start.strftime('%H:%M')}→{candle_close.strftime('%H:%M')} UTC | {max(0, wait_s):.0f}s to close")
    if wait_s > 0:
        time.sleep(wait_s)

def get_orb_15m(instrument, session_open_time):
    """Fetch the 15m candle that started at session_open_time (snapped to 15m boundary)."""
    snap_min  = (session_open_time.minute // 15) * 15
    orb_start = session_open_time.replace(minute=snap_min, second=0, microsecond=0)
    for attempt in range(3):
        candles = get_candles(instrument, 'M15', 5)
        done    = [c for c in candles if c.get('complete', True)]
        if not done:
            time.sleep(10); continue
        match = None
        for c in done:
            try:
                ct = datetime.fromisoformat(c['time'].replace('Z', '+00:00'))
            except Exception:
                continue
            if abs((ct - orb_start).total_seconds()) < 1:
                match = c
                break
        if match is None:
            print(f"  [{instrument}] ORB {orb_start.strftime('%H:%M')} not yet in feed — retry in 15s")
            time.sleep(15); continue
        h = float(match['mid']['h']); l = float(match['mid']['l'])
        logging.info(f"ORB [{instrument}] {match['time']} H={h} L={l} R={h-l:.2f}")
        return h, l
    logging.error(f"ORB fetch failed for {instrument}")
    return None, None

def check_m1_breakout(instrument, orb_high, orb_low):
    """Last closed M1 candle closes above ORB_HIGH → long; below ORB_LOW → short."""
    candles = get_candles(instrument, 'M1', 3)
    done    = [c for c in candles if c.get('complete', True)]
    if not done:
        return None
    c = float(done[-1]['mid']['c'])
    if c > orb_high:
        return 'long'
    if c < orb_low:
        return 'short'
    return None

# ─────────────────────────────────────────────────────────────────────────────
# TRADE ENTRY
# ─────────────────────────────────────────────────────────────────────────────

def has_open_pos(instrument):
    return any(f"{instrument}:{n}" in open_positions for n in ('1', '2', '3'))

def place_orb_trade(instrument, direction, orb_high, orb_low, session_name):
    """D3: real stop distance + weighted sizing + R-multiple TPs + trailing pos3.

    Risk budget = RISK_PCT_PER_CLUSTER (2%) of current balance, split across
    pos1/pos2/pos3 by POSITION_WEIGHTS (default 20/30/50). Each position's
    units are sized off the ACTUAL stop distance (ORB level ± buffer),
    not the SL buffer alone. TPs are R-multiples of that stop distance.
    pos3 has no fixed TP — trails by POS3_TRAIL_DISTANCE_R after pos1 hits.
    """
    global paper_balance
    if _daily_dd_halt_triggered():
        logging.warning(f"daily DD halt active — skipping ORB on {instrument}")
        return False
    try:
        entry = get_price(instrument)
    except Exception as e:
        logging.error(f"place_orb_trade price {instrument}: {e}")
        return False

    pip_val   = PIP_VALUE[instrument]
    usd_per_pt = usd_per_pt_per_unit(instrument)   # locked-in FX for this position's lifetime

    # ── Stop placement: structural (ORB level ± buffer) ──────────────────────
    if direction == 'long':
        stop_loss   = orb_low  - SL_BUFFER_POINTS * pip_val
        stop_pts    = entry - stop_loss   # always positive
    else:
        stop_loss   = orb_high + SL_BUFFER_POINTS * pip_val
        stop_pts    = stop_loss - entry

    if stop_pts <= 0:
        logging.error(f"non-positive stop distance ({stop_pts}) for {instrument} — aborting trade")
        return False

    # ── Sizing: budget × weight, divided by REAL stop distance ──────────────
    cluster_risk_budget = paper_balance * RISK_PCT_PER_CLUSTER     # rail = 2%
    per_pos_risk_usd = {
        n: cluster_risk_budget * POSITION_WEIGHTS[f'pos{n}']
        for n in ('1', '2', '3')
    }
    per_pos_units = {}
    for n in ('1', '2', '3'):
        u = int(per_pos_risk_usd[n] / (stop_pts * pip_val))
        per_pos_units[n] = max(1, u)
    total_units = sum(per_pos_units.values())

    # ── TPs as R-multiples ──────────────────────────────────────────────────
    def tp_from_R(R):
        if R is None:
            return None
        return entry + R * stop_pts if direction == 'long' else entry - R * stop_pts

    tp1 = tp_from_R(TP_R_MULTIPLES.get('pos1'))
    tp2 = tp_from_R(TP_R_MULTIPLES.get('pos2'))
    tp3 = tp_from_R(TP_R_MULTIPLES.get('pos3'))   # None when trailing

    now_iso  = datetime.now(timezone.utc).isoformat()
    now_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    # ── Team context tag (Phase 1: observation only) ─────────────────────────
    ctx = session_context.get(instrument, {})
    orb_range_pts = round(orb_high - orb_low, 4)
    if direction == 'long':
        breakout_distance_pts = round(entry - orb_high, 4)
    else:
        breakout_distance_pts = round(orb_low - entry, 4)
    aligned = is_strategist_aligned(instrument, direction)

    base = {
        'direction': direction, 'entry': entry, 'stop_loss': stop_loss,
        'pip_value': pip_val, 'usd_per_pt': usd_per_pt, 'stop_pts': round(stop_pts, 4),
        'breakeven_moved': False, 'open_time': now_iso,
        'orb_high': orb_high, 'orb_low': orb_low,
        'regime_at_entry':           ctx.get('regime', 'unknown'),
        'strategist_bias_at_entry':  ctx.get('strategist_bias', 'neutral'),
        'lens_bias_at_entry':        ctx.get('lens_bias', 'neutral'),
        'lens_confidence_at_entry':  ctx.get('lens_confidence', 50.0),
        'strategist_aligned':        aligned,
        'norman_verdict_at_entry':   ctx.get('norman_verdict', 'UNKNOWN'),
        'norman_ruin_prob_at_entry': ctx.get('norman_ruin_prob'),
        'norman_dated':              ctx.get('norman_dated'),
        'h4_read_at_entry':          ctx.get('h4_read', {}),
        'orb_range_pts':             orb_range_pts,
        'breakout_distance_pts':     breakout_distance_pts,
        'cluster_risk_usd':          round(cluster_risk_budget, 2),
    }
    tp_levels = {'1': tp1, '2': tp2, '3': tp3}
    for n in ('1', '2', '3'):
        pk = f"{instrument}:{n}"
        open_positions[pk] = {
            **base,
            'trade_id':         str(uuid.uuid4()),
            'tp':               tp_levels[n],
            'pos_num':          n,
            'units':            per_pos_units[n],
            'per_pos_risk_usd': round(per_pos_risk_usd[n], 2),
            'tp_R':             TP_R_MULTIPLES.get(f'pos{n}'),
            'trailing_active':  False,
            'trail_high_water': entry,
        }
        tp_label = f"+{TP_R_MULTIPLES[f'pos{n}']}R" if TP_R_MULTIPLES.get(f'pos{n}') is not None else "TRAIL"
        session_trades.append({
            'id': open_positions[pk]['trade_id'], 'agent': AGENT_NAME,
            'date': now_date, 'timestamp': now_iso, 'session': session_name,
            'pair': instrument, 'symbol': instrument, 'direction': direction,
            'setup': f'15m ORB pos{n}', 'entry': entry, 'stop': stop_loss,
            'tp1': tp_levels[n] if tp_levels[n] is not None else 0, 'tp2': 0, 'tp3': 0,
            'result': 'Pending',
            'pnl_usd': 0, 'r_multiple': 0,
            'notes': (f'ORB pos{n} | units:{per_pos_units[n]} | SL:{stop_loss:.2f} ({stop_pts:.1f}pt) '
                      f'| TP:{tp_label} | risk:${per_pos_risk_usd[n]:.2f}'),
            'regime_at_entry':           base['regime_at_entry'],
            'strategist_bias_at_entry':  base['strategist_bias_at_entry'],
            'lens_bias_at_entry':        base['lens_bias_at_entry'],
            'lens_confidence_at_entry':  base['lens_confidence_at_entry'],
            'strategist_aligned':        base['strategist_aligned'],
            'norman_verdict_at_entry':   base['norman_verdict_at_entry'],
            'norman_ruin_prob_at_entry': base['norman_ruin_prob_at_entry'],
            'orb_range_pts':             orb_range_pts,
            'breakout_distance_pts':     breakout_distance_pts,
        })

    short = instrument.split('_')[0]
    dir_word = 'LONG' if direction == 'long' else 'SHORT'
    icon = '🟢' if direction == 'long' else '🔴'
    tp_str = (f"TP1:{tp1:.2f}({TP_R_MULTIPLES['pos1']}R) "
              f"TP2:{tp2:.2f}({TP_R_MULTIPLES['pos2']}R) "
              f"TP3:{'TRAIL' if tp3 is None else f'{tp3:.2f}'}")
    units_str = '/'.join(str(per_pos_units[n]) for n in ('1','2','3'))
    msg = (f"{icon} BLADE {dir_word} {short} @ {entry:.2f} | "
           f"SL:{stop_loss:.2f}({stop_pts:.1f}pt) | {tp_str} | units:{units_str} | "
           f"risk:${cluster_risk_budget:.2f}({RISK_PCT_PER_CLUSTER*100:.1f}% of ${paper_balance:.2f})")
    print(f"  >> {msg}")
    logging.info(msg)
    hub_post(AGENT_NAME, "trade", msg, tags=["trading", "entry", session_name.lower()])
    return True


# ── Daily DD circuit breaker (4% rail) ───────────────────────────────────────
def _daily_dd_paths():
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    return f'/tmp/blade_dd_{today}.json'

def _load_daily_dd():
    try:
        with open(_daily_dd_paths()) as f:
            return json.load(f)
    except Exception:
        return {'date': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
                'day_start_balance': paper_balance,
                'cumulative_pnl': 0.0,
                'halted': False}

def _save_daily_dd(state):
    try:
        with open(_daily_dd_paths(), 'w') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logging.warning(f"daily DD save failed: {e}")

def _record_daily_pnl(pnl):
    """Add a closed-position PnL to today's tally. Flip halt flag if breached."""
    state = _load_daily_dd()
    state['cumulative_pnl'] = round(state.get('cumulative_pnl', 0.0) + pnl, 2)
    threshold = -state['day_start_balance'] * DAILY_DD_HALT_PCT
    if state['cumulative_pnl'] <= threshold and not state.get('halted'):
        state['halted'] = True
        state['halted_at'] = datetime.now(timezone.utc).isoformat()
        msg = (f"🛑 DAILY DD CIRCUIT BREAKER: cumulative PnL ${state['cumulative_pnl']:.2f} "
               f"≤ -{DAILY_DD_HALT_PCT*100:.0f}% of day-start balance "
               f"(${state['day_start_balance']:.2f}). Halting remaining sessions today.")
        logging.warning(msg)
        print(f"\n  {msg}")
        try:
            send_telegram(wrap_message('blade', msg))
        except Exception:
            pass
    _save_daily_dd(state)

def _daily_dd_halt_triggered() -> bool:
    return bool(_load_daily_dd().get('halted'))

# ─────────────────────────────────────────────────────────────────────────────
# POSITION MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────

def manage_positions():
    """Check TPs/SLs; advance trailing pos3; pos1 TP → BE for pos2 + activate trail for pos3."""
    global paper_balance
    to_close = []

    for pos_key, pos in list(open_positions.items()):
        instrument, pos_num = pos_key.rsplit(':', 1)
        try:
            price      = get_price(instrument)
            direction  = pos['direction']
            entry      = pos['entry']
            units      = pos['units']
            pip_val    = pos['pip_value']                              # for stop-distance math
            usd_per_pt = pos.get('usd_per_pt', pos['pip_value'])       # for P&L; fallback = legacy behavior
            tp         = pos.get('tp')

            # ── Trailing pos3: advance stop while in profit ─────────────────
            if pos_num == '3' and pos.get('trailing_active') and POS3_TRAIL:
                trail_distance = pos['stop_pts'] * POS3_TRAIL_DISTANCE_R
                if direction == 'long':
                    if price > pos.get('trail_high_water', entry):
                        pos['trail_high_water'] = price
                        new_sl = price - trail_distance
                        if new_sl > pos['stop_loss']:
                            pos['stop_loss'] = new_sl
                else:
                    if price < pos.get('trail_high_water', entry):
                        pos['trail_high_water'] = price
                        new_sl = price + trail_distance
                        if new_sl < pos['stop_loss']:
                            pos['stop_loss'] = new_sl

            stop = pos['stop_loss']

            # ── Fixed TP check (skip if tp is None, i.e. trailing pos3) ─────
            if tp is not None:
                tp_hit = (price >= tp) if direction == 'long' else (price <= tp)
                if tp_hit:
                    pnl = (tp - entry) * units * usd_per_pt if direction == 'long' \
                          else (entry - tp) * units * usd_per_pt
                    to_close.append((pos_key, f"TP{pos_num}", pnl, tp))
                    if pos_num == '1':
                        # pos1 fires → pos2 SL to BE; pos3 SL to BE + activate trail
                        for n in ('2', '3'):
                            pk = f"{instrument}:{n}"
                            if pk in open_positions:
                                open_positions[pk]['stop_loss']       = entry
                                open_positions[pk]['breakeven_moved'] = True
                                logging.info(f"BE MOVE: {instrument} pos{n} SL → {entry:.2f}")
                                print(f"  BE: {instrument} pos{n} SL → {entry:.2f}")
                                if n == '3' and POS3_TRAIL:
                                    open_positions[pk]['trailing_active']  = True
                                    open_positions[pk]['trail_high_water'] = price
                                    print(f"  TRAIL: pos3 activated (distance={POS3_TRAIL_DISTANCE_R}R)")
                                    logging.info(f"TRAIL ACTIVATED: {instrument} pos3 high_water={price:.2f}")
                    continue

            # ── Stop check (works for both BE and trailing variants) ────────
            hit_stop = (price <= stop) if direction == 'long' else (price >= stop)
            if hit_stop:
                if pos.get('trailing_active') and pos_num == '3':
                    # Trail-out: close at trailed stop; R-mult = realized profit
                    pnl = (stop - entry) * units * usd_per_pt if direction == 'long' \
                          else (entry - stop) * units * usd_per_pt
                    result = 'TRAIL' if pnl > 0 else ('BE' if abs(pnl) < 0.01 else 'SL')
                elif pos.get('breakeven_moved'):
                    pnl, result = 0.0, 'BE'
                else:
                    pnl = (price - entry) * units * usd_per_pt if direction == 'long' \
                          else (entry - price) * units * usd_per_pt
                    result = 'SL'
                close_price = stop if pos.get('trailing_active') else (entry if result == 'BE' else price)
                to_close.append((pos_key, result, pnl, close_price))
        except Exception as e:
            logging.error(f"manage_positions {pos_key}: {e}")

    for pos_key, result, pnl, close_price in to_close:
        if pos_key not in open_positions:
            continue
        paper_balance += pnl
        _record_daily_pnl(pnl)
        pos = open_positions[pos_key]
        update_trade_log(pos['trade_id'], result, pnl, f"Closed: {result}")
        instrument, pos_num = pos_key.rsplit(':', 1)
        short = instrument.split('_')[0]
        icon  = '✅' if pnl > 0 else ('⚪' if result == 'BE' else '🔴')
        logging.info(f"{result}: {instrument} pos{pos_num} @ {close_price:.2f} PnL:${pnl:.2f}")
        print(f"  {icon} {result}: {instrument} pos{pos_num} @ {close_price:.2f} | ${pnl:.2f}")
        _record_learning(pos, instrument, pos_num, result, pnl, close_price)
        del open_positions[pos_key]

def close_all_positions(reason="Session end"):
    """Force-close every open position at current market price."""
    global paper_balance
    for pos_key in list(open_positions.keys()):
        instrument, pos_num = pos_key.rsplit(':', 1)
        pos = open_positions[pos_key]
        try:
            price = get_price(instrument)
        except Exception:
            price = pos['entry']
        usd_per_pt = pos.get('usd_per_pt', pos['pip_value'])
        pnl = (price - pos['entry']) * pos['units'] * usd_per_pt if pos['direction'] == 'long' \
              else (pos['entry'] - price) * pos['units'] * usd_per_pt
        paper_balance += pnl
        _record_daily_pnl(pnl)
        update_trade_log(pos['trade_id'], "Time Stop", pnl, reason)
        logging.info(f"TIME STOP: {instrument} pos{pos_num} @ {price:.2f} PnL:${pnl:.2f}")
        print(f"  TIME STOP: {instrument} pos{pos_num} @ {price:.2f} | ${pnl:.2f}")
        _record_learning(pos, instrument, pos_num, "Time Stop", pnl, price)
        del open_positions[pos_key]


def _record_learning(pos, instrument, pos_num, outcome, pnl, close_price):
    """Append one closed position to /root/.openclaw/dashboard/blade_learning_log.json.
    For pos3 trail outcomes, log the realized R-multiple in a dedicated field so
    Norman can validate the D3 design's thinnest assumption (n=3, all XAU,
    zero SPX500 in the priors) at the 100-cluster review.

    R-multiple denominator = actual unit-risk in USD (units × stop_pts × usd_per_pt),
    not the budgeted dollar risk — so unit-rounding doesn't distort R, and the
    ratio stays dimensionless (USD/USD) on the non-USD-quoted pairs too."""
    usd_per_pt = pos.get('usd_per_pt', pos.get('pip_value', 0)) or 0
    actual_unit_risk = (pos.get('units', 0) or 0) * (pos.get('stop_pts', 0) or 0) * usd_per_pt
    r_mult = round(pnl / actual_unit_risk, 2) if actual_unit_risk else 0.0

    # Dedicated pos3-trail R-multiple field. Populated only when pos3 actually
    # closed under the trailing-stop path (trailing_active was set when pos1 hit).
    pos3_trail_r_achieved = None
    if pos_num == '3' and pos.get('trailing_active'):
        pos3_trail_r_achieved = r_mult

    append_learning_log({
        'trade_id':                 pos['trade_id'],
        'pos_num':                  pos_num,
        'session':                  _current_session_name(),
        'instrument':               instrument,
        'direction':                pos['direction'],
        'timestamp_entry':          pos.get('open_time'),
        'timestamp_close':          datetime.now(timezone.utc).isoformat(),
        'entry_price':              round(pos['entry'], 4),
        'close_price':              round(close_price, 4),
        'stop_loss':                round(pos['stop_loss'], 4),
        'orb_high':                 round(pos['orb_high'], 4),
        'orb_low':                  round(pos['orb_low'], 4),
        'orb_range_pts':            pos.get('orb_range_pts'),
        'breakout_distance_pts':    pos.get('breakout_distance_pts'),
        'regime_at_entry':          pos.get('regime_at_entry', 'unknown'),
        'strategist_bias_at_entry': pos.get('strategist_bias_at_entry', 'neutral'),
        'lens_bias_at_entry':       pos.get('lens_bias_at_entry', 'neutral'),
        'lens_confidence_at_entry': pos.get('lens_confidence_at_entry', 50.0),
        'strategist_aligned':       pos.get('strategist_aligned', False),
        'norman_verdict_at_entry':  pos.get('norman_verdict_at_entry', 'UNKNOWN'),
        'norman_ruin_prob_at_entry': pos.get('norman_ruin_prob_at_entry'),
        'norman_dated':             pos.get('norman_dated'),
        'h4_read_at_entry':         pos.get('h4_read_at_entry', {}),
        'outcome':                  outcome,        # TP1/TP2/SL/BE/TRAIL/Time Stop
        'pnl_usd':                  round(pnl, 2),
        'r_multiple':               r_mult,
        'stop_pts':                 pos.get('stop_pts'),
        'units':                    pos.get('units'),
        'per_pos_risk_usd':         pos.get('per_pos_risk_usd'),
        'tp_R':                     pos.get('tp_R'),
        'trailing_active':          bool(pos.get('trailing_active')),
        'pos3_trail_r_achieved':    pos3_trail_r_achieved,
        'cluster_risk_usd':         pos.get('cluster_risk_usd'),
    })


_current_session = {'name': None}

def _current_session_name():
    return _current_session.get('name') or 'UNKNOWN'

def update_trade_log(trade_id, result, pnl, notes):
    for t in session_trades:
        if t['id'] == trade_id:
            t['result']     = result
            t['pnl_usd']    = round(pnl, 2)
            risk            = abs(t['entry'] - t['stop']) or 1
            t['r_multiple'] = round(pnl / risk, 1)
            t['notes']      = notes
            return

def record_no_trade(session_name, instrument, reason):
    session_trades.append({
        'id': str(uuid.uuid4()), 'agent': AGENT_NAME,
        'date': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'session': session_name, 'pair': instrument, 'symbol': instrument,
        'direction': 'none', 'setup': '15m ORB',
        'entry': 0, 'stop': 0, 'tp1': 0, 'tp2': 0, 'tp3': 0,
        'result': 'no_trade', 'pnl_usd': 0, 'r_multiple': 0, 'notes': reason,
    })
    print(f"  NO TRADE [{instrument}]: {reason}")
    logging.info(f"NO TRADE: {instrument} | {reason}")

# ─────────────────────────────────────────────────────────────────────────────
# REPORTING
# ─────────────────────────────────────────────────────────────────────────────

def write_session_trades_to_json():
    def norm(t):
        return {
            "agent": t.get('agent', AGENT_NAME),
            "symbol": t.get('symbol') or t.get('pair') or '',
            "direction": t.get('direction', 'none'),
            "pnl": t.get('pnl_usd', 0),
            "date": t.get('date', ''), "timestamp": t.get('timestamp', ''),
            "session": t.get('session', ''), "result": t.get('result', ''),
        }
    try:
        with open(TRADES_JSON_PATH) as f:
            data = json.load(f)
    except Exception:
        data = {"trades": []}
    if not session_trades:
        session_trades.append({
            "agent": AGENT_NAME, "direction": "none", "pnl_usd": 0,
            "date": datetime.now(timezone.utc).strftime('%Y-%m-%d'),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    data['trades'] = data.get('trades', []) + [norm(t) for t in session_trades]
    with open(TRADES_JSON_PATH, 'w') as f:
        json.dump(data, f, indent=2)

def send_telegram(message):
    try:
        subprocess.run([
            "openclaw", "message", "send",
            "--channel", "telegram", "--target", TELEGRAM_UID, "--message", message
        ], timeout=15)
    except Exception as e:
        logging.warning(f"telegram send failed: {e}")

def _bump_sessions_today():
    """Increment per-day session-complete counter, return (done, total)."""
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    state_path = f"/tmp/blade_sessions_{today}.json"
    try:
        with open(state_path) as f:
            state = json.load(f)
    except Exception:
        state = {'done': 0}
    state['done'] = int(state.get('done', 0)) + 1
    try:
        with open(state_path, 'w') as f:
            json.dump(state, f)
    except Exception:
        pass
    return state['done'], len(SESSION_TIMES)


def send_session_summary(session_name):
    fired = {}
    for t in session_trades:
        if t.get('result') in ('no_trade', 'Pending'):
            continue
        setup = t.get('setup', '')
        if 'pos' not in setup:
            continue
        pos_num = setup.split('pos')[-1].strip()
        key = (t.get('pair', '?'), t.get('direction', '?'))
        bucket = fired.setdefault(key, {'pnl': 0.0})
        bucket[f'pos{pos_num}'] = t.get('result', '')
        bucket['pnl'] += t.get('pnl_usd', 0) or 0

    done, total = _bump_sessions_today()

    if not fired:
        send_telegram(f"📊 BLADE — {session_name} | No trades taken.")
        return

    open_h, open_m   = SESSION_TIMES[session_name]['open']
    close_h, close_m = SESSION_TIMES[session_name]['close']
    date_s = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    lines = [
        f"📊 BLADE — {session_name} SESSION COMPLETE",
        f"Date: {date_s} | {open_h:02d}:{open_m:02d} – {close_h:02d}:{close_m:02d} UTC",
        "",
        "Trades taken:",
    ]

    session_pnl = 0.0
    for (pair, direction), info in fired.items():
        short    = pair.split('_')[0]
        dir_word = 'LONG' if direction == 'long' else 'SHORT'
        pnl      = info['pnl']
        session_pnl += pnl

        results = [info.get(f'pos{n}') for n in ('1', '2', '3')]
        if all(r == 'SL' for r in results if r):
            result_str = "SL ❌"
        elif all(r == 'BE' for r in results if r):
            result_str = "BE 🔁"
        else:
            parts = []
            for n, r in zip(('1', '2', '3'), results):
                if r is None:
                    continue
                if r.startswith('TP') or r == 'Time Stop':
                    parts.append(f"TP{n} ✅")
                elif r == 'SL':
                    parts.append(f"SL{n} ❌")
                elif r == 'BE':
                    parts.append(f"BE{n} 🔁")
                else:
                    parts.append(f"{r}{n}")
            result_str = ' '.join(parts) if parts else '—'

        if pnl > 0:
            pnl_str = f"+${pnl:.2f}"
        elif pnl < 0:
            pnl_str = f"-${abs(pnl):.2f}"
        else:
            pnl_str = "$0"
        lines.append(f"- {short} {dir_word} → {result_str} | {pnl_str}")

    if session_pnl > 0:
        spnl = f"+${session_pnl:.2f}"
    elif session_pnl < 0:
        spnl = f"-${abs(session_pnl):.2f}"
    else:
        spnl = "$0"

    lines += [
        "",
        f"Session P&L: {spnl}",
        f"Running balance: ${paper_balance:.2f}",
        f"Sessions today: {done}/{total} complete",
    ]
    send_telegram(wrap_message("blade", "\n".join(lines)))

# ─────────────────────────────────────────────────────────────────────────────
# MAIN SESSION RUNNER
# ─────────────────────────────────────────────────────────────────────────────

def run_session(session_name):
    """Pure ORB runner: wait → ORB → monitor M1 breakouts → manage → close.

    Wrapped in try/finally + SIGTERM handler so the compounding balance is
    persisted to disk even when `timeout` (cron wrapper) sends SIGTERM before
    the natural session-end time — otherwise the in-process gains evaporate.
    """
    global session_trades, paper_balance
    session_trades = []
    _current_session['name'] = session_name

    # Refresh compounding balance from disk in case it was updated mid-day.
    paper_balance = _load_paper_balance()

    # Persist balance on SIGTERM (cron `timeout` kill) so paper gains survive.
    def _persist_and_exit(signum, _frame):
        logging.warning(f"SIGNAL {signum} received — persisting balance ${paper_balance:.2f} and exiting.")
        try:
            _save_paper_balance(paper_balance, last_session=session_name)
        except Exception as e:
            logging.error(f"emergency balance save failed: {e}")
        sys.exit(0)
    signal.signal(signal.SIGTERM, _persist_and_exit)
    signal.signal(signal.SIGINT,  _persist_and_exit)

    # Ensure today's DD state exists and locks day_start_balance to session-open.
    import os as _os
    if not _os.path.exists(_daily_dd_paths()):
        _save_daily_dd({
            'date':              datetime.now(timezone.utc).strftime('%Y-%m-%d'),
            'day_start_balance': paper_balance,
            'cumulative_pnl':    0.0,
            'halted':            False,
        })

    # Daily DD circuit breaker: if today's cumulative PnL already breached
    # the -DAILY_DD_HALT_PCT rail in an earlier session, stand down now.
    if _daily_dd_halt_triggered():
        state = _load_daily_dd()
        msg = wrap_message('blade',
            f"HALT. Daily DD circuit breaker active "
            f"(cum PnL ${state['cumulative_pnl']:.2f} ≤ -{DAILY_DD_HALT_PCT*100:.0f}% of "
            f"${state['day_start_balance']:.2f}). Standing down for {session_name}.")
        print(msg); logging.warning(msg); send_telegram(msg)
        return

    # Load team context once. Phase 1: observation only. Blade does NOT gate on this.
    load_session_context(SESSION_INSTRUMENTS[session_name])

    if paper_balance < MIN_BALANCE:
        msg = wrap_message("blade", f"HALT. Balance ${paper_balance:.2f} below ${MIN_BALANCE} floor. Standing down.")
        print(msg); logging.warning(msg); send_telegram(msg)
        return

    instruments = SESSION_INSTRUMENTS[session_name]
    print(f"\n{'='*60}\nBLADE v5/D3 — {session_name} | Instruments: {instruments} | ${paper_balance:.2f}\n{'='*60}")
    logging.info(f"SESSION START: {session_name} | balance=${paper_balance:.2f}")
    hub_post(AGENT_NAME, "status", f"{session_name} starting. Balance: ${paper_balance:.2f}", tags=["session"])

    wait_for_session_open(session_name)
    session_open_time = datetime.now(timezone.utc)
    send_telegram(f"🔪 Blade {session_name} starting")

    wait_for_orb_close(session_open_time)

    orb_levels = {}
    for inst in instruments:
        h, l = get_orb_15m(inst, session_open_time)
        if h is None:
            record_no_trade(session_name, inst, "ORB data unavailable")
            continue
        orb_levels[inst] = (h, l)
        print(f"  [{inst}] ORB H={h:.2f} L={l:.2f} R={h-l:.2f}")

    close_h, close_m = SESSION_TIMES[session_name]['close']
    session_end = session_open_time.replace(hour=close_h, minute=close_m, second=0, microsecond=0)
    if session_end <= session_open_time:
        session_end += timedelta(days=1)

    fired = set()
    print(f"\n  Monitoring {list(orb_levels)} until {session_end.strftime('%H:%M UTC')}...")

    while datetime.now(timezone.utc) < session_end:
        for inst, (orb_high, orb_low) in orb_levels.items():
            if inst in fired or has_open_pos(inst):
                continue
            direction = check_m1_breakout(inst, orb_high, orb_low)
            if direction:
                print(f"  [{inst}] BREAKOUT {direction.upper()} — entering")
                logging.info(f"BREAKOUT: {inst} {direction.upper()}")
                if place_orb_trade(inst, direction, orb_high, orb_low, session_name):
                    fired.add(inst)

        if open_positions:
            manage_positions()

        open_instrs = sorted({k.rsplit(':', 1)[0] for k in open_positions})
        print(f"  [{datetime.now(timezone.utc).strftime('%H:%M:%S')}] open:{open_instrs} | "
              f"fired:{sorted(fired)} | ${paper_balance:.2f}")
        # Persist incrementally so a cron-timeout kill mid-session doesn't lose
        # the running gains. Tiny IO; SIGTERM handler is the primary safety net.
        _save_paper_balance(paper_balance, last_session=session_name)
        time.sleep(30)

    if open_positions:
        print("\n  Session end — closing remaining positions")
        close_all_positions("Session end time stop")

    for inst in orb_levels:
        if inst not in fired:
            already = any(t['pair'] == inst and t['result'] == 'no_trade' for t in session_trades)
            if not already:
                record_no_trade(session_name, inst, "No breakout in session")

    total = len([t for t in session_trades if t['result'] not in ('no_trade', 'Pending')])
    _save_paper_balance(paper_balance, last_session=session_name)
    print(f"\n{'='*60}\n{session_name} COMPLETE | Balance: ${paper_balance:.2f} | {total} closed\n{'='*60}")
    logging.info(f"SESSION END: {session_name} | Balance: ${paper_balance:.2f} (persisted)")
    hub_post(AGENT_NAME, "status", f"{session_name} complete. {total} trades. Balance: ${paper_balance:.2f}.",
             tags=["session", "complete"])
    write_session_trades_to_json()
    send_session_summary(session_name)
    import os
    os.system("python3 /root/.openclaw/scripts/sync_agent_pnl.py")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 blade_bot.py <SESSION>")
        print("Sessions:", list(SESSION_TIMES))
        sys.exit(1)
    s = sys.argv[1].upper()
    if s not in SESSION_TIMES:
        print(f"Unknown session '{s}'. Valid: {list(SESSION_TIMES)}")
        sys.exit(1)
    run_session(s)
