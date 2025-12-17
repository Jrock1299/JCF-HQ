import os
import json
import ccxt.async_support as ccxt
import aiohttp
from datetime import datetime

# --- CONFIG ---
DATA_FILE = "/app/data/paper_portfolio.json"
FMP_KEY = os.getenv("FMP_KEY")
OANDA_TOKEN = os.getenv("OANDA_TOKEN")

# --- FILE MANAGEMENT ---
def load_portfolio():
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
            # Ensure it's a list, not a dict or None
            if isinstance(data, list):
                return data
            return []
    except:
        return []

def save_portfolio(data):
    # Ensure directory exists
    if not os.path.exists("/app/data"):
        os.makedirs("/app/data")
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f)

# --- TRADE ENTRY ---
def open_position(symbol, entry_price, direction, asset_type, sl, tp, style):
    trades = load_portfolio()
    
    # Prevent duplicate opens
    for t in trades:
        if t['symbol'] == symbol and t['status'] == 'OPEN' and t.get('style') == style:
            return False 

    new_trade = {
        "id": len(trades) + 1,
        "symbol": symbol,
        "entry_price": float(entry_price),
        "direction": direction,
        "asset_type": asset_type,
        "stop_loss": float(sl),
        "take_profit": float(tp),
        "style": style, 
        "status": "OPEN",
        "timestamp": datetime.now().isoformat(),
        "close_price": 0.0,
        "pnl_pct": 0.0,
        "outcome": None
    }
    
    trades.append(new_trade)
    save_portfolio(trades)
    return True

# --- PRICE FETCHING ---
async def get_current_price(symbol, asset_type):
    price = 0.0
    try:
        if asset_type == "CRYPTO":
            # Instantiate properly to avoid unclosed connector errors
            exchange = ccxt.binanceus({'enableRateLimit': True})
            try:
                ticker = await exchange.fetch_ticker(symbol)
                price = ticker['last']
            finally:
                await exchange.close()

        elif asset_type == "STOCK":
            url = f"https://financialmodelingprep.com/api/v3/quote-short/{symbol}?apikey={FMP_KEY}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data: price = float(data[0]['price'])

        elif asset_type == "FOREX":
            clean_pair = symbol.replace("/", "_")
            url = f"https://api-fxtrade.oanda.com/v3/instruments/{clean_pair}/candles?count=1&granularity=M1"
            headers = {"Authorization": f"Bearer {OANDA_TOKEN}"}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        price = float(data['candles'][0]['mid']['c'])
    except Exception as e:
        print(f"Price Fetch Error for {symbol}: {e}")
        return 0.0
        
    return price

# --- EXIT MANAGER ---
async def update_positions():
    trades = load_portfolio()
    active_trades = [t for t in trades if t['status'] == 'OPEN']
    closed_notifications = []
    
    if not active_trades:
        return []

    data_changed = False
    
    for t in active_trades:
        # 1. Backwards Compatibility: Handle missing keys from old trades
        if 'stop_loss' not in t: t['stop_loss'] = 0.0
        if 'take_profit' not in t: t['take_profit'] = 0.0
        if 'style' not in t: t['style'] = "SWING" # Default old trades to SWING

        current_price = await get_current_price(t['symbol'], t['asset_type'])
        if current_price == 0: continue
        
        outcome = None
        close_reason = None
        
        # BUY LOGIC
        if "BUY" in t['direction']:
            if t['take_profit'] > 0 and current_price >= t['take_profit']:
                outcome = "WIN"
                close_reason = "Hit Take Profit 🎯"
            elif t['stop_loss'] > 0 and current_price <= t['stop_loss']:
                outcome = "LOSS"
                close_reason = "Hit Stop Loss 🛑"
        
        # SELL LOGIC
        elif "SELL" in t['direction']:
            if t['take_profit'] > 0 and current_price <= t['take_profit']:
                outcome = "WIN"
                close_reason = "Hit Take Profit 🎯"
            elif t['stop_loss'] > 0 and current_price >= t['stop_loss']:
                outcome = "LOSS"
                close_reason = "Hit Stop Loss 🛑"
        
        if outcome:
            if "BUY" in t['direction']:
                pnl = ((current_price - t['entry_price']) / t['entry_price']) * 100
            else:
                pnl = ((t['entry_price'] - current_price) / t['entry_price']) * 100
                
            t['status'] = "CLOSED"
            t['close_price'] = current_price
            t['pnl_pct'] = pnl
            t['outcome'] = outcome
            
            closed_notifications.append(f"{close_reason}: **{t['symbol']}** ({t['style']})\nProfit: **{pnl:+.2f}%**")
            data_changed = True

    if data_changed:
        save_portfolio(trades)
        
    return closed_notifications

# --- REPORTING ---
async def generate_portfolio_report():
    try:
        trades = load_portfolio()
        active_trades = [t for t in trades if t['status'] == 'OPEN']
        closed_trades = [t for t in trades if t['status'] == 'CLOSED']
        
        # Calculate Stats
        wins = len([t for t in closed_trades if t.get('outcome') == "WIN"])
        losses = len([t for t in closed_trades if t.get('outcome') == "LOSS"])
        total_closed = wins + losses
        win_rate = (wins / total_closed * 100) if total_closed > 0 else 0.0
        
        report_lines = []
        report_lines.append(f"📊 **Performance:** {wins} Wins / {losses} Losses (**{win_rate:.0f}% Win Rate**)")
        report_lines.append("---")
        
        if not active_trades:
            return 0.0, "\n".join(report_lines) + "\n\n(No active positions)"

        total_unrealized_pnl = 0.0
        
        for t in active_trades:
            # Safe Get for Style
            style = t.get('style', 'SWING')
            
            current_price = await get_current_price(t['symbol'], t['asset_type'])
            
            pnl = 0.0
            if current_price > 0:
                if "BUY" in t['direction']:
                    pnl = ((current_price - t['entry_price']) / t['entry_price']) * 100
                else:
                    pnl = ((t['entry_price'] - current_price) / t['entry_price']) * 100
            
            icon = "🟢" if pnl >= 0 else "🔴"
            line = f"{icon} **{t['symbol']}** ({style}): {pnl:+.2f}%"
            report_lines.append(line)
            total_unrealized_pnl += pnl

        return total_unrealized_pnl, "\n".join(report_lines)
        
    except Exception as e:
        return 0.0, f"⚠️ Error generating report: {str(e)}"
