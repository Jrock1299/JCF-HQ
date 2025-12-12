import os
import asyncio
import ccxt.async_support as ccxt
import pandas as pd
import pandas_ta_classic as ta 
import aiohttp
from datetime import datetime
import data_logger 

# --- CONFIG ---
CRYPTO_PAIRS = os.getenv("CRYPTO_PAIRS", "BTC/USDT,ETH/USDT").split(",")
STOCK_TICKERS = os.getenv("STOCK_TICKERS", "NVDA,TSLA").split(",")
FOREX_PAIRS = os.getenv("FOREX_PAIRS", "EUR_USD").split(",")

OANDA_TOKEN = os.getenv("OANDA_TOKEN")
OANDA_ID = os.getenv("OANDA_ID")
FMP_KEY = os.getenv("FMP_KEY")

# --- HELPER: TIME & SESSIONS ---
def is_forex_session_active():
    """
    Returns True if we are in London or NY Session.
    Helps avoid choppy Asian session for EUR/GBP pairs.
    (Simple check: 07:00 UTC to 21:00 UTC)
    """
    current_hour = datetime.utcnow().hour
    # Adjust these hours based on your preference
    if 7 <= current_hour <= 21:
        return True
    return False

# --- BRAIN 1: MARKET STRUCTURE & TREND ---
def get_structure_and_trend(df_1h, df_4h):
    """
    Analyzes 1H Structure and confirms with 4H Trend (Big Brother).
    """
    # 1. Big Brother Check (4H Trend)
    df_4h.ta.ema(length=50, append=True)
    current_4h = df_4h.iloc[-1]
    
    # 2. 1H Structure Check
    # (Simple Higher High/Lower Low Logic)
    last_highs = df_1h['high'].rolling(5, center=True).max().dropna().tail(2).values
    last_lows = df_1h['low'].rolling(5, center=True).min().dropna().tail(2).values
    
    structure = "NEUTRAL"
    if len(last_highs) >= 2 and len(last_lows) >= 2:
        if last_highs[1] > last_highs[0] and last_lows[1] > last_lows[0]:
            structure = "BULLISH"
        elif last_highs[1] < last_highs[0] and last_lows[1] < last_lows[0]:
            structure = "BEARISH"

    # Combine
    big_trend = "BULLISH" if current_4h['close'] > current_4h.get('EMA_50', 0) else "BEARISH"
    
    return structure, big_trend

# --- BRAIN 2: SWING ANALYZER ---
def analyze_swing(df_1h, df_4h, symbol, asset_type):
    if df_1h is None or df_4h is None: return None

    # Indicators
    df_1h.ta.rsi(length=14, append=True)
    df_1h.ta.ema(length=200, append=True)
    df_1h.ta.atr(length=14, append=True)

    # Get "Big Brother" confirmation
    structure_1h, trend_4h = get_structure_and_trend(df_1h, df_4h)
    
    current = df_1h.iloc[-1]
    rsi = current.get('RSI_14')
    ema200 = current.get('EMA_200')
    price = current['close']
    atr = current.get('ATRr_14')
    
    if not all([rsi, ema200, atr]): return None

    signal = None
    
    # BUY LOGIC: Price > EMA200 (1H) AND Bullish Structure AND 4H is Bullish
    if price > ema200 and rsi < 40 and structure_1h == "BULLISH":
        if trend_4h == "BULLISH": # The "Big Brother" Confirmation
            signal = "🟢 SWING BUY"
    
    # SELL LOGIC
    elif price < ema200 and rsi > 60 and structure_1h == "BEARISH":
        if trend_4h == "BEARISH":
            signal = "🔴 SWING SELL"

    if signal:
        # Dynamic Swing Risk (Wide Stops)
        sl_dist = atr * 2.0
        tp_dist = atr * 3.0 # Aim for big wins (1:1.5)
        
        return {
            "symbol": symbol, "signal": signal, "price": price,
            "stop_loss": price - sl_dist if "BUY" in signal else price + sl_dist,
            "take_profit": price + tp_dist if "BUY" in signal else price - tp_dist,
            "confidence": "High (Trend Aligned)", "rsi": rsi, "type": asset_type, "style": "SWING"
        }
    return None

# --- BRAIN 3: SCALP ANALYZER (5m/15m) ---
def analyze_scalp(df_15m, symbol, asset_type):
    """
    Looking for quick reversals (RSI Extreme + Bollinger Bands).
    """
    if df_15m is None: return None
    
    # Indicators
    df_15m.ta.rsi(length=14, append=True)
    df_15m.ta.bbands(length=20, std=2, append=True) # Bollinger Bands
    
    current = df_15m.iloc[-1]
    rsi = current.get('RSI_14')
    price = current['close']
    upper_band = current.get('BBU_20_2.0')
    lower_band = current.get('BBL_20_2.0')
    
    if not all([rsi, upper_band, lower_band]): return None
    
    signal = None
    
    # SCALP BUY: RSI Oversold (<30) AND Price touched Lower Band
    if rsi < 30 and price <= lower_band:
        signal = "⚡ SCALP BUY"
        
    # SCALP SELL: RSI Overbought (>70) AND Price touched Upper Band
    elif rsi > 70 and price >= upper_band:
        signal = "⚡ SCALP SELL"
        
    if signal:
        # Tight Risk for Scalps (Fixed % or small ATR)
        # Simplified for Scalps: 0.5% Target / 0.3% Stop
        target_pct = 0.005 # 0.5% move
        stop_pct = 0.003   # 0.3% stop
        
        sl = price * (1 - stop_pct) if "BUY" in signal else price * (1 + stop_pct)
        tp = price * (1 + target_pct) if "BUY" in signal else price * (1 - target_pct)
        
        return {
            "symbol": symbol, "signal": signal, "price": price,
            "stop_loss": sl, "take_profit": tp,
            "confidence": "Scalp", "rsi": rsi, "type": asset_type, "style": "SCALP"
        }
    return None

# --- SCANNER: CRYPTO (Swing + Scalp) ---
async def scan_crypto():
    exchange = ccxt.binanceus({'enableRateLimit': True})
    signals = []
    try:
        for symbol in CRYPTO_PAIRS:
            if not symbol: continue
            try:
                # Fetch 1H Data (For Swing)
                ohlcv_1h = await exchange.fetch_ohlcv(symbol, timeframe='1h', limit=100)
                # Fetch 4H Data (For Big Brother)
                ohlcv_4h = await exchange.fetch_ohlcv(symbol, timeframe='4h', limit=50)
                # Fetch 15m Data (For Scalp)
                ohlcv_15m = await exchange.fetch_ohlcv(symbol, timeframe='15m', limit=50)
                
                if not ohlcv_1h or not ohlcv_4h: continue
                
                df_1h = pd.DataFrame(ohlcv_1h, columns=['time','open','high','low','close','vol'])
                df_4h = pd.DataFrame(ohlcv_4h, columns=['time','open','high','low','close','vol'])
                df_15m = pd.DataFrame(ohlcv_15m, columns=['time','open','high','low','close','vol'])
                
                # Check Swing
                swing_sig = analyze_swing(df_1h, df_4h, symbol, "CRYPTO")
                if swing_sig: signals.append(swing_sig)
                
                # Check Scalp
                scalp_sig = analyze_scalp(df_15m, symbol, "CRYPTO")
                if scalp_sig: signals.append(scalp_sig)
                
            except: continue
    except: pass
    finally: await exchange.close()
    return signals

# --- SCANNER: FOREX (Swing + Scalp + Session) ---
async def scan_forex():
    if not OANDA_TOKEN: return []
    signals = []
    headers = {"Authorization": f"Bearer {OANDA_TOKEN}"}
    session = aiohttp.ClientSession()
    
    # Session Filter: If Asian session, maybe skip Swings or require stricter filters
    active_session = is_forex_session_active() 
    
    for pair in FOREX_PAIRS:
        if not pair: continue
        # Fetch 1H (Swing)
        url_1h = f"https://api-fxtrade.oanda.com/v3/instruments/{pair}/candles?count=100&granularity=H1"
        # Fetch 4H (Big Brother)
        url_4h = f"https://api-fxtrade.oanda.com/v3/instruments/{pair}/candles?count=50&granularity=H4"
        # Fetch 15m (Scalp)
        url_15m = f"https://api-fxtrade.oanda.com/v3/instruments/{pair}/candles?count=50&granularity=M15"
        
        try:
            # Helper to fetch
            async def get_oanda_df(url):
                async with session.get(url, headers=headers) as r:
                    if r.status == 200:
                        d = await r.json()
                        p = [{"close": float(c['mid']['c']), "high": float(c['mid']['h']), "low": float(c['mid']['l']), "open": float(c['mid']['o'])} for c in d.get('candles', []) if c['complete']]
                        return pd.DataFrame(p) if p else None
                    return None

            df_1h = await get_oanda_df(url_1h)
            df_4h = await get_oanda_df(url_4h)
            df_15m = await get_oanda_df(url_15m)

            # Check Swing (Only if Session is Active OR very strong signal)
            if active_session or "JPY" in pair: # JPY pairs move in Asian session
                swing_sig = analyze_swing(df_1h, df_4h, pair.replace("_", "/"), "FOREX")
                if swing_sig: signals.append(swing_sig)
            
            # Check Scalp (Scalps work anytime volatility exists)
            scalp_sig = analyze_scalp(df_15m, pair.replace("_", "/"), "FOREX")
            if scalp_sig: signals.append(scalp_sig)

        except: continue
        
    await session.close()
    return signals

# --- SCANNER: STOCKS (Daily/Hourly only - No Scalping yet) ---
async def scan_stocks():
    if not FMP_KEY: return []
    signals = []
    async with aiohttp.ClientSession() as session:
        for ticker in STOCK_TICKERS:
            if not ticker: continue
            # Stocks we stick to 1H swing for now
            url = f"https://financialmodelingprep.com/api/v3/historical-chart/1hour/{ticker}?apikey={FMP_KEY}"
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data:
                            df = pd.DataFrame(data).iloc[::-1]
                            # For stocks, we cheat and use 1H as big brother for now to save API calls
                            swing_sig = analyze_swing(df, df, ticker, "STOCK")
                            if swing_sig: signals.append(swing_sig)
            except: continue
    return signals
