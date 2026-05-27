import oandapyV20
from oandapyV20 import API
from oandapyV20.endpoints.accounts import AccountDetails
from oandapyV20.endpoints.instruments import InstrumentsCandles
from oandapyV20.endpoints.orders import OrderCreate
from oandapyV20.endpoints.trades import TradesList
import json
import time
import logging
from datetime import datetime, timezone

logging.basicConfig(
    filename='/root/.openclaw/agents/blade/bot/blade.log',
    level=logging.INFO,
    format='%(asctime)s %(message)s'
)

with open('/root/.openclaw/agents/main/agent/auth-profiles.json') as f:
    auth = json.load(f)

creds = auth['profiles']['oanda:default']
client = API(access_token=creds['key'], environment='practice')
ACCOUNT_ID = creds['account_id']

INSTRUMENTS = ['GBP_JPY', 'AUD_CAD', 'XAU_USD', 'NAS100_USD', 'SPX500_USD']
RISK_PERCENT = 0.02
MIN_STOP_DISTANCE = 0.001

SESSIONS = {
    'ASIA':   {'start_hour': 0, 'end_hour': 3, 'minute': 0},  # 00:00–03:00 UTC
    'LONDON': {'hour': 8,  'minute': 0},
    'NY':     {'hour': 13, 'minute': 30},
}

paper_balance = 2000.0
open_positions = {}


def test_oanda_connection():
    try:
        r = AccountDetails(ACCOUNT_ID)
        client.request(r)
        bal = r.response['account'].get('balance')
        msg = f"OANDA PRACTICE OK | account={ACCOUNT_ID} | balance={bal}"
        print(msg)
        logging.info(msg)
        return True
    except Exception as e:
        msg = f"OANDA PRACTICE ERROR | account={ACCOUNT_ID} | error={e}"
        print(msg)
        logging.error(msg)
        return False

def get_balance():
    r = AccountDetails(ACCOUNT_ID)
    client.request(r)
    return float(r.response['account']['balance'])

def get_candles(instrument, granularity, count):
    params = {'granularity': granularity, 'count': count}
    r = InstrumentsCandles(instrument, params=params)
    client.request(r)
    return r.response['candles']

def get_price(instrument):
    candles = get_candles(instrument, 'M1', 2)
    return float(candles[-1]['mid']['c'])

def get_orb_range(instrument):
    candles = get_candles(instrument, 'M15', 3)
    # Get the last fully closed 15m candle
    closed = [c for c in candles if c['complete']]
    if not closed:
        return None, None
    candle = closed[-1]
    high = float(candle['mid']['h'])
    low = float(candle['mid']['l'])
    return high, low

def check_1m_breakout(instrument, orb_high, orb_low):
    candles = get_candles(instrument, 'M1', 3)
    closed = [c for c in candles if c['complete']]
    if not closed:
        return None
    last = closed[-1]
    close = float(last['mid']['c'])
    open_price = float(last['mid']['o'])
    if close > orb_high and open_price > orb_high:
        return 'long'
    elif close < orb_low and open_price < orb_low:
        return 'short'
    return None

def wait_for_session_open(session_name):
    session = SESSIONS[session_name]
    if 'start_hour' in session and 'end_hour' in session:
        print(f"Waiting for {session_name} window ({session['start_hour']:02d}:00–{session['end_hour']:02d}:00 UTC)...")
        while True:
            now = datetime.now(timezone.utc)
            if session['start_hour'] <= now.hour < session['end_hour']:
                if now.minute >= session.get('minute', 0):
                    print(f"{session_name} session open! {now.strftime('%H:%M:%S')} UTC")
                    return
            time.sleep(10)
    else:
        print(f"Waiting for {session_name} open ({session['hour']:02d}:{session['minute']:02d} UTC)...")
        while True:
            now = datetime.now(timezone.utc)
            if now.hour == session['hour'] and now.minute == session['minute']:
                print(f"{session_name} session open! {now.strftime('%H:%M:%S')} UTC")
                return
            time.sleep(10)

def wait_for_candle_close():
    now = datetime.now(timezone.utc)
    minutes = now.minute
    seconds = now.second
    remaining = ((14 - (minutes % 15)) * 60) + (60 - seconds) + 2
    if remaining > 900:
        remaining -= 900
    print(f"Waiting {remaining//60}m {remaining%60}s for 15m candle to close...")
    time.sleep(remaining)
    print("15m candle closed — monitoring 1m chart")

def place_paper_order(instrument, direction, orb_high, orb_low):
    global paper_balance
    price = get_price(instrument)

    if direction == 'long':
        stop_loss = orb_low
        take_profit = price + (price - orb_low) * 2
    else:
        stop_loss = orb_high
        take_profit = price - (orb_high - price) * 2

    stop_distance = abs(price - stop_loss) / price
    stop_distance = max(stop_distance, MIN_STOP_DISTANCE)
    risk_amount = paper_balance * RISK_PERCENT
    max_position_value = (paper_balance / 3)
    position_value = min(risk_amount / stop_distance, max_position_value)
    units = round(position_value / price, 2)

    open_positions[instrument] = {
        'direction': direction,
        'entry': price,
        'stop_loss': stop_loss,
        'take_profit': take_profit,
        'units': units,
        'position_value': position_value,
        'open_time': datetime.now(timezone.utc).strftime('%H:%M:%S'),
        'breakeven_moved': False,
    }

    msg = f"PAPER TRADE: {instrument} {direction.upper()} | Entry:{price} | SL:{stop_loss:.5f} | TP:{take_profit:.5f} | Units:{units} | Value:${position_value:.2f}"
    print(f"✅ {msg}")
    logging.info(msg)
    return True

def manage_positions():
    global paper_balance
    to_close = []
    for instrument, pos in open_positions.items():
        try:
            price = get_price(instrument)
            direction = pos['direction']
            entry = pos['entry']
            stop = pos['stop_loss']
            tp = pos['take_profit']
            units = pos['units']

            if direction == 'long':
                pnl = (price - entry) * units
                hit_stop = price <= stop
                hit_tp = price >= tp
                if not pos['breakeven_moved'] and price >= entry + (entry - stop):
                    open_positions[instrument]['stop_loss'] = entry
                    open_positions[instrument]['breakeven_moved'] = True
                    print(f"🔒 {instrument} stop moved to breakeven {entry}")
                    logging.info(f"BREAKEVEN: {instrument} stop moved to {entry}")
            else:
                pnl = (entry - price) * units
                hit_stop = price >= stop
                hit_tp = price <= tp
                if not pos['breakeven_moved'] and price <= entry - (stop - entry):
                    open_positions[instrument]['stop_loss'] = entry
                    open_positions[instrument]['breakeven_moved'] = True
                    print(f"🔒 {instrument} stop moved to breakeven {entry}")
                    logging.info(f"BREAKEVEN: {instrument} stop moved to {entry}")

            status = "🟢" if pnl > 0 else "🔴"
            print(f"{status} {instrument} {direction.upper()} | Entry:{entry} Current:{price} | PnL:${pnl:.2f} | SL:{stop:.5f} TP:{tp:.5f}")

            if hit_stop:
                paper_balance += pnl
                to_close.append(instrument)
                msg = f"STOP HIT: {instrument} {direction.upper()} | Entry:{entry} Exit:{price} | PnL:${pnl:.2f} | Balance:${paper_balance:.2f}"
                print(f"🛑 {msg}")
                logging.info(msg)
            elif hit_tp:
                paper_balance += pnl
                to_close.append(instrument)
                msg = f"TP HIT: {instrument} {direction.upper()} | Entry:{entry} Exit:{price} | PnL:${pnl:.2f} | Balance:${paper_balance:.2f}"
                print(f"🎯 {msg}")
                logging.info(msg)

        except Exception as e:
            print(f"Position check error {instrument}: {e}")

    for instrument in to_close:
        del open_positions[instrument]

def run_orb_session(session_name):
    global paper_balance
    print(f"\n{'='*50}")
    print(f"BLADE — {session_name} Session | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"Balance: ${paper_balance:.2f}")
    print(f"{'='*50}")
    logging.info(f"{session_name} session started | Balance:${paper_balance:.2f}")

    # confirm OANDA practice connectivity
    test_oanda_connection()

    wait_for_session_open(session_name)

    print(f"\nRecording opening range...")
    wait_for_candle_close()

    orb_ranges = {}
    for instrument in INSTRUMENTS:
        high, low = get_orb_range(instrument)
        if high and low:
            orb_ranges[instrument] = {'high': high, 'low': low}
            print(f"📊 {instrument} ORB — High:{high} Low:{low}")
        else:
            print(f"⚠️ Could not get ORB for {instrument}")

    if not orb_ranges:
        print("No ORB ranges found, aborting")
        return

    end_time = time.time() + (4 * 3600)
    traded = set()
    print(f"\nMonitoring 1m chart for breakouts...")

    while time.time() < end_time:
        for instrument in INSTRUMENTS:
            if instrument in traded or instrument not in orb_ranges:
                continue
            direction = check_1m_breakout(instrument, orb_ranges[instrument]['high'], orb_ranges[instrument]['low'])
            if direction:
                print(f"🚨 BREAKOUT: {instrument} {direction.upper()}")
                success = place_paper_order(instrument, direction, orb_ranges[instrument]['high'], orb_ranges[instrument]['low'])
                if success:
                    traded.add(instrument)

        if open_positions:
            manage_positions()

        print(f"💰 Balance:${paper_balance:.2f} | Open:{list(open_positions.keys())} | {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC")
        time.sleep(30)

    for instrument in list(open_positions.keys()):
        pos = open_positions[instrument]
        price = get_price(instrument)
        if pos['direction'] == 'long':
            pnl = (price - pos['entry']) * pos['units']
        else:
            pnl = (pos['entry'] - price) * pos['units']
        paper_balance += pnl
        msg = f"TIME STOP: {instrument} {pos['direction'].upper()} | Entry:{pos['entry']} Exit:{price} | PnL:${pnl:.2f}"
        print(f"⏰ {msg}")
        logging.info(msg)

    open_positions.clear()
    print(f"\n{'='*50}")
    print(f"{session_name} session complete | Trades:{len(traded)} | Balance:${paper_balance:.2f}")
    print(f"{'='*50}")
    logging.info(f"{session_name} complete | Trades:{len(traded)} | Balance:${paper_balance:.2f}")

def read_strategy():
    try:
        with open('/root/.openclaw/agents/blade/workspace/STRATEGY.md') as f:
            content = f.read()
        print('\n' + '='*50)
        print('STRATEGY.md loaded')
        print('='*50)
        first_line = content.splitlines()[0] if content else ''
        if first_line:
            print(first_line)
    except Exception as e:
        print(f"STRATEGY.md read failed: {e}")

if __name__ == '__main__':
    import sys
    session = sys.argv[1] if len(sys.argv) > 1 else 'NY'
    print('Read your STRATEGY.md file at the start of every session before analyzing the market.')
    read_strategy()
    run_orb_session(session)
