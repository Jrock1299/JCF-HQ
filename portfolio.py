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
            return json.load(f)
    except:
        return []

def save_portfolio(data):
    # Ensure directory exists
    if not os.path.exists("/app/data"):
        os.makedirs("/app/data")
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f)

# --- TRADE LOGIC ---
def open_position(symbol, entry_price, direction, asset_type):
    """
    Records a new virtual trade.
    """
    trades = load_portfolio()
    
    # Optional: Check if we already have an open trade for this symbol
    # to prevent spamming multiple buys on the same asset.
    for t in trades:
        if t['symbol'] == symbol and t['status'] == 'OPEN':
            return False # Trade already exists

    new_trade = {
        "id": len(trades) + 1,
        "symbol": symbol,
        "entry_price": float(entry_price),
        "direction": direction, # "BUY" or "SELL"
        "asset_type": asset_type,
        "status": "OPEN",
        "timestamp": datetime.now().isoformat(),
        "size": 1000 # Virtual $1000 position
    }
    
    trades.append(new_trade)
    save_portfolio(trades)
    return True

# --- PNL CALCULATION ---
async def get_current_price(symbol, asset_type):
    """
    Fetches live price to calculate PnL.
    """
    price = 0.0
    try:
        # 1. CRYPTO
        if asset_type == "CRYPTO":
            exchange = ccxt.binanceus()
            ticker = await exchange.fetch_ticker(symbol)
            price = ticker['last']
            await exchange.close()

        # 2. STOCKS
        elif asset_type == "STOCK":
            url = f"https://financialmodelingprep.com/api/v3/quote-short/{symbol}?apikey={FMP_KEY}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data: price = float(data[0]['price'])

        # 3. FOREX
        elif asset_type == "FOREX":
            # Using OANDA Live
            clean_pair = symbol.replace("/", "_")
            url = f"https://api-fxtrade.oanda.com/v3/instruments/{clean_pair}/candles?count=1&granularity=M1"
            headers = {"Authorization": f"Bearer {OANDA_TOKEN}"}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        price = float(data['candles'][0]['mid']['c'])
    except Exception as e:
        print(f"Price fetch error for {symbol}: {e}")
        
    return price

async def generate_portfolio_report():
    """
    Generates a performance report for Discord.
    """
    trades = load_portfolio()
    active_trades = [t for t in trades if t['status'] == 'OPEN']
    
    if not active_trades:
        return None, "No active paper trades."

    report_lines = []
    total_pnl = 0.0
    
    for t in active_trades:
        current_price = await get_current_price(t['symbol'], t['asset_type'])
        
        if current_price == 0:
            pnl_pct = 0.0
        else:
            # Logic: (Current - Entry) / Entry * 100
            if "BUY" in t['direction']:
                pnl_pct = ((current_price - t['entry_price']) / t['entry_price']) * 100
            else: # Short/Sell
                pnl_pct = ((t['entry_price'] - current_price) / t['entry_price']) * 100
        
        # Add Emoji
        icon = "🟢" if pnl_pct >= 0 else "🔴"
        line = f"{icon} **{t['symbol']}**: {t['direction']} @ {t['entry_price']:.4f} ➜ Now {current_price:.4f} (**{pnl_pct:+.2f}%**)"
        report_lines.append(line)
        total_pnl += pnl_pct

    return total_pnl, "\n".join(report_lines)
