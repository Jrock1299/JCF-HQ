# ---------------------------
# JCF WatchBot - full drop-in
# ---------------------------

# Force "no audio" BEFORE importing discord to avoid audioop on Py 3.11/3.13
import os
os.environ["DISCORD_NO_AUDIO"] = "1"

import asyncio
import datetime as dt
import json
import math
import random
import traceback

import discord
from discord.ext import commands, tasks

# Data stack
import requests
import numpy as np
import pandas as pd
import yfinance as yf

# ====== ENV / CONFIG ======
TOKEN = os.getenv("DISCORD_TOKEN", "")

# Channel IDs (ints, optional)
def _to_int(s):
    try:
        return int(str(s))
    except Exception:
        return None

CHANNEL_CRYPTO_ID = _to_int(os.getenv("CHANNEL_CRYPTO_ID"))
CHANNEL_STOCKS_ID = _to_int(os.getenv("CHANNEL_STOCKS_ID"))
CHANNEL_FOREX_ID  = _to_int(os.getenv("CHANNEL_FOREX_ID"))

# Watchlists (CSV)
def _csv_list(name, default):
    raw = os.getenv(name, default)
    return [x.strip() for x in raw.split(",") if x.strip()]

WATCHLIST_CRYPTO = _csv_list("WATCHLIST_CRYPTO", "BTC-USD,ETH-USD,SOL-USD,MSTR")
WATCHLIST_STOCKS = _csv_list("WATCHLIST_STOCKS", "AAPL,NVDA,TSLA,SPY,AMD,PLTR,SOFI,MSTR")
WATCHLIST_FOREX  = _csv_list("WATCHLIST_FOREX", "EURUSD,GBPUSD,USDJPY,XAUUSD")

# Risk knobs
RISK_CRYPTO_PCT = float(os.getenv("RISK_CRYPTO_PCT", "2"))      # You said 2% for crypto
RISK_STOCKS_PCT = float(os.getenv("RISK_STOCKS_PCT", "1"))      # default 1% stocks
RISK_FOREX_PCT  = float(os.getenv("RISK_FOREX_PCT", "1"))       # default 1% fx

# Signal tuning
CONF_THRESHOLD   = float(os.getenv("SIGNAL_CONF_THRESHOLD", "0.75"))  # 0..1
EARLY_VS_CONFIRMED = os.getenv("SIGNAL_TIMING", "hybrid").lower()     # early|confirmed|hybrid
INTRADAY_FOCUS  = os.getenv("INTRADAY_FOCUS", "1") == "1"             # bias faster signals

# Loop controls
AI_SCAN_LOOP    = os.getenv("AI_SCAN_LOOP", "1") == "1"
LOOP_MIN_CRYPTO = int(os.getenv("LOOP_MIN_CRYPTO", "25"))
LOOP_MIN_STOCKS = int(os.getenv("LOOP_MIN_STOCKS", "45"))
LOOP_MIN_FOREX  = int(os.getenv("LOOP_MIN_FOREX", "45"))

# TP / RR preferences (you picked 2 TPs, text only; early vs confirmed included)
TP_MODE     = os.getenv("TPMODE", "two")  # "two" or "single"
TP1_RR      = float(os.getenv("TP1_RR", "1.0"))  # risk:reward tp1
TP2_RR      = float(os.getenv("TP2_RR", "2.0"))  # risk:reward tp2

# Alpha Vantage fallback
ALPHAVANTAGE_KEY   = os.getenv("ALPHAVANTAGE_KEY", "")
USE_ALPHA_FALLBACK = os.getenv("USE_ALPHA_FALLBACK", "1") == "1"

# ====== DISCORD SETUP ======
intents = discord.Intents.default()
intents.message_content = True

# Disable the default !help (we had a registration conflict earlier)
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# ====== DATA HELPERS ======
ALIAS_YAHOO = {
    # Indices/FX common aliases -> Yahoo symbols
    "SPX": "^GSPC",
    "XAUUSD": "XAUUSD=X",
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
}

def get_ohlc(symbol: str, period_days: int = 180, interval="1d"):
    """
    Returns list of dict OHLC candles (newest last):
    [{time, open, high, low, close}, ...]
    Tries Yahoo via yfinance, then Alpha Vantage as fallback (if enabled).
    """
    # 1) Yahoo try
    try:
        end = dt.datetime.utcnow()
        start = end - dt.timedelta(days=period_days + 10)
        ysym = ALIAS_YAHOO.get(symbol.upper(), symbol)
        df = yf.download(
            ysym,
            start=start.date().isoformat(),
            end=end.date().isoformat(),
            interval=interval,
            progress=False
        )
        if df is not None and not df.empty and {"Open","High","Low","Close"}.issubset(df.columns):
            out = []
            for ts, row in df.iterrows():
                # Some intervals return timezone-aware index
                if hasattr(ts, "to_pydatetime"):
                    ts = ts.to_pydatetime()
                out.append({
                    "time": ts,
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low":  float(row["Low"]),
                    "close":float(row["Close"]),
                })
            if out:
                return out
    except Exception as e:
        print(f"[yf] {symbol} error: {e}")

    # 2) Alpha fallback
    if not (USE_ALPHA_FALLBACK and ALPHAVANTAGE_KEY):
        return []

    try:
        if symbol.upper() in ("EURUSD","GBPUSD","USDJPY","XAUUSD"):
            from_sym, to_sym = symbol[:3].upper(), symbol[3:].upper()
            if symbol.upper() == "XAUUSD":
                # Alpha uses "XAU" as from_symbol with FX_DAILY too
                from_sym, to_sym = "XAU", "USD"
            url = ("https://www.alphavantage.co/query"
                   f"?function=FX_DAILY&from_symbol={from_sym}&to_symbol={to_sym}"
                   f"&apikey={ALPHAVANTAGE_KEY}&outputsize=full")
            r = requests.get(url, timeout=15)
            data = r.json().get("Time Series FX (Daily)", {})
        else:
            sym = "SPY" if symbol.upper() in ("^GSPC", "SPX") else symbol.upper()
            url = ("https://www.alphavantage.co/query"
                   f"?function=TIME_SERIES_DAILY_ADJUSTED&symbol={sym}"
                   f"&apikey={ALPHAVANTAGE_KEY}&outputsize=full")
            r = requests.get(url, timeout=15)
            data = r.json().get("Time Series (Daily)", {})

        rows = []
        for dstr, row in sorted(data.items()):
            rows.append({
                "time": dt.datetime.strptime(dstr, "%Y-%m-%d"),
                "open": float(row.get("1. open") or row.get("1. Open", 0.0)),
                "high": float(row.get("2. high") or row.get("2. High", 0.0)),
                "low":  float(row.get("3. low")  or row.get("3. Low",  0.0)),
                "close":float(row.get("4. close") or row.get("4. Close", 0.0)),
            })
        return rows[-period_days:]
    except Exception as e:
        print(f"[alpha] {symbol} error: {e}")
        return []

def sma(series, length):
    if len(series) < length:
        return [np.nan]*len(series)
    s = pd.Series(series, dtype=float)
    return s.rolling(length).mean().tolist()

def rsi(series, length=14):
    # Simple RSI implementation on closes
    if len(series) < length + 1:
        return [np.nan]*len(series)
    s = pd.Series(series, dtype=float)
    delta = s.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.rolling(length).mean()
    avg_loss = loss.rolling(length).mean()
    rs = avg_gain / (avg_loss.replace(0, np.nan))
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50).tolist()

def assess_signal(symbol, candles):
    """
    Very light 'AI-ish' heuristic:
      - Trend continuation + breakout-retest vibe
      - Uses SMA(20/50) slope + last close vs recent range + RSI
    Returns (is_signal, direction, confidence, context_dict)
    """
    if len(candles) < 60:
        return (False, None, 0.0, {})

    closes = [c["close"] for c in candles]
    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]
    times  = [c["time"]  for c in candles]

    sma20 = sma(closes, 20)
    sma50 = sma(closes, 50)
    rsi14 = rsi(closes, 14)

    last = -1
    c = closes[last]
    s20 = sma20[last]
    s50 = sma50[last]
    r  = rsi14[last]

    # Slopes
    def slope(arr, k=5):
        if len(arr) < k+1 or any(np.isnan(arr[-i]) for i in range(1,k+1)):
            return 0.0
        y1, y2 = arr[-k], arr[-1]
        return (y2 - y1) / max(1e-9, k)

    slope20 = slope(sma20, 5)
    slope50 = slope(sma50, 5)

    # Range breakout check
    recent_high = max(highs[-20:])
    recent_low  = min(lows[-20:])

    bull_bias = slope20 > 0 and slope50 > 0 and s20 >= s50
    bear_bias = slope20 < 0 and slope50 < 0 and s20 <= s50

    long_break  = c >= recent_high * 0.999
    short_break = c <= recent_low  * 1.001

    direction = None
    score = 0.0
    notes = []

    if bull_bias and long_break:
        direction = "LONG"
        score += 0.55
        notes.append("Uptrend + breakout")
    if bear_bias and short_break:
        direction = "SHORT"
        score += 0.55
        notes.append("Downtrend + breakdown")

    # RSI confirmation
    if direction == "LONG" and 50 <= r <= 70:
        score += 0.2
        notes.append("RSI supportive")
    if direction == "SHORT" and 30 <= r <= 50:
        score += 0.2
        notes.append("RSI supportive")

    # Early vs confirmed: adjust threshold or score
    if EARLY_VS_CONFIRMED == "early":
        score += 0.1
    elif EARLY_VS_CONFIRMED == "confirmed":
        score -= 0.05

    # Intraday bias: slightly boost frequent signals
    if INTRADAY_FOCUS:
        score += 0.05

    confidence = max(0.0, min(0.99, score))
    return (confidence >= CONF_THRESHOLD and direction is not None, direction, confidence, {
        "rsi": round(r, 1),
        "sma20": s20,
        "sma50": s50,
        "recent_high": recent_high,
        "recent_low": recent_low,
        "last_close": c,
        "notes": notes
    })

def calc_tp_sl(entry, direction, risk_pct=1.0, rr1=1.0, rr2=2.0, atr_like=None):
    """
    Simple TP/SL using synthetic 'ATR-like' measure (recent range).
    Returns dict with sl, tp1, tp2 (if two).
    """
    # Use last 14 bars range as poor-man ATR
    vol = atr_like if atr_like and atr_like > 0 else None
    if vol is None:
        vol = 0.0
    # Fallback: 1% of entry if no range info
    if vol == 0.0:
        vol = entry * 0.01

    # Stop = 1x 'vol', TP multiples by RR
    if direction == "LONG":
        sl   = entry - vol
        tp1  = entry + vol * rr1
        tp2  = entry + vol * rr2 if TP_MODE == "two" else None
    else:
        sl   = entry + vol
        tp1  = entry - vol * rr1
        tp2  = entry - vol * rr2 if TP_MODE == "two" else None

    return {"sl": sl, "tp1": tp1, "tp2": tp2}

async def post_signal(channel: discord.TextChannel, symbol: str, direction: str, conf: float, ctx: dict, risk_pct: float):
    entry = ctx["last_close"]
    rng   = (ctx["recent_high"] - ctx["recent_low"]) / 14.0  # crude ATR-like
    tps   = calc_tp_sl(entry, direction, risk_pct=risk_pct, rr1=TP1_RR, rr2=TP2_RR, atr_like=rng)

    early_or_conf = {"early":"EARLY", "confirmed":"CONFIRMED"}.get(EARLY_VS_CONFIRMED, "HYBRID")
    lines = [
        f"**{symbol}** — {direction}  |  Confidence: **{int(conf*100)}%**  ({early_or_conf})",
        f"Entry (mkt): **{entry:.2f}**",
        f"Stop: **{tps['sl']:.2f}**",
        f"TP1 (RR {TP1_RR:.1f}): **{tps['tp1']:.2f}**",
    ]
    if TP_MODE == "two" and tps["tp2"] is not None:
        lines.append(f"TP2 (RR {TP2_RR:.1f}): **{tps['tp2']:.2f}**")
    lines += [
        "",
        f"Risk per trade: **{risk_pct:.1f}%**",
        f"RSI: **{ctx['rsi']}**",
        f"Notes: _{', '.join(ctx['notes']) or '—'}_"
    ]
    await channel.send("\n".join(lines))

async def scan_and_post(kind: str):
    """
    kind in {"crypto","stocks","forex"}
    """
    channel_id = {
        "crypto": CHANNEL_CRYPTO_ID,
        "stocks": CHANNEL_STOCKS_ID,
        "forex":  CHANNEL_FOREX_ID
    }.get(kind)

    if not channel_id:
        print(f"⚠️ No CHANNEL_{kind.upper()}_ID set; skipping {kind} scan.")
        return

    channel = bot.get_channel(channel_id)
    if channel is None:
        print(f"⚠️ Channel id {channel_id} not found in cache for {kind}.")
        return

    watch = {
        "crypto": WATCHLIST_CRYPTO,
        "stocks": WATCHLIST_STOCKS,
        "forex":  WATCHLIST_FOREX
    }[kind]

    risk_pct = {
        "crypto": RISK_CRYPTO_PCT,
        "stocks": RISK_STOCKS_PCT,
        "forex":  RISK_FOREX_PCT
    }[kind]

    hits = 0
    for sym in watch:
        candles = get_ohlc(sym, period_days=180, interval="1d")
        if not candles:
            print(f"[scan:{kind}] {sym} -> no data (yf/alpha both empty).")
            continue

        ok, direction, conf, ctx = assess_signal(sym, candles)
        if ok:
            await post_signal(channel, sym, direction, conf, ctx, risk_pct)
            hits += 1

    if hits == 0:
        await channel.send("🟨 No strong signals on my latest pass.")

# ====== LOOPS ======
@tasks.loop(minutes=LOOP_MIN_CRYPTO)
async def crypto_loop():
    try:
        await scan_and_post("crypto")
    except Exception:
        traceback.print_exc()

@tasks.loop(minutes=LOOP_MIN_STOCKS)
async def stocks_loop():
    try:
        await scan_and_post("stocks")
    except Exception:
        traceback.print_exc()

@tasks.loop(minutes=LOOP_MIN_FOREX)
async def forex_loop():
    try:
        await scan_and_post("forex")
    except Exception:
        traceback.print_exc()

# ====== COMMANDS ======
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} ({bot.user.id})")
    if AI_SCAN_LOOP:
        print("🧠 AI scan loops started.")
        if LOOP_MIN_CRYPTO > 0:
            print(f"♻️ Crypto loop every {LOOP_MIN_CRYPTO}m enabled.")
            crypto_loop.start()
        if LOOP_MIN_STOCKS > 0:
            print(f"♻️ Stocks loop every {LOOP_MIN_STOCKS}m enabled.")
            stocks_loop.start()
        if LOOP_MIN_FOREX > 0:
            print(f"♻️ Forex loop every {LOOP_MIN_FOREX}m enabled.")
            forex_loop.start()

@bot.command()
async def ping(ctx):
    await ctx.reply("Pong 🏓")

@bot.command(name="price")
async def price_cmd(ctx, symbol: str):
    """!price AAPL  -> shows latest close"""
    candles = get_ohlc(symbol, period_days=5, interval="1d")
    if not candles:
        await ctx.reply(f"Couldn’t load data for `{symbol}`.")
        return
    last = candles[-1]
    await ctx.reply(f"**{symbol.upper()}** last close: **{last['close']:.4f}** (on {last['time'].date()})")

@bot.command(name="scan")
async def scan_cmd(ctx, which: str):
    """!scan once <crypto|stocks|forex>"""
    which = which.lower()
    if which not in ("crypto","stocks","forex"):
        await ctx.reply("Use `!scan <crypto|stocks|forex>`")
        return
    await ctx.reply(f"Scanning **{which}** watchlist…")
    await scan_and_post(which)

@bot.command(name="scanonce")
async def scanonce_alias(ctx, which: str):
    await scan_cmd(ctx, which)

# ====== RUN ======
if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Missing DISCORD_TOKEN env var.")
    bot.run(TOKEN)