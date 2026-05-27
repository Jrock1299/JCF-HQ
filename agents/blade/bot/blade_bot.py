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
import session_notify

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

RISK_PCT         = 0.01   # 1% of paper balance per trade (total across 3 positions)
SL_BUFFER_POINTS = 3      # SL = opposite ORB ± 3 points
TP_PIPS          = {'pos1': 3, 'pos2': 5, 'pos3': 10}
MIN_BALANCE      = 100.0

paper_balance  = 2000.0
open_positions = {}
session_trades = []

SESSION_INSTRUMENTS = {
    'ASIA':   ['SPX500_USD'],
    'LONDON': ['SPX500_USD', 'DE30_EUR', 'CHF_JPY'],
    'NY_PM':  ['SPX500_USD'],
}
# TODO: PIP_VALUE currently stores price increment per pip, not USD per unit per pip.
# CHF_JPY and DE30_EUR P&L will be slightly mis-stated in paper accounting.
# Fix before going live: split into pip_size and usd_per_unit_per_pip with FX conversion.
PIP_VALUE = {'SPX500_USD': 1.0, 'DE30_EUR': 1.0, 'CHF_JPY': 0.01}

SESSION_TIMES = {
    'ASIA':   {'open': (0,  0), 'close': (6,  0)},
    'LONDON': {'open': (8,  0), 'close': (12, 0)},
    'NY_PM':  {'open': (18, 0), 'close': (21, 0)},
}

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
    """Enter 3 paper positions with fixed TPs and SL 3pts beyond opposite ORB."""
    global paper_balance
    try:
        entry = get_price(instrument)
    except Exception as e:
        logging.error(f"place_orb_trade price {instrument}: {e}")
        return False

    pip_val     = PIP_VALUE[instrument]
    risk_amount = paper_balance * RISK_PCT
    units_per_pos = max(1, int(risk_amount / (SL_BUFFER_POINTS * pip_val) / 3))

    sl_dist  = SL_BUFFER_POINTS * pip_val
    tp1_dist = TP_PIPS['pos1']  * pip_val
    tp2_dist = TP_PIPS['pos2']  * pip_val
    tp3_dist = TP_PIPS['pos3']  * pip_val

    if direction == 'long':
        stop_loss = orb_low - sl_dist
        tp1, tp2, tp3 = entry + tp1_dist, entry + tp2_dist, entry + tp3_dist
    else:
        stop_loss = orb_high + sl_dist
        tp1, tp2, tp3 = entry - tp1_dist, entry - tp2_dist, entry - tp3_dist

    now_iso  = datetime.now(timezone.utc).isoformat()
    now_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    base = {
        'direction': direction, 'entry': entry, 'stop_loss': stop_loss,
        'units': units_per_pos, 'pip_value': pip_val,
        'breakeven_moved': False, 'open_time': now_iso,
        'orb_high': orb_high, 'orb_low': orb_low,
    }
    tp_map = {'1': tp1, '2': tp2, '3': tp3}
    for n, tp in tp_map.items():
        pk = f"{instrument}:{n}"
        open_positions[pk] = {**base, 'trade_id': str(uuid.uuid4()), 'tp': tp}
        session_trades.append({
            'id': open_positions[pk]['trade_id'], 'agent': AGENT_NAME,
            'date': now_date, 'timestamp': now_iso, 'session': session_name,
            'pair': instrument, 'symbol': instrument, 'direction': direction,
            'setup': f'15m ORB pos{n}', 'entry': entry, 'stop': stop_loss,
            'tp1': tp, 'tp2': 0, 'tp3': 0, 'result': 'Pending',
            'pnl_usd': 0, 'r_multiple': 0,
            'notes': f'ORB pos{n} | units:{units_per_pos} | SL:{stop_loss:.2f} | TP:+{TP_PIPS[f"pos{n}"]}pts',
        })

    short = instrument.split('_')[0]
    dir_word = 'LONG' if direction == 'long' else 'SHORT'
    icon = '🟢' if direction == 'long' else '🔴'
    msg = (f"{icon} BLADE {dir_word} {short} @ {entry:.2f} | "
           f"SL:{stop_loss:.2f} | TPs:{tp1:.2f}/{tp2:.2f}/{tp3:.2f} | units:{units_per_pos}")
    print(f"  >> {msg}")
    logging.info(msg)
    hub_post(AGENT_NAME, "trade", msg, tags=["trading", "entry", session_name.lower()])
    return True

# ─────────────────────────────────────────────────────────────────────────────
# POSITION MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────

def manage_positions():
    """Check all open positions for TP hits and stop losses. pos1 TP → BE for pos2/pos3."""
    global paper_balance
    to_close = []

    for pos_key, pos in list(open_positions.items()):
        instrument, pos_num = pos_key.rsplit(':', 1)
        try:
            price     = get_price(instrument)
            direction = pos['direction']
            entry     = pos['entry']
            stop      = pos['stop_loss']
            units     = pos['units']
            pip_val   = pos['pip_value']
            tp        = pos['tp']

            tp_hit = (price >= tp) if direction == 'long' else (price <= tp)
            if tp_hit:
                pnl = (tp - entry) * units * pip_val if direction == 'long' \
                      else (entry - tp) * units * pip_val
                to_close.append((pos_key, f"TP{pos_num}", pnl, tp))
                if pos_num == '1':
                    for n in ('2', '3'):
                        pk = f"{instrument}:{n}"
                        if pk in open_positions:
                            open_positions[pk]['stop_loss']       = entry
                            open_positions[pk]['breakeven_moved'] = True
                            logging.info(f"BE MOVE: {instrument} pos{n} SL → {entry:.2f}")
                            print(f"  BE: {instrument} pos{n} SL → {entry:.2f}")
                continue

            hit_stop = (price <= stop) if direction == 'long' else (price >= stop)
            if hit_stop:
                if pos.get('breakeven_moved'):
                    pnl, close_price, result = 0.0, entry, 'BE'
                else:
                    pnl = (price - entry) * units * pip_val if direction == 'long' \
                          else (entry - price) * units * pip_val
                    close_price, result = price, 'SL'
                to_close.append((pos_key, result, pnl, close_price))
        except Exception as e:
            logging.error(f"manage_positions {pos_key}: {e}")

    for pos_key, result, pnl, close_price in to_close:
        if pos_key not in open_positions:
            continue
        paper_balance += pnl
        update_trade_log(open_positions[pos_key]['trade_id'], result, pnl, f"Closed: {result}")
        instrument, pos_num = pos_key.rsplit(':', 1)
        short = instrument.split('_')[0]
        icon  = '✅' if pnl > 0 else ('⚪' if result == 'BE' else '🔴')
        logging.info(f"{result}: {instrument} pos{pos_num} @ {close_price:.2f} PnL:${pnl:.2f}")
        print(f"  {icon} {result}: {instrument} pos{pos_num} @ {close_price:.2f} | ${pnl:.2f}")
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
        pnl = (price - pos['entry']) * pos['units'] * pos['pip_value'] if pos['direction'] == 'long' \
              else (pos['entry'] - price) * pos['units'] * pos['pip_value']
        paper_balance += pnl
        update_trade_log(pos['trade_id'], "Time Stop", pnl, reason)
        logging.info(f"TIME STOP: {instrument} pos{pos_num} @ {price:.2f} PnL:${pnl:.2f}")
        print(f"  TIME STOP: {instrument} pos{pos_num} @ {price:.2f} | ${pnl:.2f}")
        del open_positions[pos_key]

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
    """Pure ORB runner: wait → ORB → monitor M1 breakouts → manage → close."""
    global session_trades
    session_trades = []

    if paper_balance < MIN_BALANCE:
        msg = wrap_message("blade", f"HALT. Balance ${paper_balance:.2f} below ${MIN_BALANCE} floor. Standing down.")
        print(msg); logging.warning(msg); send_telegram(msg)
        return

    instruments = SESSION_INSTRUMENTS[session_name]
    print(f"\n{'='*60}\nBLADE v5 — {session_name} | Instruments: {instruments} | ${paper_balance:.2f}\n{'='*60}")
    logging.info(f"SESSION START: {session_name} | ${paper_balance:.2f}")
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
    print(f"\n{'='*60}\n{session_name} COMPLETE | Balance: ${paper_balance:.2f} | {total} closed\n{'='*60}")
    logging.info(f"SESSION END: {session_name} | Balance: ${paper_balance:.2f}")
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
