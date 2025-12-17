import os
import asyncio
import ccxt.async_support as ccxt
import pandas as pd
import pandas_ta_classic as ta 
import aiohttp
from datetime import datetime
import data_logger 
import market_intel # Import the new intel module

# --- CONFIG ---
CRYPTO_PAIRS = os.getenv("CRYPTO_PAIRS", "BTC/USDT,ETH/USDT").split(",")
STOCK_TICKERS = os.getenv("STOCK_TICKERS", "NVDA,TSLA").split(",")
FOREX_PAIRS = os.getenv("FOREX_PAIRS", "EUR_USD").split(",")

OANDA_TOKEN = os.getenv("OANDA_TOKEN")
FMP_KEY = os.getenv("FMP_KEY")

# --- HELPER: TIME & SESSIONS ---
def is_forex_session_active():
    current_hour = datetime.utcnow().hour
    if 7 <= current_hour <= 21:
        return True
    return False

# --- BRAIN 1: MARKET STRUCTURE & TREND ---
def get_structure_and_trend(df_1h, df_4h):
    # 1. Big Brother Check (4H Trend)
    df_4h.ta.ema(length=50, append=True)
    current_4h = df_4h.iloc[-1]
    
    # 2. 1H Structure Check
    last_highs = df_1h['high'].rolling(5, center=True).max().dropna().tail(2).values
    last_lows = df_1h['low'].rolling(5, center=True).min().dropna().tail(2).values
    
    structure = "NEUTRAL"
    if len(last_highs) >= 2 and len(last_lows) >= 2:
        if last_highs[1] > last_highs[0] and last_lows[1] > last_lows[0]:
            structure = "BULLISH"
        elif last_highs[1] < last_highs[0] and last_lows[1] < last_lows[0]:
            structure = "BEARISH"

    big_trend = "BULLISH" if current_4h['close'] > current_4h.get('EMA_50', 0) else "BEARISH"
    return structure, big_trend

# --- BRAIN 2: SWING ANALYZER (VWAP ADDED) ---
def analyze_swing(df_1h, df_4h, symbol, asset_type):
    if df_1h is None or df_4h is None: return None

    # VWAP requires a datetime index
    if 'time' in df_1h.columns:
        # Convert timestamp to datetime if not already
        if not pd.api.types.is_datetime64_any_dtype(df_1h['time']):
             df_1h['time'] = pd.to_datetime(df_1h['time'], unit='ms')
        df_1h.set_index('time', inplace=True)

    # Indicators
    df_1h.ta.rsi(length=14, append=True)
    df_1h.ta.ema(length=200, append=True)
    df_1h.ta.atr(length=14, append=True)
    
    # --- NEW: VWAP ---
    # Calculates Volume Weighted Average Price
    try:
        df_1h.ta.vwap(append=True)
    except: 
        # Fallback if VWAP fails (e.g. not enough data)
        pass

    # Log Data for AI (Fix included)
    try:
        data_logger.log_market_snapshot(symbol, df_1h, asset_type)
    except: pass

    # Get "Big Brother" confirmation
    structure_1h, trend_4h = get_structure_and_trend(df_1h, df_4h)
    
    current = df_1h.iloc[-1]
    rsi = current.get('RSI_14')
    ema200 = current.get('EMA_200')
    vwap = current.get('VWAP_D') # Pandas TA usually names it VWAP_D
    price = current['close']
    atr = current.get('ATRr_14')
    
    if not all([rsi, ema200, atr]): return None
    
    # If VWAP failed to calculate, assume neutral (don't crash)
    if vwap is None: vwap = price 

    signal = None
    confidence = "Medium"
    
    # SWING BUY LOGIC:
    # 1. Price > EMA200 (Uptrend)
    # 2. RSI < 40 (Dip)
    # 3. Structure = BULLISH
    # 4. NEW: Price > VWAP (Volume supports the move)
    if price > ema200 and rsi < 40 and structure_1h == "BULLISH":
        if trend_4h == "BULLISH" and price > vwap:
            signal = "🟢 SWING BUY"
            confidence = "High (VWAP Confirmed)"
        elif trend_4h == "BULLISH":
            # If below VWAP, it's risky. Maybe skip or take with lower confidence?
            # For now, let's SKIP to fix your -31% drawdown.
            return None 
    
    # SWING SELL LOGIC
    elif price < ema200 and rsi > 60 and structure_1h == "BEARISH":
        if trend_4h == "BEARISH" and price < vwap:
            signal = "🔴 SWING SELL"
            confidence = "High (VWAP Confirmed)"
        elif trend_4h == "BEARISH":
            return None

    if signal:
        sl_dist = atr * 2.0
        tp_dist = atr * 3.0
        
        return {
            "symbol": symbol, "signal": signal, "price": price,
            "stop_loss": price - sl_dist if "BUY" in signal else price + sl_dist,
            "take_profit": price + tp_dist if "BUY" in signal else price - tp_dist,
            "confidence": confidence, "rsi": rsi, "type": asset_type, "style": "SWING"
        }
    return None

# --- BRAIN 3: SCALP ANALYZER (VWAP ADDED) ---
def analyze_scalp(df_15m, symbol, asset_type):
    if df_15m is None: return None
    
    if 'time' in df_15m.columns:
        if not pd.api.types.is_datetime64_any_dtype(df_15m['time']):
             df_15m['time'] = pd.to_datetime(df_15m['time'], unit='ms')
        df_15m.set_index('time', inplace=True)
    
    # Indicators
    df_15m.ta.rsi(length=14, append=True)
    df_15m.ta.bbands(length=20, std=2, append=True)
    try:
        df_15m.ta.vwap(append=True)
    except: pass
    
    # Log 15m data
    try:
        data_logger.log_market_snapshot(f"{symbol}_SCALP", df_15m, asset_type)
    except: pass
    
    current = df_15m.iloc[-1]
    rsi = current.get('RSI_14')
    price = current['close']
    upper_band = current.get('BBU_20_2.0')
    lower_band = current.get('BBL_20_2.0')
    vwap = current.get('VWAP_D')
    
    if not all([rsi, upper_band, lower_band]): return None
    if vwap is None: vwap = price
    
    signal = None
    
    # SCALP BUY: RSI Oversold + Touched Lower Band + Price ABOVE VWAP (Trend Scalp)
    # We add VWAP check here to avoid catching falling knives even on scalps
    if rsi < 30 and price <= lower_band:
        # Only take long scalps if we are continuously above VWAP (Strong Intraday Trend)
        if price > vwap: 
            signal = "⚡ SCALP BUY"
        
    # SCALP SELL
    elif rsi > 70 and price >= upper_band:
        if price < vwap:
            signal = "⚡ SCALP SELL"
        
    if signal:
        target_pct = 0.005 # 0.5%
        stop_pct = 0.003   # 0.3%
        
        sl = price * (1 - stop_pct) if "BUY" in signal else price * (1 + stop_pct)
        tp = price * (1 + target_pct) if "BUY" in signal else price * (1 - target_pct)
        
        return {
            "symbol": symbol, "signal": signal, "price": price,
            "stop_loss": sl, "take_profit": tp,
            "confidence": "Scalp", "rsi": rsi, "type": asset_type, "style": "SCALP"
        }
    return None

# --- SCANNER: CRYPTO ---
async def scan_crypto():
    exchange = ccxt.binanceus({'enableRateLimit': True})
    signals = []
    try:
        for symbol in CRYPTO_PAIRS:
            if not symbol: continue
            try:
                ohlcv_1h = await exchange.fetch_ohlcv(symbol, timeframe='1h', limit=100)
                ohlcv_4h = await exchange.fetch_ohlcv(symbol, timeframe='4h', limit=50)
                ohlcv_15m = await exchange.fetch_ohlcv(symbol, timeframe='15m', limit=50)
                
                if not ohlcv_1h or not ohlcv_4h: continue
                
                df_1h = pd.DataFrame(ohlcv_1h, columns=['time','open','high','low','close','vol'])
                df_4h = pd.DataFrame(ohlcv_4h, columns=['time','open','high','low','close','vol'])
                df_15m = pd.DataFrame(ohlcv_15m, columns=['time','open','high','low','close','vol'])
                
                swing_sig = analyze_swing(df_1h, df_4h, symbol, "CRYPTO")
                if swing_sig: signals.append(swing_sig)
                
                scalp_sig = analyze_scalp(df_15m, symbol, "CRYPTO")
                if scalp_sig: signals.append(scalp_sig)
                
            except: continue
    except: pass
    finally: await exchange.close()
    return signals

# --- SCANNER: FOREX ---
async def scan_forex():
    if not OANDA_TOKEN: return []
    signals = []
    headers = {"Authorization": f"Bearer {OANDA_TOKEN}"}
    session = aiohttp.ClientSession()
    active_session = is_forex_session_active() 
    
    for pair in FOREX_PAIRS:
        if not pair: continue
        clean_pair = pair.replace("/", "_")
        url_1h = f"https://api-fxtrade.oanda.com/v3/instruments/{clean_pair}/candles?count=100&granularity=H1"
        url_4h = f"https://api-fxtrade.oanda.com/v3/instruments/{clean_pair}/candles?count=50&granularity=H4"
        url_15m = f"https://api-fxtrade.oanda.com/v3/instruments/{clean_pair}/candles?count=50&granularity=M15"
        
        try:
            async def get_oanda_df(url):
                async with session.get(url, headers=headers) as r:
                    if r.status == 200:
                        d = await r.json()
                        p = [{"close": float(c['mid']['c']), "high": float(c['mid']['h']), "low": float(c['mid']['l']), "open": float(c['mid']['o']), "vol": float(c['volume']), "time": c['time']} for c in d.get('candles', []) if c['complete']]
                        if not p: return None
                        df = pd.DataFrame(p)
                        # OANDA Time string fix
                        df['time'] = pd.to_datetime(df['time'])
                        return df
                    return None

            df_1h = await get_oanda_df(url_1h)
            df_4h = await get_oanda_df(url_4h)
            df_15m = await get_oanda_df(url_15m)

            if active_session or "JPY" in pair: 
                swing_sig = analyze_swing(df_1h, df_4h, pair.replace("_", "/"), "FOREX")
                if swing_sig: signals.append(swing_sig)
            
            scalp_sig = analyze_scalp(df_15m, pair.replace("_", "/"), "FOREX")
            if scalp_sig: signals.append(scalp_sig)

        except: continue
    await session.close()
    return signals

# --- SCANNER: STOCKS ---
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
                            df = pd.DataFrame(data).iloc[::-1]
                            # FMP uses 'date' usually, map to 'time' for consistency
                            df.rename(columns={'date': 'time'}, inplace=True)
                            
                            # Log Data
                            try: data_logger.log_market_snapshot(ticker, df, "STOCK")
                            except: pass
                            
                            swing_sig = analyze_swing(df, df, ticker, "STOCK")
                            if swing_sig: signals.append(swing_sig)
            except: continue
    return signals
