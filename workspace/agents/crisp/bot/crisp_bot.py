import ccxt
import time
import json
import logging
from datetime import datetime, timezone

logging.basicConfig(
    filename='/root/.openclaw/agents/crisp/bot/crisp.log',
    level=logging.INFO,
    format='%(asctime)s %(message)s'
)

binance = ccxt.binance({'enableRateLimit': True})

SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT']
RISK_PERCENT = 0.04
LEVERAGE = 3
MIN_STOP_DISTANCE = 0.01

paper_balance = 10000.0
open_positions = {}

# Session open times in UTC
SESSIONS = {
    'NY':   {'hour': 14, 'minute': 30},
    'ASIA': {'hour': 0,  'minute': 0},
}

def get_candles(symbol, timeframe, limit):
    return binance.fetch_ohlcv(symbol, timeframe, limit=limit)

def get_price(symbol):
    return binance.fetch_ticker(symbol)['last']

def wait_for_session_open(session_name):
    session = SESSIONS[session_name]
    target_hour = session['hour']
    target_minute = session['minute']
    print(f"⏳ Waiting for {session_name} session open ({target_hour:02d}:{target_minute:02d} UTC)...")
    while True:
        now = datetime.now(timezone.utc)
        if now.hour == target_hour and now.minute == target_minute:
            print(f"🔔 {session_name} session open! {now.strftime('%H:%M:%S')} UTC")
            return
        time.sleep(10)

def get_opening_candle(symbol):
    """Get the first 15m candle of the session and wait for it to close"""
    print(f"📊 Recording opening 15m candle for {symbol}...")
    # Get the current 15m candle (the one that just opened at session start)
    candles = get_candles(symbol, '15m', 2)
    if not candles:
        return None, None
    opening_candle = candles[-2]  # Last closed candle
    high = opening_candle[2]
    low = opening_candle[3]
    return high, low

def wait_for_candle_close():
    """Wait until the current 15m candle closes"""
    now = datetime.now(timezone.utc)
    # Calculate seconds until next 15m boundary
    minutes = now.minute
    seconds = now.second
    remaining_minutes = 14 - (minutes % 15)
    remaining_seconds = (remaining_minutes * 60) + (60 - seconds)
    if remaining_seconds > 900:
        remaining_seconds = remaining_seconds - 900
    print(f"⏳ Waiting {remaining_seconds//60}m {remaining_seconds%60}s for 15m candle to close...")
    time.sleep(remaining_seconds + 2)  # +2 seconds buffer
    print(f"✅ 15m candle closed — dropping to 1m chart")

def check_1m_breakout(symbol, orb_high, orb_low):
    """Check if a 1m candle has fully closed above or below the ORB range"""
    candles = get_candles(symbol, '1m', 3)
    if not candles:
        return None
    # Use the last fully closed candle (second to last)
    last_closed = candles[-2]
    close = last_closed[4]
    open_price = last_closed[1]
    # Full candle body must close beyond the range
    if close > orb_high and open_price > orb_high:
        return 'long'
    elif close < orb_low and open_price < orb_low:
        return 'short'
    return None

def place_paper_order(symbol, direction, orb_high, orb_low):
    global paper_balance
    price = get_price(symbol)
    if direction == 'long':
        stop_loss = orb_low
        take_profit = price + (price - orb_low) * 2
    else:
        stop_loss = orb_high
        take_profit = price - (orb_high - price) * 2

    stop_distance = abs(price - stop_loss) / price
    stop_distance = max(stop_distance, MIN_STOP_DISTANCE)
    risk_amount = paper_balance * RISK_PERCENT
    max_position_value = (paper_balance / 3) * LEVERAGE
    position_value = min(risk_amount / stop_distance, max_position_value)
    amount = round(position_value / price, 4)

    open_positions[symbol] = {
        'direction': direction,
        'entry': price,
        'stop_loss': stop_loss,
        'take_profit': take_profit,
        'amount': amount,
        'position_value': position_value,
        'open_time': datetime.now().strftime('%H:%M:%S'),
        'breakeven_moved': False,
    }

    msg = f"PAPER TRADE: {symbol} {direction.upper()} | Entry: {price} | SL: {stop_loss:.4f} | TP: {take_profit:.4f} | Size: {amount} | Value: ${position_value:.2f}"
    print(f"✅ {msg}")
    logging.info(msg)
    return True

def manage_positions():
    global paper_balance
    to_close = []
    for symbol, pos in open_positions.items():
        try:
            price = get_price(symbol)
            direction = pos['direction']
            entry = pos['entry']
            stop = pos['stop_loss']
            tp = pos['take_profit']
            amount = pos['amount']

            if direction == 'long':
                pnl = (price - entry) * amount
                hit_stop = price <= stop
                hit_tp = price >= tp
                if not pos['breakeven_moved'] and price >= entry * 1.03:
                    open_positions[symbol]['stop_loss'] = entry
                    open_positions[symbol]['breakeven_moved'] = True
                    print(f"🔒 {symbol} stop moved to breakeven at {entry}")
                    logging.info(f"BREAKEVEN: {symbol} stop moved to {entry}")
            else:
                pnl = (entry - price) * amount
                hit_stop = price >= stop
                hit_tp = price <= tp
                if not pos['breakeven_moved'] and price <= entry * 0.97:
                    open_positions[symbol]['stop_loss'] = entry
                    open_positions[symbol]['breakeven_moved'] = True
                    print(f"🔒 {symbol} stop moved to breakeven at {entry}")
                    logging.info(f"BREAKEVEN: {symbol} stop moved to {entry}")

            status = "🟢" if pnl > 0 else "🔴"
            print(f"{status} {symbol} {direction.upper()} | Entry:{entry} Current:{price} | Unrealized PnL: ${pnl:.2f} | SL:{stop:.4f} TP:{tp:.4f}")

            if hit_stop:
                paper_balance += pnl
                to_close.append(symbol)
                msg = f"STOP HIT: {symbol} {direction.upper()} | Entry:{entry} Exit:{price} | PnL: ${pnl:.2f} | Balance: ${paper_balance:.2f}"
                print(f"🛑 {msg}")
                logging.info(msg)
            elif hit_tp:
                paper_balance += pnl
                to_close.append(symbol)
                msg = f"TP HIT: {symbol} {direction.upper()} | Entry:{entry} Exit:{price} | PnL: ${pnl:.2f} | Balance: ${paper_balance:.2f}"
                print(f"🎯 {msg}")
                logging.info(msg)

        except Exception as e:
            print(f"Position check error {symbol}: {e}")

    for symbol in to_close:
        del open_positions[symbol]

def run_orb_session(session_name):
    global paper_balance
    print(f"\n{'='*50}")
    print(f"{session_name} ORB Session — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"Starting balance: ${paper_balance:.2f}")
    print(f"{'='*50}")
    logging.info(f"{session_name} ORB session started | Balance: ${paper_balance:.2f}")

    # Step 1 — Wait for session open
    wait_for_session_open(session_name)

    # Step 2 — Record the opening 15m candle high and low
    print(f"\n📊 Recording opening range for all symbols...")
    orb_ranges = {}
    for symbol in SYMBOLS:
        # Wait for candle to close first
        pass

    # Wait for the 15m candle to fully close
    wait_for_candle_close()

    # Step 3 — Get the closed opening candle range
    for symbol in SYMBOLS:
        high, low = get_opening_candle(symbol)
        if high and low:
            orb_ranges[symbol] = {'high': high, 'low': low}
            print(f"📊 {symbol} ORB marked — High: {high} Low: {low}")
        else:
            print(f"⚠️ Could not get ORB range for {symbol}")

    if not orb_ranges:
        print("❌ No ORB ranges found, aborting session")
        return

    # Step 4 — Monitor 1m chart for breakouts for 4 hours
    end_time = time.time() + (4 * 3600)
    traded = set()
    print(f"\n🔍 Monitoring 1m chart for breakouts...")

    while time.time() < end_time:
        for symbol in SYMBOLS:
            if symbol in traded or symbol not in orb_ranges:
                continue
            direction = check_1m_breakout(symbol, orb_ranges[symbol]['high'], orb_ranges[symbol]['low'])
            if direction:
                print(f"🚨 BREAKOUT: {symbol} {direction.upper()} — 1m candle fully closed beyond ORB")
                success = place_paper_order(symbol, direction, orb_ranges[symbol]['high'], orb_ranges[symbol]['low'])
                if success:
                    traded.add(symbol)

        if open_positions:
            manage_positions()

        print(f"💰 Balance: ${paper_balance:.2f} | Open: {list(open_positions.keys())} | Time: {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC")
        time.sleep(30)

    # Close remaining positions at market
    for symbol in list(open_positions.keys()):
        pos = open_positions[symbol]
        price = get_price(symbol)
        if pos['direction'] == 'long':
            pnl = (price - pos['entry']) * pos['amount']
        else:
            pnl = (pos['entry'] - price) * pos['amount']
        paper_balance += pnl
        msg = f"TIME STOP: {symbol} {pos['direction'].upper()} | Entry:{pos['entry']} Exit:{price} | PnL: ${pnl:.2f}"
        print(f"⏰ {msg}")
        logging.info(msg)

    open_positions.clear()
    print(f"\n{'='*50}")
    print(f"{session_name} session complete")
    print(f"Trades taken: {len(traded)}")
    print(f"Final balance: ${paper_balance:.2f}")
    print(f"{'='*50}")
    logging.info(f"{session_name} complete | Trades:{len(traded)} | Final balance:${paper_balance:.2f}")

def read_strategy():
    try:
        with open('/root/.openclaw/agents/crisp/workspace/STRATEGY.md') as f:
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
