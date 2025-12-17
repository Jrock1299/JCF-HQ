import os
import aiohttp
import ccxt.async_support as ccxt
import pandas as pd
from datetime import datetime, timedelta

# --- CONFIG ---
FMP_KEY = os.getenv("FMP_KEY")
WATCHLIST_STOCKS = os.getenv("STOCK_TICKERS", "NVDA,TSLA,AAPL,SOFI,BULL").split(",")
CRYPTO_PAIRS = os.getenv("CRYPTO_PAIRS", "BTC/USDT,ETH/USDT").split(",")

# --- 1. SAFETY CHECK (THE NEW SHIELD) ---
async def is_market_safe_from_news():
    """
    Returns False if High Impact News is within 60 mins.
    Returns True if safe to trade.
    """
    if not FMP_KEY: return True # Default to safe if no key (risky but necessary fallback)
    
    today = datetime.utcnow().strftime("%Y-%m-%d")
    url = f"https://financialmodelingprep.com/api/v3/economic_calendar?from={today}&to={today}&apikey={FMP_KEY}"
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    current_time = datetime.utcnow()
                    
                    for event in data:
                        # Filter for HIGH IMPACT events only
                        # FMP doesn't always tag 'impact', so we filter by keywords
                        event_name = event.get('event', '').lower()
                        high_impact_keywords = ["fed", "cpi", "gdp", "unemployment", "interest rate", "non-farm", "fomc"]
                        
                        if any(x in event_name for x in high_impact_keywords):
                            event_date_str = event.get('date', '') # Format: 2023-10-27 12:30:00
                            if not event_date_str: continue
                            
                            event_dt = datetime.strptime(event_date_str, "%Y-%m-%d %H:%M:%S")
                            
                            # Check time difference
                            diff_minutes = (event_dt - current_time).total_seconds() / 60
                            
                            # DANGER ZONE: 60 mins before to 30 mins after
                            if -30 < diff_minutes < 60:
                                return False # MARKET IS DANGEROUS
        except:
            return True # Fallback
    return True

# --- 2. MACRO NEWS (Display) ---
async def fetch_major_news():
    if not FMP_KEY: return None
    today = datetime.utcnow().strftime("%Y-%m-%d")
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
        except: return None
    return None

# --- 3. WHALE WATCHER ---
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
                
                if current_vol > (avg_vol * 3):
                    direction = "🟢 BUY/ACCUMULATION" if df['close'].iloc[-1] > df['open'].iloc[-1] else "🔴 SELL/DUMP"
                    pct = (current_vol / avg_vol) * 100
                    alerts.append(f"🐳 **WHALE ALERT: {symbol}**\nType: {direction}\nVol: **{pct:.0f}%** > Avg\nPrice: ${df['close'].iloc[-1]:.2f}")
            except: continue
    except: pass
    finally: await exchange.close()
    return alerts

# --- 4. INSIDER TRADING ---
async def check_insider_trading():
    if not FMP_KEY: return []
    alerts = []
    async with aiohttp.ClientSession() as session:
        for symbol in WATCHLIST_STOCKS:
            url = f"https://financialmodelingprep.com/api/v4/insider-trading?symbol={symbol}&page=0&apikey={FMP_KEY}"
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for trade in data[:3]:
                            if 'Purchase' in trade.get('transactionType', '') and trade.get('securitiesTransacted', 0) > 1000:
                                person = trade.get('reportingName', 'Unknown')
                                amount = float(trade.get('securitiesTransacted', 0)) * float(trade.get('price', 0))
                                if amount > 50000:
                                    alert = (f"🚨 **INSIDER BUY: {symbol}**\n👤 {person}\n💰 ${amount:,.0f}")
                                    alerts.append(alert)
            except: continue
    return list(set(alerts))

# --- 5. SMART MONEY ---
async def check_smart_money():
    if not FMP_KEY: return []
    alerts = []
    async with aiohttp.ClientSession() as session:
        for symbol in WATCHLIST_STOCKS:
            url = f"https://financialmodelingprep.com/api/v4/institutional-ownership/symbol-positions-summary?symbol={symbol}&apikey={FMP_KEY}"
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data:
                            latest = data[0]
                            change = latest.get('investorsHoldingChange', 0)
                            if change > 5: 
                                alerts.append(f"🏦 **SMART MONEY: {symbol}**\n📈 Hedge Funds Added: +{change}")
            except: continue
    return alerts
