import os
import asyncio
import ccxt.async_support as ccxt
import pandas as pd
import pandas_ta_classic as ta 
import aiohttp
from datetime import datetime
import data_logger 
import market_intel 

# --- CONFIG ---
CRYPTO_PAIRS = os.getenv("CRYPTO_PAIRS", "BTC/USDT,ETH/USDT").split(",")
STOCK_TICKERS = os.getenv("STOCK_TICKERS", "NVDA,TSLA").split(",")
FOREX_PAIRS = os.getenv("FOREX_PAIRS", "EUR_USD").split(",")

OANDA_TOKEN = os.getenv("OANDA_TOKEN")
FMP_KEY = os.getenv("FMP_KEY")

# --- HELPER: TIME & SESSIONS ---
def is_forex_session_active():
    """
    Returns True if we are in London or NY Session (07:00 - 21:00 UTC).
    """
    current_hour = datetime.utcnow().hour
    if 7 <= current_hour <= 21:
        return True
    return False

# --- BRAIN 1: DIVERGENCE DETECTOR (THE ALPHA) ---
def check_divergence(df):
    """
    Detects Regular Bullish/Bearish Divergence.
    Returns: "BULLISH_DIV", "BEARISH_DIV", or None
    """
    # We use a rolling window to find local extremas
    lows = df['low']
    highs = df['high']
    
    # Identify Low Pivots (Valleys)
    is_low_pivot = (lows < lows.shift(1)) & (lows < lows.shift(-1))
    
    # Identify High Pivots (Peaks)
    is_high_pivot = (highs > highs.shift(1)) & (highs > highs.shift(-1))
    
    # Get the last 2 pivots
    low_pivots = df[is_low_pivot].tail(2)
    high_pivots = df[is_high_pivot].tail(2)
    
    if len(low_pivots) < 2 or len(high_pivots) < 2:
        return None

    # --- BULLISH DIVERGENCE LOGIC ---
    # Price Lower Low + RSI Higher Low
    p_low_1 = low_pivots['low'].iloc[0]
    p_low_2 = low_pivots['low'].iloc[1]
    r_low_1 = low_pivots['RSI_14'].iloc[0]
    r_low_2 = low_pivots['RSI_14'].iloc[1]

    if p_low_2 < p_low_1 and r_low_2 > r_low_1:
        # Filter: Divergence must be recent (within last 5 candles approx)
        if (df.index[-1] - low_pivots.index[-1]).total_seconds() / 60 < 300: 
             return "BULLISH_DIV"

    # --- BEARISH DIVERGENCE LOGIC ---
    # Price Higher High + RSI Lower High
    p_high_1 = high_pivots['high'].iloc[0]
    p_high_2 = high_pivots['high'].iloc[1]
    r_high_1 = high_pivots['RSI_14'].iloc[0]
    r_high_2 = high_pivots['RSI_14'].iloc[1]

    if p_high_2 > p_high_1 and r_high_2 < r_high_1:
         return "BEARISH_DIV"
         
    return None

# --- BRAIN 2: SWING ANALYZER (PRO VERSION) ---
def analyze_swing(df_1h, df_4h, symbol, asset_type):
    if df_1h is None or df_4h is None: return None

    # Time Index Fix for VWAP/Divergence
    if 'time' in df_1h.columns:
        if not pd.api.types.is_datetime64_any_dtype(df_1h['time']):
             df_1h['time'] = pd.to_datetime(df_1h['time'], unit='ms')
        df_1h.set_index('time', inplace=True)

    # Indicators
    df_1h.ta.rsi(length=14, append=True)
    df_1h.ta.ema(length=200, append=True)
    df_1h.ta.atr(length=14, append=True)
    try: df_1h.ta.vwap(append=True)
    except: pass
    
    # Log Data for AI
    try: data_logger.log_market_snapshot(symbol, df_1h, asset_type)
    except: pass

    # Get "Big Brother" Trend (4H)
    df_4h.ta.ema(length=50, append=True)
    curr_4h = df_4h.iloc[-1]
    big_trend = "BULLISH" if curr_4h['close'] > curr_4h.get('EMA_50', 0) else "BEARISH"
    
    # Check Divergence (The Alpha)
    divergence = check_divergence(df_1h) # Returns "BULLISH_DIV" or "BEARISH_DIV"

    current = df_1h.iloc[-1]
    rsi = current.get('RSI_14')
    ema200 = current.get('EMA_200')
    vwap = current.get('VWAP_D')
    price = current['close']
    atr = current.get('ATRr_14')
    
    if not all([rsi, ema200, atr]): return None
    if vwap is None: vwap = price 

    signal = None
    confidence = "Medium"
    
    # --- SWING BUY LOGIC ---
    # 1. Trend: Price > EMA200 (Uptrend)
    # 2. Safety: Price > VWAP
    # 3. TRIGGER: Bullish Divergence OR (RSI Oversold + 4H Trend)
    if price > ema200 and price > vwap:
        if divergence == "BULLISH_DIV":
            signal = "🟢 SWING BUY"
            confidence = "💎 DIAMOND (Divergence)"
        elif rsi < 35 and big_trend == "BULLISH": # Standard Setup
            signal = "🟢 SWING BUY"
            confidence = "Standard"

    # --- SWING SELL LOGIC ---
    elif price < ema200 and price < vwap:
        if divergence == "BEARISH_DIV":
            signal = "🔴 SWING SELL"
            confidence = "💎 DIAMOND (Divergence)"
        elif rsi > 65 and big_trend == "BEARISH":
            signal = "🔴 SWING SELL"
            confidence = "Standard"

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

# --- BRAIN 3: SCALP ANALYZER ---
def analyze_scalp(df_15m, symbol, asset_type):
    if df_15m is None: return None
    
    if 'time' in df_15m.columns:
        if not pd.api.types.is_datetime64_any_dtype(df_15m['time']):
             df_15m['time'] = pd.to_datetime(df_15m['time'], unit='ms')
        df_15m.set_index('time', inplace=True)
    
    df_15m.ta.rsi(length=14, append=True)
    df_15m.ta.bbands(length=20, std=2, append=True)
    try: df_15m.ta.vwap(append=True)
    except: pass
    
    # Log 15m Data
    try: data_logger.log_market_snapshot(f"{symbol}_SCALP", df_15m, asset_type)
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
    
    # SCALPS (Momentum Snapshots with VWAP Trend)
    if rsi < 30 and price <= lower_band and price > vwap:
        signal = "⚡ SCALP BUY"
    elif rsi > 70 and price >= upper_band and price < vwap:
        signal = "⚡ SCALP SELL"
        
    if signal:
        target_pct = 0.005 
        stop_pct = 0.003  
        sl = price * (1 - stop_pct) if "BUY" in signal else price * (1 + stop_pct)
        tp = price * (1 + target_pct) if "BUY" in signal else price * (1 - target_pct)
        return {
            "symbol": symbol, "signal": signal, "price": price,
            "stop_loss": sl, "take_profit": tp,
            "confidence": "Scalp", "rsi": rsi, "type": asset_type, "style": "SCALP"
        }
    return None

# --- SCANNER: CRYPTO (WITH NEWS SHIELD) ---
async def scan_crypto():
    # 1. NEWS SHIELD
    is_safe = await market_intel.is_market_safe_from_news()
    if not is_safe:
        print("⚠️ SKIPPING SCAN: High Impact News Event Detected.")
        return [] 
        
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

# --- SCANNER: FOREX (WITH NEWS SHIELD) ---
async def scan_forex():
    # 1. NEWS SHIELD
    is_safe = await market_intel.is_market_safe_from_news()
    if not is_safe:
        print("⚠️ SKIPPING SCAN: High Impact News Event Detected.")
        return []

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

# --- SCANNER: STOCKS (WITH NEWS SHIELD) ---
async def scan_stocks():
    # 1. NEWS SHIELD
    is_safe = await market_intel.is_market_safe_from_news()
    if not is_safe:
        print("⚠️ SKIPPING SCAN: High Impact News Event Detected.")
        return []

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
                            df.rename(columns={'date': 'time'}, inplace=True)
                            
                            try: data_logger.log_market_snapshot(ticker, df, "STOCK")
                            except: pass
                            
                            swing_sig = analyze_swing(df, df, ticker, "STOCK")
                            if swing_sig: signals.append(swing_sig)
            except: continue
    return signals
