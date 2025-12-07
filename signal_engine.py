import os
import asyncio
import ccxt.async_support as ccxt
import pandas as pd
import pandas_ta as ta
import aiohttp
import json

# --- CONFIG ---
CRYPTO_PAIRS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"]
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
    df['RSI'] = df.ta.rsi(length=14)
    df['EMA_50'] = df.ta.ema(length=50)
    df['EMA_200'] = df.ta.ema(length=200)
    
    # Get the latest candle
    current = df.iloc[-1]
    prev = df.iloc[-2]

    # 2. THE LOGIC (Trend + Momentum)
    signal = None
    confidence = "Low"

    # BUY LOGIC: Price > EMA 200 (Uptrend) AND RSI < 30 (Oversold)
    if current['close'] > current['EMA_200'] and current['RSI'] < 35:
        signal = "🟢 BUY"
        confidence = "High" if current['close'] > current['EMA_50'] else "Medium"
    
    # SELL LOGIC: Price < EMA 200 (Downtrend) AND RSI > 70 (Overbought)
    elif current['close'] < current['EMA_200'] and current['RSI'] > 65:
        signal = "🔴 SELL"
        confidence = "High" if current['close'] < current['EMA_50'] else "Medium"

    if signal:
        return {
            "symbol": symbol,
            "signal": signal,
            "price": current['close'],
            "confidence": confidence,
            "rsi": current['RSI'],
            "type": asset_type
        }
    return None

# --- 1. CRYPTO ENGINE ---
async def scan_crypto():
    exchange = ccxt.binanceus({'enableRateLimit': True})
    signals = []
    
    try:
        for symbol in CRYPTO_PAIRS:
            ohlcv = await exchange.fetch_ohlcv(symbol, timeframe='1h', limit=250)
            df = pd.DataFrame(ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'vol'])
            result = analyze_market(df, symbol, "CRYPTO")
            if result:
                signals.append(result)
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
            url = f"https://api-fxpractice.oanda.com/v3/instruments/{pair}/candles?count=250&granularity=H1"
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    candles = data.get('candles', [])
                    
                    # Parse OANDA data to DataFrame
                    parsed = []
                    for c in candles:
                        parsed.append({
                            "close": float(c['mid']['c']),
                            "high": float(c['mid']['h']),
                            "low": float(c['mid']['l'])
                        })
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
