import os
import asyncio
import ccxt.async_support as ccxt
import pandas as pd
import pandas_ta_classic as ta # <--- FIXED IMPORT NAME
import aiohttp
import json
import data_logger # <--- NEW IMPORT

# --- CONFIG ---
CRYPTO_PAIRS = os.getenv("CRYPTO_PAIRS", "BTC/USDT,ETH/USDT").split(",")
STOCK_TICKERS = os.getenv("STOCK_TICKERS", "NVDA,TSLA").split(",")
FOREX_PAIRS = os.getenv("FOREX_PAIRS", "EUR_USD").split(",")

OANDA_TOKEN = os.getenv("OANDA_TOKEN")
OANDA_ID = os.getenv("OANDA_ID")
FMP_KEY = os.getenv("FMP_KEY")

# --- SMART LOGIC (THE "BRAIN") ---
def analyze_market(df, symbol, asset_type):
    """
    Applies Technical Logic to find setups.
    Returns: (Signal_Type, Confidence, Price) or None
    """
    if df is None or df.empty: return None

    # 1. Calculate Indicators
    df.ta.rsi(length=14, append=True)
    df.ta.ema(length=50, append=True)
    df.ta.ema(length=200, append=True)
    
    # --- NEW: LOG DATA FOR AI TRAINING ---
    # We save the data BEFORE filtering for signals, so the AI learns 
    # from both "boring" markets and "exciting" markets.
    try:
        data_logger.log_market_snapshot(symbol, df, asset_type)
    except Exception as e:
        print(f"Logging failed: {e}")
    # -------------------------------------

    # Get the latest candle
    current = df.iloc[-1]
    
    # 2. THE LOGIC (Trend + Momentum)
    signal = None
    confidence = "Low"
    
    rsi_val = current.get('RSI_14')
    ema_50 = current.get('EMA_50')
    ema_200 = current.get('EMA_200')
    price = current['close']
    
    if rsi_val is None or ema_200 is None: return None

    if price > ema_200 and rsi_val < 35:
        signal = "🟢 BUY"
        confidence = "High" if price > ema_50 else "Medium"
    
    elif price < ema_200 and rsi_val > 65:
        signal = "🔴 SELL"
        confidence = "High" if price < ema_50 else "Medium"

    if signal:
        return {
            "symbol": symbol,
            "signal": signal,
            "price": price,
            "confidence": confidence,
            "rsi": rsi_val,
            "type": asset_type
        }
    return None
# --- 1. CRYPTO ENGINE ---
async def scan_crypto():
    exchange = ccxt.binanceus({'enableRateLimit': True})
    signals = []
    
    try:
        for symbol in CRYPTO_PAIRS:
            if not symbol: continue
            try:
                ohlcv = await exchange.fetch_ohlcv(symbol, timeframe='1h', limit=250)
                if not ohlcv: continue
                
                df = pd.DataFrame(ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'vol'])
                result = analyze_market(df, symbol, "CRYPTO")
                if result:
                    signals.append(result)
            except Exception as e:
                print(f"Skipping {symbol}: {e}")
                continue
    except Exception as e:
        print(f"Crypto Scan Error: {e}")
    finally:
        await exchange.close()
    
    return signals

# --- 2. FOREX ENGINE (OANDA) ---
async def scan_forex():
    if not OANDA_TOKEN: return []
    
    signals = []
    headers = {"Authorization": f"Bearer {OANDA_TOKEN}"}
    
    async with aiohttp.ClientSession() as session:
        for pair in FOREX_PAIRS:
            if not pair: continue
            # LIVE SERVER URL
            url = f"https://api-fxtrade.oanda.com/v3/instruments/{pair}/candles?count=250&granularity=H1"
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    candles = data.get('candles', [])
                    
                    parsed = []
                    for c in candles:
                        if c['complete']:
                            parsed.append({
                                "close": float(c['mid']['c']),
                                "high": float(c['mid']['h']),
                                "low": float(c['mid']['l']),
                                "open": float(c['mid']['o'])
                            })
                    if not parsed: continue
                    df = pd.DataFrame(parsed)
                    
                    result = analyze_market(df, pair.replace("_", "/"), "FOREX")
                    if result:
                        signals.append(result)
    return signals

# --- 3. STOCK ENGINE (FMP) ---
async def scan_stocks():
    if not FMP_KEY: return []
    
    signals = []
    async with aiohttp.ClientSession() as session:
        for ticker in STOCK_TICKERS:
            if not ticker: continue
            url = f"https://financialmodelingprep.com/api/v3/historical-chart/1hour/{ticker}?apikey={FMP_KEY}"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if not data: continue
                    
                    # FMP returns data newest first, need to reverse it for Logic
                    df = pd.DataFrame(data).iloc[::-1] 
                    result = analyze_market(df, ticker, "STOCK")
                    if result:
                        signals.append(result)
    return signals
