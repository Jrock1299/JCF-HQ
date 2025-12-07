import os
import aiohttp
import ccxt.async_support as ccxt
import pandas as pd
import datetime

# --- CONFIG ---
FMP_KEY = os.getenv("FMP_KEY")
CRYPTO_PAIRS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT"]

# --- MACRO NEWS ENGINE ---
async def fetch_major_news():
    """
    Fetches High Impact economic news from FMP for 'today'.
    Returns a list of formatted strings or None.
    """
    if not FMP_KEY:
        return None

    # Get today's date
    today = datetime.date.today().strftime("%Y-%m-%d")
    url = f"https://financialmodelingprep.com/api/v3/economic_calendar?from={today}&to={today}&apikey={FMP_KEY}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                return None
            data = await response.json()

    # Filter for "High" importance only (Red Folder Events)
    # Note: FMP doesn't strictly have an "importance" field in the free tier standard endpoint sometimes,
    # but we can filter by key major events or if the field exists.
    # We will look for major keywords if importance isn't listed.
    
    important_news = []
    major_events = ["Fed", "CPI", "GDP", "Unemployment", "Interest Rate", "FOMC"]

    for event in data:
        event_name = event.get('event', '')
        # Check if it matches our "Major" list
        if any(x in event_name for x in major_events):
            time = event.get('date', '').split(' ')[1] # Extract time
            impact = "🔥 HIGH" 
            formatted = f"**{impact} IMPACT: {event_name}**\n🕒 Time: {time} UTC\nActual: {event.get('actual', '-')} | Est: {event.get('estimate', '-')}"
            important_news.append(formatted)
            
    return important_news

# --- WHALE WATCHER ENGINE ---
async def check_crypto_whales():
    """
    Scans Binance for Volume Anomalies (> 300% of average).
    Returns: List of alerts.
    """
    exchange = ccxt.binanceus({'enableRateLimit': True}) 
    alerts = []

    try:
        for symbol in CRYPTO_PAIRS:
            # Fetch last 50 candles (1 hour timeframe)
            ohlcv = await exchange.fetch_ohlcv(symbol, timeframe='1h', limit=50)
            if not ohlcv:
                continue

            df = pd.DataFrame(ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
            
            # Calculate Average Volume (last 20 candles)
            avg_vol = df['volume'].rolling(window=20).mean().iloc[-1]
            current_vol = df['volume'].iloc[-1]
            current_close = df['close'].iloc[-1]
            open_price = df['open'].iloc[-1]

            # WHALE LOGIC: Is current volume > 3x the average?
            if current_vol > (avg_vol * 3):
                # Determine Direction
                direction = "🟢 BUY/ACCUMULATION" if current_close > open_price else "🔴 SELL/DUMP"
                pct_vol = (current_vol / avg_vol) * 100
                
                alert = (
                    f"🐳 **WHALE ALERT: {symbol}**\n"
                    f"Type: {direction}\n"
                    f"Volume: **{pct_vol:.0f}%** higher than average\n"
                    f"Price: ${current_close:,.2f}"
                )
                alerts.append(alert)

    except Exception as e:
        print(f"Whale Scan Error: {e}")
    finally:
        await exchange.close()

    return alerts

