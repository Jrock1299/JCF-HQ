import os
import aiohttp
import ccxt.async_support as ccxt
import pandas as pd
import datetime

# --- CONFIG ---
FMP_KEY = os.getenv("FMP_KEY")
# We scan these specific tickers for Insider/Smart Money activity
WATCHLIST_STOCKS = os.getenv("STOCK_TICKERS", "NVDA,TSLA,AAPL,SOFI,BULL").split(",")
CRYPTO_PAIRS = os.getenv("CRYPTO_PAIRS", "BTC/USDT,ETH/USDT").split(",")

# --- 1. MACRO NEWS ENGINE (Existing) ---
async def fetch_major_news():
    if not FMP_KEY: return None
    today = datetime.date.today().strftime("%Y-%m-%d")
    url = f"https://financialmodelingprep.com/api/v3/economic_calendar?from={today}&to={today}&apikey={FMP_KEY}"
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    important_news = []
                    major_events = ["Fed", "CPI", "GDP", "Unemployment", "Interest Rate"]
                    for event in data:
                        if any(x in event.get('event', '') for x in major_events):
                            time = event.get('date', '').split(' ')[1]
                            fmt = f"**🔥 MACRO ALERT: {event.get('event')}**\n🕒 {time} UTC | Actual: {event.get('actual','-')} vs Est: {event.get('estimate','-')}"
                            important_news.append(fmt)
                    return important_news
        except:
            return None
    return None

# --- 2. WHALE WATCHER (Existing) ---
async def check_crypto_whales():
    exchange = ccxt.binanceus({'enableRateLimit': True}) 
    alerts = []
    try:
        for symbol in CRYPTO_PAIRS:
            if not symbol: continue
            try:
                ohlcv = await exchange.fetch_ohlcv(symbol, timeframe='1h', limit=50)
                if not ohlcv: continue
                df = pd.DataFrame(ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
                avg_vol = df['volume'].rolling(window=20).mean().iloc[-1]
                current_vol = df['volume'].iloc[-1]
                
                # If Volume is 3x Average
                if current_vol > (avg_vol * 3):
                    direction = "🟢 BUY/ACCUMULATION" if df['close'].iloc[-1] > df['open'].iloc[-1] else "🔴 SELL/DUMP"
                    pct = (current_vol / avg_vol) * 100
                    alerts.append(f"🐳 **WHALE ALERT: {symbol}**\nType: {direction}\nVol: **{pct:.0f}%** > Avg\nPrice: ${df['close'].iloc[-1]:.2f}")
            except: continue
    except: pass
    finally: await exchange.close()
    return alerts

# --- 3. INSIDER TRADING SCANNER (New!) ---
async def check_insider_trading():
    """
    Checks for recent Insider Buys (Form 4) for our watchlist stocks.
    """
    if not FMP_KEY: return []
    alerts = []
    
    async with aiohttp.ClientSession() as session:
        for symbol in WATCHLIST_STOCKS:
            # We look for 'Purchase' transactions specifically
            url = f"https://financialmodelingprep.com/api/v4/insider-trading?symbol={symbol}&page=0&apikey={FMP_KEY}"
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        # Check the last 3 transactions
                        for trade in data[:3]:
                            # Filter for 'Purchase' only (Bullish) and recent dates
                            if 'Purchase' in trade.get('transactionType', '') and trade.get('securitiesTransacted', 0) > 1000:
                                # Simple check to avoid spamming old news (checking transactionDate vs Today is complex with timezones, 
                                # so we'll just return the raw latest alerts and rely on the bot loop frequency to catch new ones mostly)
                                person = trade.get('reportingName', 'Unknown')
                                amount = float(trade.get('securitiesTransacted', 0)) * float(trade.get('price', 0))
                                
                                if amount > 50000: # Only report buys > $50k
                                    alert = (
                                        f"🚨 **INSIDER BUY: {symbol}**\n"
                                        f"👤 Who: {person} ({trade.get('typeOfOwner')})\n"
                                        f"💰 Amount: ${amount:,.0f}\n"
                                        f"📅 Date: {trade.get('transactionDate')}"
                                    )
                                    alerts.append(alert)
            except: continue
    # Deduplicate alerts
    return list(set(alerts))

# --- 4. SMART MONEY / INSTITUTIONAL (New!) ---
async def check_smart_money():
    """
    Checks for Institutional Accumulation (Hedge Funds buying).
    """
    if not FMP_KEY: return []
    alerts = []
    
    async with aiohttp.ClientSession() as session:
        for symbol in WATCHLIST_STOCKS:
            # Check Institutional Ownership changes
            url = f"https://financialmodelingprep.com/api/v4/institutional-ownership/symbol-positions-summary?symbol={symbol}&apikey={FMP_KEY}"
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data:
                            latest = data[0]
                            change = latest.get('investorsHoldingChange', 0)
                            
                            # If multiple funds entered this quarter
                            if change > 5: 
                                alert = (
                                    f"🏦 **SMART MONEY FLOW: {symbol}**\n"
                                    f"📈 Hedge Funds Added: +{change}\n"
                                    f"Total Institutions: {latest.get('investorsHolding')}\n"
                                    f"Sentiment: ACCUMULATION"
                                )
                                alerts.append(alert)
            except: continue
            
    return alerts
