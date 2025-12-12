import os
import asyncio
import ccxt.async_support as ccxt
import pandas as pd
import pandas_ta_classic as ta 
import aiohttp
import json
import data_logger 

# --- CONFIG ---
CRYPTO_PAIRS = os.getenv("CRYPTO_PAIRS", "BTC/USDT,ETH/USDT").split(",")
STOCK_TICKERS = os.getenv("STOCK_TICKERS", "NVDA,TSLA").split(",")
FOREX_PAIRS = os.getenv("FOREX_PAIRS", "EUR_USD").split(",")

OANDA_TOKEN = os.getenv("OANDA_TOKEN")
OANDA_ID = os.getenv("OANDA_ID")
FMP_KEY = os.getenv("FMP_KEY")

# --- 1. NEW: MARKET STRUCTURE ENGINE ---
def check_market_structure(df, lookback=5):
    """
    Determines if the recent structure is Bullish or Bearish
    based on local peaks (Highs) and valleys (Lows).
    """
    # Find local peaks (Highs) and valleys (Lows)
    # A 'Pivot' is a candle higher/lower than its immediate neighbors
    df['high_pivot'] = df['high'][(df['high'].shift(1) < df['high']) & (df['high'].shift(-1) < df['high'])]
    df['low_pivot'] = df['low'][(df['low'].shift(1) > df['low']) & (df['low'].shift(-1) > df['low'])]

    # Get the last 2 confirmed pivots (ignoring NaNs)
    last_highs = df['high_pivot'].dropna().tail(2).values
    last_lows = df['low_pivot'].dropna().tail(2).values

    structure = "NEUTRAL"

    # Check for Uptrend (Higher Highs + Higher Lows)
    if len(last_highs) >= 2 and len(last_lows) >= 2:
        if last_highs[1] > last_highs[0] and last_lows[1] > last_lows[0]:
            structure = "BULLISH"
    
    # Check for Downtrend (Lower Highs + Lower Lows)
    if len(last_highs) >= 2 and len(last_lows) >= 2:
        if last_highs[1] < last_highs[0] and last_lows[1] < last_lows[0]:
            structure = "BEARISH"
            
    return structure

# --- SMART LOGIC ---
def analyze_market(df, symbol, asset_type):
    if df is None or df.empty: return None

    # 1. Calculate Indicators
    df.ta.rsi(length=14, append=True)
    df.ta.ema(length=50, append=True)
    df.ta.ema(length=200, append=True)
    df.ta.atr(length=14, append=True)
    
    # 2. Log Data for AI (The Brain)
    try:
        data_logger.log_market_snapshot(symbol, df, asset_type)
    except: pass

    current = df.iloc[-1]
    
    # 3. Get Market Structure (The New Filter)
    trend_structure = check_market_structure(df.copy())

    signal = None
    confidence = "Low"
    
    rsi = current.get('RSI_14')
    ema200 = current.get('EMA_200')
    price = current['close']
    atr = current.get('ATRr_14')

    if not all([rsi, ema200, atr]): return None

    # --- THE ELITE LOGIC ---
    
    # BUY SETUP: 
    # 1. Price is above EMA 200 (Long Term Trend Up)
    # 2. RSI is Oversold (Short Term Dip)
    # 3. Structure is BULLISH (We are making Higher Highs - NOT catching a falling knife)
    if price > ema200 and rsi < 35:
        if trend_structure == "BULLISH":
            signal = "🟢 BUY"
            confidence = "High" 
        else:
            # If structure is Bearish, we ignore the RSI signal. 
            # This saves us from buying a crash.
            return None 

    # SELL SETUP:
    # 1. Price is below EMA 200 (Long Term Trend Down)
    # 2. RSI is Overbought (Short Term Rally)
    # 3. Structure is BEARISH (Lower Lows confirmed)
    elif price < ema200 and rsi > 65:
        if trend_structure == "BEARISH":
            signal = "🔴 SELL"
            confidence = "High"
        else:
            return None

    if signal:
        # Dynamic Risk Management (ATR)
        sl_dist = atr * 1.5
        tp_dist = atr * 2.0
        
        sl = price - sl_dist if "BUY" in signal else price + sl_dist
        tp = price + tp_dist if "BUY" in signal else price - tp_dist
        
        return {
            "symbol": symbol,
            "signal": signal,
            "price": price,
            "stop_loss": sl,
            "take_profit": tp,
            "confidence": confidence,
            "rsi": rsi,
            "type": asset_type
        }
    return None

# --- SCAN FUNCTIONS (Unchanged logic, just calling new analyze_market) ---
async def scan_crypto():
    exchange = ccxt.binanceus({'enableRateLimit': True})
    signals = []
    try:
        for symbol in CRYPTO_PAIRS:
            if not symbol: continue
            try:
                # Need slightly more candles to find pivots (limit=100)
                ohlcv = await exchange.fetch_ohlcv(symbol, timeframe='1h', limit=100)
                if not ohlcv: continue
                df = pd.DataFrame(ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'vol'])
                result = analyze_market(df, symbol, "CRYPTO")
                if result: signals.append(result)
            except: continue
    except: pass
    finally: await exchange.close()
    return signals

async def scan_forex():
    if not OANDA_TOKEN: return []
    signals = []
    headers = {"Authorization": f"Bearer {OANDA_TOKEN}"}
    async with aiohttp.ClientSession() as session:
        for pair in FOREX_PAIRS:
            if not pair: continue
            url = f"https://api-fxtrade.oanda.com/v3/instruments/{pair}/candles?count=100&granularity=H1"
            try:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        parsed = []
                        for c in data.get('candles', []):
                            if c['complete']:
                                parsed.append({
                                    "close": float(c['mid']['c']),
                                    "high": float(c['mid']['h']),
                                    "low": float(c['mid']['l']),
                                    "open": float(c['mid']['o'])
                                })
                        if parsed:
                            df = pd.DataFrame(parsed)
                            result = analyze_market(df, pair.replace("_", "/"), "FOREX")
                            if result: signals.append(result)
            except: continue
    return signals

async def scan_stocks():
    if not FMP_KEY: return []
    signals = []
    async with aiohttp.ClientSession() as session:
        for ticker in STOCK_TICKERS:
            if not ticker: continue
            url = f"https://financialmodelingprep.com/api/v3/historical-chart/1hour/{ticker}?apikey={FMP_KEY}"
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data:
                            df = pd.DataFrame(data).iloc[::-1] # Reverse to get oldest first
                            result = analyze_market(df, ticker, "STOCK")
                            if result: signals.append(result)
            except: continue
    return signals
