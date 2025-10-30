# bot.py
# Discord AI markets bot — clean drop-in
# Features:
# - Reads env-based watch lists and AI scan lists per asset class
# - Per-class thresholds (stars/confidence/strength) with fallbacks to global thresholds
# - yfinance-first / AV-first switching with graceful fallback & backoff
# - Hard-looped background scans gated by AI_*_LOOP=1
# - Commands: !price, !scanonce, !scanall, !scancrypto, !scanstocks, !scanforex, !scan <class> <symbol>, !env KEY

import os
import asyncio
import time
from typing import Dict, List, Optional, Tuple

import discord
from discord.ext import commands, tasks

# ---- Optional deps that must exist in requirements.txt ----
# yfinance for quotes; requests for Alpha Vantage fallback
import yfinance as yf
import requests

# ------------- Utilities & Config -------------
INTENTS = discord.Intents.default()
INTENTS.message_content = True

CMD_PREFIX = os.getenv("CMD_PREFIX", "!")
TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("BOT_TOKEN")

# Channel IDs (strings or ints both fine)
CHANNEL_CRYPTO_ID = os.getenv("CHANNEL_CRYPTO_ID")
CHANNEL_STOCKS_ID = os.getenv("CHANNEL_STOCKS_ID")
CHANNEL_FOREX_ID  = os.getenv("CHANNEL_FOREX_ID")

# Loop toggles (hard loops)
AI_CRYPTO_LOOP = os.getenv("AI_CRYPTO_LOOP", "0") == "1"
AI_STOCKS_LOOP = os.getenv("AI_STOCKS_LOOP", "0") == "1"
AI_FOREX_LOOP  = os.getenv("AI_FOREX_LOOP", "0") == "1"

# Loop cadence (minutes) — sensible defaults; can override via env
CRYPTO_EVERY_MIN = int(os.getenv("AI_CRYPTO_EVERY_MIN", "25"))
STOCKS_EVERY_MIN = int(os.getenv("AI_STOCKS_EVERY_MIN", "45"))
FOREX_EVERY_MIN  = int(os.getenv("AI_FOREX_EVERY_MIN",  "45"))

# Data sources
USE_YF_FIRST  = os.getenv("USE_YF_FIRST", "1") == "1"
DATA_CRYPTO_SOURCE = os.getenv("DATA_CRYPTO_SOURCE", "yf")  # "yf" or "av"
DATA_STOCKS_SOURCE = os.getenv("DATA_STOCKS_SOURCE", "yf")
DATA_FOREX_SOURCE  = os.getenv("DATA_FOREX_SOURCE",  "yf")

AV_KEY = os.getenv("ALPHAVANTAGE_API_KEY") or os.getenv("ALPHA_VANTAGE_API_KEY") or os.getenv("ALPHAVANTAGEKEY") or os.getenv("ALPHA_VANTAGE_KEY")
AV_BACKOFF_SEC = int(os.getenv("AV_BACKOFF_SEC", "12"))

# Global thresholds
AI_MIN_STARS     = int(os.getenv("AI_MIN_STARS", "3"))
AI_MIN_CONF      = float(os.getenv("AI_MIN_CONF", "0.60"))
AI_MIN_STRENGTH  = float(os.getenv("AI_MIN_STRENGTH", "3.0"))

# Per-asset-class overrides
CR_MIN_STARS    = int(os.getenv("AI_CRYPTO_MIN_STARS",    str(AI_MIN_STARS)))
CR_MIN_CONF     = float(os.getenv("AI_CRYPTO_MIN_CONF",   str(AI_MIN_CONF)))
CR_MIN_STRENGTH = float(os.getenv("AI_CRYPTO_MIN_STRENGTH", str(AI_MIN_STRENGTH)))

ST_MIN_STARS    = int(os.getenv("AI_STOCKS_MIN_STARS",    str(AI_MIN_STARS)))
ST_MIN_CONF     = float(os.getenv("AI_STOCKS_MIN_CONF",   str(AI_MIN_CONF)))
ST_MIN_STRENGTH = float(os.getenv("AI_STOCKS_MIN_STRENGTH", str(AI_MIN_STRENGTH)))

FX_MIN_STARS    = int(os.getenv("AI_FOREX_MIN_STARS",     str(AI_MIN_STARS)))
FX_MIN_CONF     = float(os.getenv("AI_FOREX_MIN_CONF",    str(AI_MIN_CONF)))
FX_MIN_STRENGTH = float(os.getenv("AI_FOREX_MIN_STRENGTH", str(AI_MIN_STRENGTH)))

# Watch lists (small, always included) & AI lists (bigger pools)
def parse_list(name: str) -> List[str]:
    raw = os.getenv(name, "") or ""
    if not raw.strip():
        return []
    items = [x.strip().upper() for x in raw.split(",") if x.strip()]
    return list(dict.fromkeys(items))  # dedupe, keep order

AIWATCH_CRYPTO_TICKERS = parse_list("AIWATCH_CRYPTO_TICKERS")
AIWATCH_STOCKS_TICKERS = parse_list("AIWATCH_STOCKS_TICKERS")
AIWATCH_FOREX_TICKERS  = parse_list("AIWATCH_FOREX_TICKERS")

AI_CRYPTO_AI_TICKERS = parse_list("AI_CRYPTO_AI_TICKERS")
AI_STOCKS_AI_TICKERS = parse_list("AI_STOCKS_AI_TICKERS")
AI_FOREX_AI_TICKERS  = parse_list("AI_FOREX_AI_TICKERS")

# Combine watch + AI list for each class (watch first, then rest)
def combined(symbols_watch: List[str], symbols_ai: List[str]) -> List[str]:
    base = list(symbols_watch)
    for s in symbols_ai:
        if s not in base:
            base.append(s)
    return base

CRYPTO_LIST = combined(AIWATCH_CRYPTO_TICKERS, AI_CRYPTO_AI_TICKERS)
STOCKS_LIST = combined(AIWATCH_STOCKS_TICKERS, AI_STOCKS_AI_TICKERS)
FOREX_LIST  = combined(AIWATCH_FOREX_TICKERS,  AI_FOREX_AI_TICKERS)

# ---- Discord bot ----
bot = commands.Bot(command_prefix=CMD_PREFIX, intents=INTENTS)

# ---------- Price Helpers ----------
session = requests.Session()

def _yf_crypto_symbol(sym: str) -> str:
    # ENV accepts "XRP", "ETH", "SOL", "HBAR" etc.; yfinance wants "XRP-USD"
    if "-" in sym:
        return sym  # user provided "ETH-USD" etc.
    return f"{sym}-USD"

def _yf_forex_symbol(pair: str) -> str:
    # ENV accepts "USDJPY", "EURUSD", "XAUUSD"
    p = pair.upper().replace("-", "").replace("/", "")
    if len(p) == 6 or len(p) == 5:  # XAUUSD is 6
        return f"{p}=X"
    return f"{pair}=X"

def yf_last_price(tkr: str) -> Optional[float]:
    try:
        t = yf.Ticker(tkr)
        # Prefer fast info first
        info = t.fast_info
        if info and getattr(info, "last_price", None):
            return float(info.last_price)
        # fallback to history
        hist = t.history(period="1d", interval="1m")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
        hist = t.history(period="1d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception as e:
        print(f"[yf] error for {tkr}: {e}")
    return None

def av_crypto_price(symbol: str, market: str="USD") -> Optional[float]:
    if not AV_KEY:
        return None
    try:
        url = "https://www.alphavantage.co/query"
        params = {
            "function":"CURRENCY_EXCHANGE_RATE",
            "from_currency": symbol.upper(),
            "to_currency": market.upper(),
            "apikey": AV_KEY
        }
        r = session.get(url, params=params, timeout=20)
        data = r.json()
        rate = data.get("Realtime Currency Exchange Rate", {}).get("5. Exchange Rate")
        if rate:
            return float(rate)
    except Exception as e:
        print(f"[av] crypto error {symbol}/{market}: {e}")
    return None

def av_fx_price(pair: str) -> Optional[float]:
    if not AV_KEY:
        return None
    p = pair.upper().replace("-", "").replace("/", "")
    if len(p) < 6:
        return None
    from_sym, to_sym = p[:3], p[3:]
    try:
        url = "https://www.alphavantage.co/query"
        params = {
            "function":"CURRENCY_EXCHANGE_RATE",
            "from_currency": from_sym,
            "to_currency": to_sym,
            "apikey": AV_KEY
        }
        r = session.get(url, params=params, timeout=20)
        data = r.json()
        rate = data.get("Realtime Currency Exchange Rate", {}).get("5. Exchange Rate")
        if rate:
            return float(rate)
    except Exception as e:
        print(f"[av] fx error {pair}: {e}")
    return None

def av_stock_price(symbol: str) -> Optional[float]:
    if not AV_KEY:
        return None
    try:
        url = "https://www.alphavantage.co/query"
        params = {"function":"GLOBAL_QUOTE", "symbol":symbol.upper(), "apikey":AV_KEY}
        r = session.get(url, params=params, timeout=20)
        data = r.json()
        q = data.get("Global Quote", {})
        price = q.get("05. price")
        if price:
            return float(price)
    except Exception as e:
        print(f"[av] stock error {symbol}: {e}")
    return None

async def get_price(asset_class: str, symbol: str) -> Optional[float]:
    asset = asset_class.lower()
    # Decide primary & fallback sources
    prim, fallback = ("yf", "av") if USE_YF_FIRST else ("av", "yf")

    for src in (prim, fallback):
        if asset == "crypto":
            if src == "yf":
                p = yf_last_price(_yf_crypto_symbol(symbol))
            else:
                time.sleep(AV_BACKOFF_SEC)
                p = av_crypto_price(symbol, "USD")
        elif asset == "stocks":
            if src == "yf":
                p = yf_last_price(symbol.upper())
            else:
                time.sleep(AV_BACKOFF_SEC)
                p = av_stock_price(symbol.upper())
        elif asset == "forex":
            if src == "yf":
                p = yf_last_price(_yf_forex_symbol(symbol))
            else:
                time.sleep(AV_BACKOFF_SEC)
                p = av_fx_price(symbol)
        else:
            p = None

        if p is not None:
            return p
    return None

# ---------- Very light "signal" scoring ----------
# We keep it simple and robust: fetch two timeframes via yfinance, derive a rough momentum/vol proxy.
def _history_close(tkr: str, period: str, interval: str) -> Optional[List[float]]:
    try:
        df = yf.Ticker(tkr).history(period=period, interval=interval)
        if df is not None and not df.empty:
            return list(df["Close"].astype(float))
    except Exception as e:
        print(f"[hist] {tkr} {period}/{interval} err: {e}")
    return None

def simple_score(asset_class: str, symbol: str) -> Tuple[int, float, float, Dict[str, float]]:
    """Return (stars, conf, strength, metrics) using a tiny momentum/vol heuristic."""
    # Map to yfinance tickers
    if asset_class == "crypto":
        tkr = _yf_crypto_symbol(symbol)
        d1 = _history_close(tkr, "5d", "1h")
        d2 = _history_close(tkr, "1mo", "1d")
    elif asset_class == "forex":
        tkr = _yf_forex_symbol(symbol)
        d1 = _history_close(tkr, "5d", "1h")
        d2 = _history_close(tkr, "1mo", "1d")
    else:  # stocks
        tkr = symbol.upper()
        d1 = _history_close(tkr, "5d", "1h")
        d2 = _history_close(tkr, "3mo", "1d")

    if not d1 and not d2:
        return (0, 0.0, 0.0, {"reason":"no_data"})

    def pct(a, b):
        try:
            return (a - b) / b * 100.0
        except Exception:
            return 0.0

    # Intra momentum
    m1 = pct(d1[-1], d1[0]) if d1 and len(d1) > 1 else 0.0
    # Higher timeframe momentum
    m2 = pct(d2[-1], d2[0]) if d2 and len(d2) > 1 else 0.0

    # Vol proxy
    import statistics
    vol = 0.0
    base = (d1 or [])[-48:] + (d2 or [])[-20:]
    if len(base) > 2:
        returns = []
        for i in range(1, len(base)):
            try:
                returns.append((base[i] - base[i-1]) / base[i-1])
            except Exception:
                pass
        if len(returns) > 2:
            vol = statistics.pstdev(returns) * 100.0  # % stdev

    # Strength is blended momentum scaled by vol clamp
    strength = max(0.0, (0.6*abs(m1) + 0.4*abs(m2)) * (1 + min(vol, 5.0)))

    # Confidence ~ consistency of direction and low whipsaw (toy)
    same_dir = (m1 >= 0 and m2 >= 0) or (m1 <= 0 and m2 <= 0)
    conf = 0.55 if same_dir else 0.45
    if abs(m1) > 1 and abs(m2) > 1 and same_dir:
        conf += 0.10
    conf = max(0.0, min(0.99, conf))

    # Stars by thresholds of strength & momentum alignment
    stars = 2
    if abs(m1) > 0.8 and abs(m2) > 0.6 and same_dir:
        stars = 3
    if abs(m1) > 1.5 and abs(m2) > 1.2 and strength > 3:
        stars = 4
    if abs(m1) > 2.5 and abs(m2) > 2.0 and strength > 5:
        stars = 5

    metrics = {"m1%": round(m1,2), "m2%": round(m2,2), "vol%": round(vol,2)}
    return (stars, conf, strength, metrics)

def passes_thresholds(asset_class: str, stars: int, conf: float, strength: float) -> Tuple[bool, str]:
    if asset_class == "crypto":
        if stars < CR_MIN_STARS: return (False, f"stars<{CR_MIN_STARS}")
        if conf  < CR_MIN_CONF:  return (False, f"conf<{CR_MIN_CONF}")
        if strength < CR_MIN_STRENGTH: return (False, f"strength<{CR_MIN_STRENGTH}")
        return (True, "")
    if asset_class == "stocks":
        if stars < ST_MIN_STARS: return (False, f"stars<{ST_MIN_STARS}")
        if conf  < ST_MIN_CONF:  return (False, f"conf<{ST_MIN_CONF}")
        if strength < ST_MIN_STRENGTH: return (False, f"strength<{ST_MIN_STRENGTH}")
        return (True, "")
    if asset_class == "forex":
        if stars < FX_MIN_STARS: return (False, f"stars<{FX_MIN_STARS}")
        if conf  < FX_MIN_CONF:  return (False, f"conf<{FX_MIN_CONF}")
        if strength < FX_MIN_STRENGTH: return (False, f"strength<{FX_MIN_STRENGTH}")
        return (True, "")
    return (False, "unknown_class")

# ---------- Formatting ----------
def fmt_signal(asset_class: str, sym: str, price: Optional[float], stars: int, conf: float, strength: float, metrics: Dict[str,float]) -> str:
    stars_bar = "★"*stars + "☆"*(5-stars)
    ptxt = f"${price:,.4f}" if price is not None else "—"
    return (
        f"**{asset_class.upper()}** · `{sym}` · Price: **{ptxt}**\n"
        f"Risk: **{stars_bar}** · Conf: **{conf:.2f}** · Strength: **{strength:.2f}** "
        f"· m1: {metrics.get('m1%',0):.2f}% · m2: {metrics.get('m2%',0):.2f}% · vol: {metrics.get('vol%',0):.2f}%"
    )

# ---------- Core scanning ----------
async def scan_symbols(asset_class: str, symbols: List[str]) -> List[str]:
    out = []
    for sym in symbols:
        price = await get_price(asset_class, sym)
        stars, conf, strength, metrics = simple_score(asset_class, sym)
        ok, why = passes_thresholds(asset_class, stars, conf, strength)
        if ok:
            out.append(fmt_signal(asset_class, sym, price, stars, conf, strength, metrics))
        else:
            print(f"[filter] {asset_class} {sym}: blocked reason={why} stars={stars} conf={conf:.2f} strength={strength:.2f}")
    return out

# ---------- Discord Commands ----------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} ({bot.user.id})")
    print("🧠 AI scan loops status:")
    print(f"   - Crypto loop: {AI_CRYPTO_LOOP} every {CRYPTO_EVERY_MIN}m, symbols={CRYPTO_LIST}")
    print(f"   - Stocks loop: {AI_STOCKS_LOOP} every {STOCKS_EVERY_MIN}m, symbols={STOCKS_LIST}")
    print(f"   - Forex loop:  {AI_FOREX_LOOP} every {FOREX_EVERY_MIN}m, symbols={FOREX_LIST}")
    print("   Thresholds:")
    print(f"   - Crypto mins: stars={CR_MIN_STARS} conf={CR_MIN_CONF} strength={CR_MIN_STRENGTH}")
    print(f"   - Stocks mins: stars={ST_MIN_STARS} conf={ST_MIN_CONF} strength={ST_MIN_STRENGTH}")
    print(f"   - Forex  mins: stars={FX_MIN_STARS} conf={FX_MIN_CONF} strength={FX_MIN_STRENGTH}")
    if AI_CRYPTO_LOOP: crypto_loop.change_interval(minutes=CRYPTO_EVERY_MIN); crypto_loop.start()
    if AI_STOCKS_LOOP: stocks_loop.change_interval(minutes=STOCKS_EVERY_MIN); stocks_loop.start()
    if AI_FOREX_LOOP:  forex_loop.change_interval(minutes=FOREX_EVERY_MIN);  forex_loop.start()
    if not (AI_CRYPTO_LOOP or AI_STOCKS_LOOP or AI_FOREX_LOOP):
        print("ℹ️ Loops disabled; use !scanonce or !scanall to test.")

@bot.command(name="env")
async def env_command(ctx, key: str):
    val = os.getenv(key)
    await ctx.send(f"`{key}` = `{val}`" if val is not None else f"`{key}` not set")

@bot.command(name="price")
async def price_command(ctx, asset_class: str, symbol: str):
    p = await get_price(asset_class, symbol)
    if p is None:
        await ctx.send(f"Couldn’t fetch price for `{asset_class}:{symbol}`.")
    else:
        await ctx.send(f"`{asset_class}:{symbol}` → **${p:,.4f}**")

@bot.command(name="scan")
async def scan_one(ctx, asset_class: str, symbol: Optional[str] = None):
    if symbol:
        msgs = await scan_symbols(asset_class, [symbol.upper()])
    else:
        if asset_class.lower() == "crypto":   pool = CRYPTO_LIST
        elif asset_class.lower() == "stocks": pool = STOCKS_LIST
        elif asset_class.lower() == "forex":  pool = FOREX_LIST
        else:
            await ctx.send("Use: `!scan <crypto|stocks|forex> [SYMBOL]`")
            return
        if not pool:
            await ctx.send("No symbols configured for that class.")
            return
        msgs = await scan_symbols(asset_class, pool)
    if msgs:
        for m in msgs:
            await ctx.send(m)
    else:
        await ctx.send("No strong signals right now.")

@bot.command(name="scanonce")
async def scanonce(ctx):
    any_symbols = CRYPTO_LIST or STOCKS_LIST or FOREX_LIST
    if not any_symbols:
        await ctx.send("No symbols configured. Set your *_TICKERS env vars and redeploy.")
        return
    out = []
    out += await scan_symbols("crypto", CRYPTO_LIST) if CRYPTO_LIST else []
    out += await scan_symbols("stocks", STOCKS_LIST) if STOCKS_LIST else []
    out += await scan_symbols("forex",  FOREX_LIST)  if FOREX_LIST  else []
    if out:
        for m in out:
            await ctx.send(m)
    else:
        await ctx.send("No strong signals right now.")

@bot.command(name="scanall")
async def scanall(ctx):
    await scanonce(ctx)

@bot.command(name="scancrypto")
async def scancrypto(ctx):
    if not CRYPTO_LIST:
        await ctx.send("No symbols configured for crypto.")
        return
    msgs = await scan_symbols("crypto", CRYPTO_LIST)
    if msgs:
        for m in msgs:
            await ctx.send(m)
    else:
        await ctx.send("No strong crypto signals right now.")

@bot.command(name="scanstocks")
async def scanstocks(ctx):
    if not STOCKS_LIST:
        await ctx.send("No symbols configured for stocks.")
        return
    msgs = await scan_symbols("stocks", STOCKS_LIST)
    if msgs:
        for m in msgs:
            await ctx.send(m)
    else:
        await ctx.send("No strong stock signals right now.")

@bot.command(name="scanforex")
async def scanforex(ctx):
    if not FOREX_LIST:
        await ctx.send("No symbols configured for forex.")
        return
    msgs = await scan_symbols("forex", FOREX_LIST)
    if msgs:
        for m in msgs:
            await ctx.send(m)
    else:
        await ctx.send("No strong forex signals right now.")

# ---------- Loops (hardloop) ----------
async def post_signals_to_channel(channel_id: str, messages: List[str], empty_text: str):
    try:
        ch = bot.get_channel(int(channel_id))
    except Exception:
        ch = None
    if not ch:
        print(f"[loop] channel {channel_id} not found or bot lacks access.")
        return
    if messages:
        for m in messages:
            await ch.send(m)
    else:
        await ch.send(empty_text)

@tasks.loop(minutes=25)
async def crypto_loop():
    if not CHANNEL_CRYPTO_ID or not CRYPTO_LIST:
        print("⚠️ Crypto loop: missing channel or symbols; skipping.")
        return
    msgs = await scan_symbols("crypto", CRYPTO_LIST)
    await post_signals_to_channel(CHANNEL_CRYPTO_ID, msgs, "No strong crypto signals this round.")

@tasks.loop(minutes=45)
async def stocks_loop():
    if not CHANNEL_STOCKS_ID or not STOCKS_LIST:
        print("⚠️ Stocks loop: missing channel or symbols; skipping.")
        return
    msgs = await scan_symbols("stocks", STOCKS_LIST)
    await post_signals_to_channel(CHANNEL_STOCKS_ID, msgs, "No strong stock signals this round.")

@tasks.loop(minutes=45)
async def forex_loop():
    if not CHANNEL_FOREX_ID or not FOREX_LIST:
        print("⚠️ Forex loop: missing channel or symbols; skipping.")
        return
    msgs = await scan_symbols("forex", FOREX_LIST)
    await post_signals_to_channel(CHANNEL_FOREX_ID, msgs, "No strong forex signals this round.")

# ---------- Bootstrap ----------
if not TOKEN:
    print("❌ DISCORD_TOKEN not set. Exiting.")
else:
    print("🚀 Starting bot...")
    bot.run(TOKEN)