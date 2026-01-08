import os
import asyncio
import ccxt.async_support as ccxt
import pandas as pd
import pandas_ta_classic as ta 
import aiohttp
import joblib
import numpy as np
from datetime import datetime
import data_logger 
import market_intel 

# --- CONFIG ---
CRYPTO_PAIRS = os.getenv("CRYPTO_PAIRS", "BTC/USDT,ETH/USDT,SOL/USDT").split(",")
STOCK_TICKERS = os.getenv("STOCK_TICKERS", "NVDA,TSLA").split(",")
FOREX_PAIRS = os.getenv("FOREX_PAIRS", "EUR_USD,AUD_CAD,GBP_JPY,CHF_JPY").split(",")

OANDA_TOKEN = os.getenv("OANDA_TOKEN")
FMP_KEY = os.getenv("FMP_KEY")
BRAIN_FILE = "/app/data/jcf_brain.joblib"

# --- HELPER: TIME & SESSIONS ---
def is_forex_session_active():
    current_hour = datetime.utcnow().hour
    if 7 <= current_hour <= 21: return True
    return False

# --- BRAIN 0: THE AI JUDGE (UPDATED: MORE PERMISSIVE) ---
def ask_ai_judge(df):
    """
    Feeds the current market data into the trained Random Forest.
    Returns: True (APPROVED) or False (DENIED).
    """
    try:
        # 1. Load Brain
        if not os.path.exists(BRAIN_FILE): return True # No brain yet? Allow trade.
        model = joblib.load(BRAIN_FILE)
        
        # 2. Re-create the EXACT features from training
        calc_df = df.copy()
        
        # RSI Trend
        calc_df['rsi'] = ta.rsi(calc_df['close'], length=14)
        calc_df['rsi_trend'] = calc_df['rsi'] - calc_df['rsi'].shift(1)
        
        # Dist EMA
        calc_df['ema_50'] = ta.ema(calc_df['close'], length=50)
        calc_df['ema_200'] = ta.ema(calc_df['close'], length=200)
        
        calc_df['dist_ema200'] = (calc_df['close'] - calc_df['ema_200']) / calc_df['ema_200'].replace(0, np.nan)
        calc_df['dist_ema50'] = (calc_df['close'] - calc_df['ema_50']) / calc_df['ema_50'].replace(0, np.nan)
        
        # Prepare Input Row (Last closed candle)
        curr = calc_df.iloc[-1]
        
        # Feature Array
        features = np.array([[
            curr['rsi'], 
            curr['rsi_trend'], 
            curr['dist_ema200'], 
            curr['dist_ema50'], 
            curr['close']
        ]])
        
        # Clean Infinite values
        features = np.nan_to_num(features)
        
        # 3. GET VERDICT (Using Probability to loosen standards)
        try:
            # Ask for probability (0.0 to 1.0)
            probs = model.predict_proba(features)
            win_prob = probs[0][1] # Probability of "Win" class
            
            # Print for debugging
            print(f"🧠 AI Analysis for last candle: Confidence {win_prob:.2f}")

            # THRESHOLD: If > 45% confident, take it.
            if win_prob > 0.45:
                return True
            else:
                return False
        except:
            # Fallback if model doesn't support probability
            prediction = model.predict(features)
            return prediction[0] == 1 
        
    except Exception as e:
        print(f"🧠 AI Glitch: {e}")
        return True # Fail open (allow trade if AI breaks)

# --- BRAIN 1: THE SQUEEZE ---
def check_squeeze(df):
    df.ta.bbands(length=20, std=2, append=True)
    df.ta.kc(length=20, scalar=1.5, append=True)
    curr = df.iloc[-1]
    bb_upper = curr.get('BBU_20_2.0')
    bb_lower = curr.get('BBL_20_2.0')
    kc_upper = curr.get('KCUe_20_1.5')
    kc_lower = curr.get('KCLe_20_1.5')
    
    if not all([bb_upper, bb_lower, kc_upper, kc_lower]): return "OFF"
    
    if bb_upper < kc_upper and bb_lower > kc_lower: return "ON" 
    
    prev = df.iloc[-2]
    if prev.get('BBU_20_2.0') < prev.get('KCUe_20_1.5'): return "FIRED"
    return "OFF"

# --- BRAIN 2: DIVERGENCE ---
def check_divergence(df):
    lows = df['low']
    highs = df['high']
    is_low_pivot = (lows < lows.shift(1)) & (lows < lows.shift(-1))
    is_high_pivot = (highs > highs.shift(1)) & (highs > highs.shift(-1))
    
    low_pivots = df[is_low_pivot].tail(2)
    high_pivots = df[is_high_pivot].tail(2)
    
    if len(low_pivots) < 2 or len(high_pivots) < 2: return None

    if low_pivots['low'].iloc[1] < low_pivots['low'].iloc[0] and \
       low_pivots['RSI_14'].iloc[1] > low_pivots['RSI_14'].iloc[0]:
        if (df.index[-1] - low_pivots.index[-1]).total_seconds() / 60 < 300: 
             return "BULLISH_DIV"

    if high_pivots['high'].iloc[1] > high_pivots['high'].iloc[0] and \
       high_pivots['RSI_14'].iloc[1] < high_pivots['RSI_14'].iloc[0]:
         return "BEARISH_DIV"
    return None

# --- BRAIN 3: SWING ANALYZER (AI CONNECTED) ---
def analyze_swing(df_1h, df_4h, symbol, asset_type):
    if df_1h is None or df_4h is None: return None

    if 'time' in df_1h.columns:
        if not pd.api.types.is_datetime64_any_dtype(df_1h['time']):
             df_1h['time'] = pd.to_datetime(df_1h['time'], unit='ms')
        df_1h.set_index('time', inplace=True)

    df_1h.ta.rsi(length=14, append=True)
    df_1h.ta.ema(length=200, append=True)
    df_1h.ta.atr(length=14, append=True)
    try: df_1h.ta.vwap(append=True)
    except: pass
    
    try: data_logger.log_market_snapshot(symbol, df_1h, asset_type)
    except: pass

    squeeze_status = check_squeeze(df_1h)
    if squeeze_status == "ON": return None

    df_4h.ta.ema(length=50, append=True)
    curr_4h = df_4h.iloc[-1]
    big_trend = "BULLISH" if curr_4h['close'] > curr_4h.get('EMA_50', 0) else "BEARISH"
    divergence = check_divergence(df_1h)

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
    
    # --- SIGNAL GENERATION ---
    if price > ema200 and price > vwap:
        if squeeze_status == "FIRED":
            signal = "🟢 SWING BUY"
            confidence = "🚀 SQUEEZE FIRE"
        elif divergence == "BULLISH_DIV":
            signal = "🟢 SWING BUY"
            confidence = "💎 DIAMOND (Div)"
        elif rsi < 35 and big_trend == "BULLISH":
            signal = "🟢 SWING BUY"
            confidence = "Standard"

    elif price < ema200 and price < vwap:
        if squeeze_status == "FIRED":
            signal = "🔴 SWING SELL"
            confidence = "🚀 SQUEEZE FIRE"
        elif divergence == "BEARISH_DIV":
            signal = "🔴 SWING SELL"
            confidence = "💎 DIAMOND (Div)"
        elif rsi > 65 and big_trend == "BEARISH":
            signal = "🔴 SWING SELL"
            confidence = "Standard"

    # --- BRAIN 4: THE AI GATEKEEPER ---
    if signal:
        # ASK THE AI
        ai_approval = ask_ai_judge(df_1h)
        
        if ai_approval:
            # AI Says YES
            sl_dist = atr * 2.0
            tp_dist = atr * 3.0
            return {
                "symbol": symbol, "signal": signal, "price": price,
                "stop_loss": price - sl_dist if "BUY" in signal else price + sl_dist,
                "take_profit": price + tp_dist if "BUY" in signal else price - tp_dist,
                "confidence": f"{confidence} + 🧠 AI Confirmed", 
                "rsi": rsi, "type": asset_type, "style": "SWING"
            }
        else:
            print(f"🤖 AI VETOED signal for {symbol}.")
            return None

    return None

# --- BRAIN 5: SCALP ANALYZER (AI CONNECTED) ---
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
    
    if rsi < 30 and price <= lower_band and price > vwap:
        signal = "⚡ SCALP BUY"
    elif rsi > 70 and price >= upper_band and price < vwap:
        signal = "⚡ SCALP SELL"
        
    if signal:
        # ASK THE AI
        ai_approval = ask_ai_judge(df_15m)
        
        if ai_approval:
            target_pct = 0.005 
            stop_pct = 0.003  
            sl = price * (1 - stop_pct) if "BUY" in signal else price * (1 + stop_pct)
            tp = price * (1 + target_pct) if "BUY" in signal else price * (1 - target_pct)
            return {
                "symbol": symbol, "signal": signal, "price": price,
                "stop_loss": sl, "take_profit": tp,
                "confidence": "Scalp + 🧠 AI", "rsi": rsi, "type": asset_type, "style": "SCALP"
            }
        else:
            print(f"🤖 AI VETOED Scalp for {symbol}.")
            return None
            
    return None

# --- SCANNERS ---
async def scan_crypto():
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

async def scan_forex():
    is_safe = await market_intel.is_market_safe_from_news()
    if not is_safe: return []
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

async def scan_stocks():
    is_safe = await market_intel.is_market_safe_from_news()
    if not is_safe: return []
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
