import os
# must be before importing discord to avoid 'audioop' on Py3.13
os.environ["DISCORD_NO_AUDIO"] = "1"

import asyncio
import logging
from datetime import datetime, time as dtime
import pytz

import discord
from discord.ext import commands, tasks

import numpy as np
import pandas as pd
import yfinance as yf
import ccxt

# ---------- ENV ----------
TOKEN = os.getenv("DISCORD_TOKEN")
ANNOUNCE_CHANNEL_ID = int(os.getenv("ANNOUNCE_CHANNEL_ID", "0") or 0)

CHAN_CRYPTO = int(os.getenv("CRYPTO_SETUPS_CHANNEL_ID", "0") or 0)
CHAN_STOCKS = int(os.getenv("STOCK_SETUPS_CHANNEL_ID", "0") or 0)
CHAN_FOREX  = int(os.getenv("FOREX_SETUPS_CHANNEL_ID", "0") or 0)

RISK_CRYPTO = float(os.getenv("RISK_PCT_CRYPTO", "2"))
RISK_STOCKS = float(os.getenv("RISK_PCT_STOCKS", "1"))
RISK_FOREX  = float(os.getenv("RISK_PCT_FOREX", "1"))

def _split_env(name, default=""):
    raw = os.getenv(name, default)
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return parts

WL_CRYPTO = _split_env("CRYPTO_TICKERS")
WL_STOCKS = _split_env("STOCK_TICKERS")
WL_FOREX  = _split_env("FOREX_TICKERS")

# ---------- LOGGING ----------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("jcf-ai")

# ---------- DISCORD ----------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- HELPERS ----------
NY = pytz.timezone("America/New_York")

def now_ny():
    return datetime.now(NY)

def market_open():
    # US equity market hours (approx): 9:30–16:00 NY, Mon–Fri
    n = now_ny()
    if n.weekday() >= 5:  # Sat/Sun
        return False
    return dtime(9, 30) <= n.time() <= dtime(16, 0)

def ema(arr, n):
    return pd.Series(arr).ewm(span=n, adjust=False).mean().to_numpy()

def atr(high, low, close, n=14):
    high = pd.Series(high); low = pd.Series(low); close = pd.Series(close)
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(n).mean().to_numpy()

# basic “hybrid” logic for intraday, trend-continuation & breakout-retest
def scan_series(symbol, o, h, l, c, v, risk_pct):
    if len(c) < 200:
        return None
    e20, e50, e200 = ema(c, 20), ema(c, 50), ema(c, 200)
    last = -1
    up_trend = e20[last] > e50[last] > e200[last] and c[last] > e20[last]
    down_trend = e20[last] < e50[last] < e200[last] and c[last] < e20[last]
    a = atr(h, l, c, 14)
    if np.isnan(a[last]) or a[last] == 0:
        return None

    # Breakout detection: new 20-bar high/low
    hh = pd.Series(c).rolling(20).max().to_numpy()
    ll = pd.Series(c).rolling(20).min().to_numpy()
    signal = None

    # Long case: trend up + recent breakout with retest near EMA20 within 1.2*ATR
    if up_trend and c[last] >= hh[last] * 0.999:
        # lookback for a pullback tag to EMA20 within last 10 bars
        window = slice(-10, None)
        pullback_ok = (np.min(np.abs(pd.Series(c[window]) - e20[window])) <= 1.2 * a[last])
        if pullback_ok:
            entry = float(c[last])
            stop  = float(max(e50[last], c[last] - 1.5 * a[last]))
            target1 = float(entry + 1.0 * a[last])
            target2 = float(entry + 2.0 * a[last])
            rr = round((entry - stop) / (target1 - entry), 2) if (target1 - entry) > 0 else None
            signal = {
                "side": "LONG", "symbol": symbol,
                "entry": entry, "stop": stop,
                "t1": target1, "t2": target2, "atr": float(a[last]),
                "rr": rr, "reason": "Trend continuation + breakout-retest near EMA20"
            }

    # Short case: mirror
    if signal is None and down_trend and c[last] <= ll[last] * 1.001:
        window = slice(-10, None)
        pullback_ok = (np.min(np.abs(pd.Series(c[window]) - e20[window])) <= 1.2 * a[last])
        if pullback_ok:
            entry = float(c[last])
            stop  = float(min(e50[last], c[last] + 1.5 * a[last]))
            target1 = float(entry - 1.0 * a[last])
            target2 = float(entry - 2.0 * a[last])
            rr = round((stop - entry) / (entry - target1), 2) if (entry - target1) > 0 else None
            signal = {
                "side": "SHORT", "symbol": symbol,
                "entry": entry, "stop": stop,
                "t1": target1, "t2": target2, "atr": float(a[last]),
                "rr": rr, "reason": "Trend continuation + breakdown-retest near EMA20"
            }

    return signal

async def post_setup(channel_id: int, title: str, sig: dict, timeframe: str, risk_pct: float):
    if not channel_id:
        return
    ch = bot.get_channel(channel_id)
    if not ch:
        return
    emoji = "🚀" if sig["side"] == "LONG" else "🛑"
    msg = (
        f"**{title}** {emoji}\n"
        f"**{sig['symbol']}** · {timeframe}\n"
        f"Side: **{sig['side']}** · Reason: {sig['reason']}\n"
        f"Entry: **{sig['entry']:.4f}**  |  Stop: **{sig['stop']:.4f}**  "
        f"|  T1: **{sig['t1']:.4f}**, T2: **{sig['t2']:.4f}**\n"
        f"ATR: {sig['atr']:.4f}  |  Est. Risk: **{risk_pct}%**  |  R/R≈**{sig['rr']}**\n"
        f"_Automated intraday scan (trend-continuation & breakout-retest)._"
    )
    await ch.send(msg)

# ---------- DATA SOURCES ----------
binance = ccxt.binance({'enableRateLimit': True})

async def fetch_crypto(symbol: str, timeframe="15m", limit=220):
    # symbol like "BTC/USDT"
    ohlcv = await asyncio.to_thread(binance.fetch_ohlcv, symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=["ts","o","h","l","c","v"])
    return df

def fetch_yf(ticker: str, interval="15m", period="5d"):
    df = yf.download(tickers=ticker, interval=interval, period=period, progress=False, prepost=False)
    if df is None or df.empty:
        return None
    df = df.rename(columns=str.lower).reset_index(drop=False)
    df["v"] = df["volume"]
    df["o"], df["h"], df["l"], df["c"] = df["open"], df["high"], df["low"], df["close"]
    return df[["Datetime","o","h","l","c","v"]].rename(columns={"Datetime":"ts"})

# ---------- SCHEDULED SCANS ----------
@tasks.loop(minutes=10)
async def scan_crypto_loop():
    if not WL_CRYPTO: return
    for sym in WL_CRYPTO:
        try:
            df = await fetch_crypto(sym, timeframe="15m")
            sig = scan_series(sym, df.o, df.h, df.l, df.c, df.v, RISK_CRYPTO)
            if sig: await post_setup(CHAN_CRYPTO, "Crypto Setup", sig, "15m", RISK_CRYPTO)
            await asyncio.sleep(0.5)
        except Exception as e:
            log.warning(f"crypto scan error {sym}: {e}")

@tasks.loop(minutes=10)
async def scan_stocks_loop():
    if not WL_STOCKS or not market_open(): return
    for t in WL_STOCKS:
        try:
            df = fetch_yf(t, interval="15m", period="5d")
            if df is None or df.empty: continue
            sig = scan_series(t, df.o, df.h, df.l, df.c, df.v, RISK_STOCKS)
            if sig: await post_setup(CHAN_STOCKS, "Stock Setup", sig, "15m", RISK_STOCKS)
            await asyncio.sleep(0.5)
        except Exception as e:
            log.warning(f"stock scan error {t}: {e}")

@tasks.loop(minutes=10)
async def scan_forex_loop():
    # yfinance symbols for FX: "USDJPY=X", "XAUUSD=X", etc.
    mapping = {
        "XAUUSD":"XAUUSD=X",
        "USDJPY":"USDJPY=X",
        "EURUSD":"EURUSD=X",
        "GBPUSD":"GBPUSD=X",
        "SPX500USD":"^GSPC"  # proxy for S&P 500 cash index
    }
    for t in WL_FOREX:
        yft = mapping.get(t, f"{t}=X")
        try:
            df = fetch_yf(yft, interval="15m", period="5d")
            if df is None or df.empty: continue
            sig = scan_series(t, df.o, df.h, df.l, df.c, df.v, RISK_FOREX)
            if sig: await post_setup(CHAN_FOREX, "Forex Setup", sig, "15m", RISK_FOREX)
            await asyncio.sleep(0.5)
        except Exception as e:
            log.warning(f"forex scan error {t}: {e}")

# ---------- BOT EVENTS & COMMANDS ----------
@bot.event
async def on_ready():
    log.info(f"✅ Logged in as {bot.user} (id: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="JCF HQ scanners"))
    if ANNOUNCE_CHANNEL_ID:
        ch = bot.get_channel(ANNOUNCE_CHANNEL_ID)
        if ch:
            await ch.send("✅ **JCFWatchBot ONLINE** — AI scanners armed. (15-min cycle)")

    if not scan_crypto_loop.is_running(): scan_crypto_loop.start()
    if not scan_stocks_loop.is_running(): scan_stocks_loop.start()
    if not scan_forex_loop.is_running():  scan_forex_loop.start()

@bot.command()
async def status(ctx):
    msg = (
        f"Crypto: {'ON' if scan_crypto_loop.is_running() else 'OFF'} | "
        f"Stocks: {'ON' if scan_stocks_loop.is_running() else 'OFF'} | "
        f"Forex: {'ON' if scan_forex_loop.is_running() else 'OFF'}\n"
        f"WL Crypto: {', '.join(WL_CRYPTO) or '-'}\n"
        f"WL Stocks: {', '.join(WL_STOCKS) or '-'}\n"
        f"WL Forex: {', '.join(WL_FOREX) or '-'}"
    )
    await ctx.reply(msg)

@bot.command()
async def scan(ctx, asset_class: str = "all"):
    asset_class = asset_class.lower()
    await ctx.reply(f"Manual scan kicked off for **{asset_class}**…")
    if asset_class in ("all","crypto"): await run_manual_crypto()
    if asset_class in ("all","stocks"): await run_manual_stocks()
    if asset_class in ("all","forex"):  await run_manual_forex()
    await ctx.reply("Done ✅")

async def run_manual_crypto():
    for sym in WL_CRYPTO:
        try:
            df = await fetch_crypto(sym, "15m")
            sig = scan_series(sym, df.o, df.h, df.l, df.c, df.v, RISK_CRYPTO)
            if sig: await post_setup(CHAN_CRYPTO, "Crypto Setup (manual)", sig, "15m", RISK_CRYPTO)
            await asyncio.sleep(0.2)
        except Exception as e:
            log.warning(f"manual crypto error {sym}: {e}")

async def run_manual_stocks():
    if not market_open(): return
    for t in WL_STOCKS:
        try:
            df = fetch_yf(t, "15m", "5d")
            if df is None or df.empty: continue
            sig = scan_series(t, df.o, df.h, df.c, df.c, df.v, RISK_STOCKS)
            if sig: await post_setup(CHAN_STOCKS, "Stock Setup (manual)", sig, "15m", RISK_STOCKS)
            await asyncio.sleep(0.2)
        except Exception as e:
            log.warning(f"manual stock error {t}: {e}")

async def run_manual_forex():
    mapping = {
        "XAUUSD":"XAUUSD=X",
        "USDJPY":"USDJPY=X",
        "EURUSD":"EURUSD=X",
        "GBPUSD":"GBPUSD=X",
        "SPX500USD":"^GSPC"
    }
    for t in WL_FOREX:
        yft = mapping.get(t, f"{t}=X")
        try:
            df = fetch_yf(yft, "15m", "5d")
            if df is None or df.empty: continue
            sig = scan_series(t, df.o, df.h, df.l, df.c, df.v, RISK_FOREX)
            if sig: await post_setup(CHAN_FOREX, "Forex Setup (manual)", sig, "15m", RISK_FOREX)
            await asyncio.sleep(0.2)
        except Exception as e:
            log.warning(f"manual forex error {t}: {e}")

bot.run(TOKEN)
