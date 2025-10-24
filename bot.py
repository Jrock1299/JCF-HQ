# bot.py
# Hunxho / JCFWatchBot – AI watchlists + Alpha Vantage pricing & scans

import os
os.environ["DISCORD_NO_AUDIO"] = "1"  # hard-disable voice deps

import re
import asyncio
import logging
from typing import Optional, Tuple, Dict, Any, List

import discord
from discord.ext import commands, tasks
import aiohttp

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s")
log = logging.getLogger("jcfbot")

# ---------- Env ----------
TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing.")

# Channel IDs (optional; needed only for auto loops)
CHANNEL_CRYPTO_ID = int(os.getenv("CHANNEL_CRYPTO_ID", "0") or "0")
CHANNEL_STOCKS_ID = int(os.getenv("CHANNEL_STOCKS_ID", "0") or "0")
CHANNEL_FOREX_ID  = int(os.getenv("CHANNEL_FOREX_ID", "0") or "0")

# Alpha Vantage
AV_KEY = os.getenv("ALPHAVANTAGE_API_KEY", "").strip()

# Loop enable
AI_SCAN_LOOP = os.getenv("AI_SCAN_LOOP", "0").strip() == "1"

# ---------- Watchlist loader (supports *_TICKERS and non-suffixed) ----------
def _parse_symlist(val: str) -> List[str]:
    if not val:
        return []
    parts = re.split(r"[,\s]+", val.strip())
    return [p.upper() for p in parts if p]

def _env_first(*names: str) -> str:
    for n in names:
        v = os.getenv(n, "")
        if v and v.strip():
            return v
    return ""

CRYPTO_RAW = _env_first("AIWATCH_CRYPTO_TICKERS", "AIWATCH_CRYPTO")
STOCKS_RAW = _env_first("AIWATCH_STOCKS_TICKERS", "AIWATCH_STOCKS")
FOREX_RAW  = _env_first("AIWATCH_FOREX_TICKERS",  "AIWATCH_FOREX")

WATCH_CRYPTO = _parse_symlist(CRYPTO_RAW)
WATCH_STOCKS = _parse_symlist(STOCKS_RAW)
WATCH_FOREX  = _parse_symlist(FOREX_RAW)

log.info("Loaded watchlists — crypto=%s stocks=%s forex=%s", WATCH_CRYPTO, WATCH_STOCKS, WATCH_FOREX)

# ---------- Discord setup ----------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- HTTP ----------
SESSION: Optional[aiohttp.ClientSession] = None
AV_BASE = "https://www.alphavantage.co/query"

async def _http_get_json(params: Dict[str, Any]) -> Dict[str, Any]:
    """GET Alpha Vantage JSON with basic error handling."""
    if not SESSION:
        raise RuntimeError("HTTP session not initialized")
    async with SESSION.get(AV_BASE, params=params, timeout=20) as resp:
        text = await resp.text()
        try:
            data = await resp.json(content_type=None)
        except Exception:
            log.error("AlphaVantage non-JSON response: %s", text[:300])
            return {}
        # AV throttling message
        if "Note" in data or "Information" in data:
            log.warning("AV throttle/info: %s", data.get("Note") or data.get("Information"))
        return data

# ---------- Alpha Vantage helpers ----------
async def av_price_equity(symbol: str) -> Optional[float]:
    """Equity price via GLOBAL_QUOTE."""
    if not AV_KEY:
        return None
    params = {
        "function": "GLOBAL_QUOTE",
        "symbol": symbol.upper(),
        "apikey": AV_KEY,
    }
    data = await _http_get_json(params)
    quote = data.get("Global Quote") or {}
    price = quote.get("05. price") or quote.get("05. Price")
    try:
        return float(price) if price else None
    except Exception:
        return None

async def av_price_fx(from_ccy: str, to_ccy: str) -> Optional[float]:
    """FX (and works for many crypto symbols) via CURRENCY_EXCHANGE_RATE."""
    if not AV_KEY:
        return None
    params = {
        "function": "CURRENCY_EXCHANGE_RATE",
        "from_currency": from_ccy.upper(),
        "to_currency": to_ccy.upper(),
        "apikey": AV_KEY,
    }
    data = await _http_get_json(params)
    key = "Realtime Currency Exchange Rate"
    rate = (data.get(key) or {}).get("5. Exchange Rate")
    try:
        return float(rate) if rate else None
    except Exception:
        return None

def split_pair(sym: str) -> Tuple[str, str]:
    """Split pairs like XRPUSD or EURUSD, fallback to (sym,'USD')."""
    s = sym.upper().replace("-", "").replace("/", "")
    if len(s) == 6:
        return s[:3], s[3:]
    # default USD quote if not a classic 6-letter pair
    return s, "USD"

async def av_price_crypto(sym: str) -> Optional[float]:
    """Crypto via exchange-rate trick (XRPUSD => XRP->USD)."""
    base, quote = split_pair(sym)
    return await av_price_fx(base, quote)

async def av_price_router(sym: str) -> Optional[float]:
    """Try FX/crypto first for 6-letter pairs (or ending in USD), else equity."""
    s = sym.upper().replace("-", "").replace("/", "")
    if len(s) == 6:
        return await av_price_fx(s[:3], s[3:])
    # common crypto forms like SOLUSD, ETHUSD
    if s.endswith("USD") and len(s) > 3:
        return await av_price_fx(s[:-3], "USD")
    # else treat as equity
    return await av_price_equity(s)

# ---------- Scan helpers (toy logic: just fetch price + basic guard) ----------
async def scan_symbols(kind: str, symbols: List[str]) -> List[str]:
    """Return list of text lines for a scan result."""
    if not symbols:
        return [f"⚠️ No symbols configured for **{kind}**."]
    out = []
    for sym in symbols:
        price = await av_price_router(sym)
        if price is None:
            out.append(f"• {sym}: _no data_")
        else:
            out.append(f"• {sym}: **{price:.4f}**")
    return out

# ---------- Commands ----------
@bot.event
async def on_ready():
    log.info("✅ Logged in as %s (%s)", bot.user, bot.user.id)
    # Start HTTP session
    global SESSION
    if SESSION is None:
        SESSION = aiohttp.ClientSession()

    # Start loops if enabled
    if AI_SCAN_LOOP and AV_KEY:
        crypto_loop.change_interval(minutes=int(os.getenv("AI_CRYPTO_MINS", "25") or "25"))
        stocks_loop.change_interval(minutes=int(os.getenv("AI_STOCKS_MINS", "45") or "45"))
        forex_loop.change_interval(minutes=int(os.getenv("AI_FOREX_MINS", "45") or "45"))
        crypto_loop.start()
        stocks_loop.start()
        forex_loop.start()
        log.info("🧠 AI scan loops started.")
    else:
        log.info("ℹ️ Loops disabled or AV key missing; use !scanonce / !scan* to test.")

@bot.command()
async def ping(ctx):
    await ctx.reply("Pong 🏓")

@bot.command(name="price")
async def price_cmd(ctx, symbol: str):
    """!price <symbol> — tries stocks/crypto/forex automatically."""
    p = await av_price_router(symbol)
    if p is None:
        await ctx.reply(f"Couldn’t fetch a price for `{symbol}`.")
    else:
        await ctx.reply(f"`{symbol.upper()}` = **{p:.6f}**")

@bot.command(name="envgrep")
async def envgrep_cmd(ctx, prefix: str):
    """!envgrep <PREFIX> — show env vars that start with prefix."""
    prefix = prefix.upper()
    keys = sorted([k for k in os.environ.keys() if k.upper().startswith(prefix)])
    if not keys:
        await ctx.reply(f"No env keys starting with `{prefix}` found.")
        return
    lines = [f"- **{k}** = `{os.getenv(k)}`" for k in keys]
    await ctx.reply("\n".join(lines))

@bot.command(name="debugwatchlists")
async def debugwatchlists_cmd(ctx):
    await ctx.reply(
        "Watchlists loaded:\n"
        f"- Crypto: `{WATCH_CRYPTO}`\n"
        f"- Stocks: `{WATCH_STOCKS}`\n"
        f"- Forex: `{WATCH_FOREX}`"
    )

@bot.command(name="scancrypto")
async def scancrypto_cmd(ctx):
    lines = await scan_symbols("crypto", WATCH_CRYPTO)
    await ctx.reply("\n".join(lines))

@bot.command(name="scanstocks")
async def scanstocks_cmd(ctx):
    lines = await scan_symbols("stocks", WATCH_STOCKS)
    await ctx.reply("\n".join(lines))

@bot.command(name="scanforex")
async def scanforex_cmd(ctx):
    lines = await scan_symbols("forex", WATCH_FOREX)
    await ctx.reply("\n".join(lines))

@bot.command(name="scanall")
async def scanall_cmd(ctx):
    msgs = []
    msgs.append("**Crypto**")
    msgs += await scan_symbols("crypto", WATCH_CRYPTO)
    msgs.append("\n**Stocks**")
    msgs += await scan_symbols("stocks", WATCH_STOCKS)
    msgs.append("\n**Forex**")
    msgs += await scan_symbols("forex", WATCH_FOREX)
    await ctx.reply("\n".join(msgs))

# ---------- Loops (optional) ----------
async def _post_to_channel(channel_id: int, header: str, lines: List[str]):
    if not channel_id:
        return
    ch = bot.get_channel(channel_id)
    if ch:
        text = f"{header}\n" + "\n".join(lines)
        await ch.send(text)

@tasks.loop(minutes=25)
async def crypto_loop():
    lines = await scan_symbols("crypto", WATCH_CRYPTO)
    await _post_to_channel(CHANNEL_CRYPTO_ID, "🧠 **AI Crypto Scan**", lines)

@tasks.loop(minutes=45)
async def stocks_loop():
    lines = await scan_symbols("stocks", WATCH_STOCKS)
    await _post_to_channel(CHANNEL_STOCKS_ID, "🧠 **AI Stocks Scan**", lines)

@tasks.loop(minutes=45)
async def forex_loop():
    lines = await scan_symbols("forex", WATCH_FOREX)
    await _post_to_channel(CHANNEL_FOREX_ID, "🧠 **AI Forex Scan**", lines)

# ---------- Cleanup ----------
@bot.event
async def on_disconnect():
    log.info("Gateway disconnected.")

async def _shutdown():
    global SESSION
    if SESSION:
        await SESSION.close()
        SESSION = None

# -----------------------------
# AI Idea Engine (Direction / Confidence / TP1/TP2)
# -----------------------------
import os, math, time, datetime as dt
from typing import Dict, Optional
import pandas as pd
import numpy as np
import requests

AV_API = os.getenv("ALPHAVANTAGE_API_KEY", "").strip()

def _norm_symbol_for_fx(s: str):
    s2 = s.replace("-", "").upper()
    # e.g. EURUSD, USDJPY
    if len(s2) == 6 and s2.isalpha():
        return s2[:3], s2[3:]
    return None, None

def _is_crypto(s: str):
    s2 = s.replace("-", "").upper()
    return s2.endswith("USD") and not s2.isalpha()  # BTC-USD/ETH-USD style OR we'll normalize below

def _looks_crypto_pair(s: str):
    s2 = s.replace("-", "").upper()
    # BTCUSD, ETHUSD, SOLUSD, XRPUSD etc.
    return s2.endswith("USD") and s2.isalpha() and len(s2) >= 6 and (len(s2) <= 8)

def _av_equity_daily(symbol: str) -> Optional[pd.DataFrame]:
    if not AV_API:
        return None
    url = "https://www.alphavantage.co/query"
    params = {"function":"TIME_SERIES_DAILY_ADJUSTED","symbol":symbol,"outputsize":"compact","apikey":AV_API}
    r = requests.get(url, params=params, timeout=20)
    if r.status_code != 200: return None
    js = r.json()
    key = "Time Series (Daily)"
    if key not in js: return None
    df = (pd.DataFrame(js[key]).T
            .rename(columns={"1. open":"open","2. high":"high","3. low":"low","4. close":"close","6. volume":"volume"})
            .astype({"open":"float","high":"float","low":"float","close":"float","volume":"float"}))
    df.index = pd.to_datetime(df.index)
    return df.sort_index()

def _av_fx_daily(pair: str) -> Optional[pd.DataFrame]:
    if not AV_API:
        return None
    base, quote = _norm_symbol_for_fx(pair)
    if not base: return None
    url = "https://www.alphavantage.co/query"
    params = {"function":"FX_DAILY","from_symbol":base,"to_symbol":quote,"outputsize":"compact","apikey":AV_API}
    r = requests.get(url, params=params, timeout=20)
    if r.status_code != 200: return None
    js = r.json()
    key = "Time Series FX (Daily)"
    if key not in js: return None
    df = (pd.DataFrame(js[key]).T
            .rename(columns={"1. open":"open","2. high":"high","3. low":"low","4. close":"close"})
            .astype(float))
    df["volume"] = np.nan
    df.index = pd.to_datetime(df.index)
    return df.sort_index()

def _av_crypto_daily(symbol: str) -> Optional[pd.DataFrame]:
    """
    Accepts BTC-USD, BTCUSD, ETHUSD, etc. Normalizes to DIGITAL_CURRENCY_DAILY (market=USD).
    """
    if not AV_API:
        return None
    s = symbol.upper().replace("-", "")
    if not s.endswith("USD"):  # require USD market for AV crypto
        return None
    coin = s.replace("USD", "")
    url = "https://www.alphavantage.co/query"
    params = {"function":"DIGITAL_CURRENCY_DAILY","symbol":coin,"market":"USD","apikey":AV_API}
    r = requests.get(url, params=params, timeout=20)
    if r.status_code != 200: return None
    js = r.json()
    key = "Time Series (Digital Currency Daily)"
    if key not in js: return None
    df = pd.DataFrame(js[key]).T
    # AV crypto columns are like: "1a. open (USD)", "2a. high (USD)", ...
    rename = {
        "1a. open (USD)":"open",
        "2a. high (USD)":"high",
        "3a. low (USD)":"low",
        "4a. close (USD)":"close",
        "5. volume":"volume"
    }
    df = df.rename(columns=rename)[["open","high","low","close","volume"]].astype(float)
    df.index = pd.to_datetime(df.index)
    return df.sort_index()

def fetch_daily_ohlc(symbol: str) -> Optional[pd.DataFrame]:
    """
    Try Alpha Vantage for: Equities, FX, Crypto-USD.
    Returns daily OHLC sorted ascending, or None.
    """
    s = symbol.upper()
    # Try FX first if it looks like a 6-letter pair
    base, quote = _norm_symbol_for_fx(s)
    if base:
        df = _av_fx_daily(s)
        if df is not None and len(df) >= 50: return df

    # Crypto (USD market)
    if _looks_crypto_pair(s) or _is_crypto(s):
        df = _av_crypto_daily(s)
        if df is not None and len(df) >= 50: return df

    # Equity fallback
    df = _av_equity_daily(s)
    if df is not None and len(df) >= 50: return df

    return None

def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()

def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = (delta.clip(lower=0)).rolling(length).mean()
    loss = (-delta.clip(upper=0)).rolling(length).mean()
    rs = gain / (loss.replace(0, np.nan))
    out = 100 - (100 / (1 + rs))
    return out.fillna(50)

def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.rolling(length).mean()

def macd(series: pd.Series, fast=12, slow=26, signal=9):
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def score_and_signal(df: pd.DataFrame, timing: str = None) -> Optional[Dict]:
    """
    Produce direction (Bullish/Bearish), confidence 0-100, entry/sl/tp1/tp2, and a few notes.
    timing: EARLY / CONFIRMED / HYBRID (reads SIGNAL_TIMING env if None)
    """
    timing = (timing or os.getenv("SIGNAL_TIMING", "HYBRID")).upper()
    close = df["close"]
    ema20 = ema(close, 20)
    ema50 = ema(close, 50)
    rsi14 = rsi(close, 14)
    macd_line, macd_sig, macd_hist = macd(close)
    atr14 = atr(df, 14)

    last = df.index[-1]
    c = float(close.iloc[-1])
    e20 = float(ema20.iloc[-1])
    e50 = float(ema50.iloc[-1])
    r = float(rsi14.iloc[-1])
    m = float(macd_line.iloc[-1])
    ms = float(macd_sig.iloc[-1])
    h = float(macd_hist.iloc[-1])
    a = float(atr14.iloc[-1]) if not math.isnan(atr14.iloc[-1]) else None

    if any(map(lambda x: x is None or math.isnan(x), [c,e20,e50,r,m,ms,h])) or a is None:
        return None

    # Direction logic
    trend_up = e20 > e50
    macd_up = m > ms
    trend_down = e20 < e50
    macd_down = m < ms

    # Confirmation gates
    early_ok = (trend_up or trend_down)
    confirmed_ok = (trend_up and macd_up) or (trend_down and macd_down)

    if timing == "EARLY":
        condition = early_ok
    elif timing == "CONFIRMED":
        condition = confirmed_ok
    else:
        # HYBRID: allow early but penalize confidence a bit, reward if confirmed
        condition = early_ok or confirmed_ok

    if not condition:
        return None

    direction = "Bullish" if trend_up else "Bearish"

    # Confidence 0-100: blend of EMA separation, MACD histogram, and RSI distance from 50
    ema_sep = abs(e20 - e50) / c  # normalized
    macd_strength = abs(h)
    rsi_centered = abs(r - 50) / 50.0  # 0..1

    base_score = (
        50.0 * min(ema_sep * 200, 1.0) +         # big weight on clear trend
        30.0 * min(macd_strength * 10, 1.0) +    # momentum
        20.0 * min(rsi_centered, 1.0)            # distance from neutral
    )

    if timing == "HYBRID":
        if confirmed_ok: base_score += 5
        else: base_score -= 5

    score = max(0, min(100, round(base_score, 1)))

    # TP/SL (2TP by default)
    tp_mode = os.getenv("SIGNAL_TP_MODE", "2TP").upper()  # "2TP" or "1TP"
    rr1 = float(os.getenv("TP1_RR", "1.0"))  # risk ratio for TP1
    rr2 = float(os.getenv("TP2_RR", "2.0"))  # risk ratio for TP2

    # Basic swing SL by ATR
    if direction == "Bullish":
        sl = c - a
        rr_unit = (c - sl)
        tp1 = c + rr1 * rr_unit
        tp2 = c + rr2 * rr_unit
    else:
        sl = c + a
        rr_unit = (sl - c)
        tp1 = c - rr1 * rr_unit
        tp2 = c - rr2 * rr_unit

    notes = []
    notes.append(f"EMA20{'> ' if e20>e50 else '<='}EMA50")
    notes.append(f"MACD{'↑' if macd_up else '↓'} ({'conf' if confirmed_ok else 'early'})")
    notes.append(f"RSI14={round(r,1)}")
    notes.append(f"ATR14≈{round(a,4)}")

    out = {
        "when": last,
        "direction": direction,
        "confidence": score,
        "entry": c,
        "sl": round(sl, 4),
        "tp1": round(tp1, 4),
        "tp2": round(tp2, 4),
        "tp_mode": tp_mode,
        "notes": ", ".join(notes)
    }
    if tp_mode == "1TP":
        out.pop("tp2", None)
    return out

def format_signal_text(symbol: str, s: Dict) -> str:
    if not s:
        return f"• **{symbol}** — _no tradable setup right now_"
    d = s["direction"]
    emoji = "🟢" if d == "Bullish" else "🔴"
    conf = s["confidence"]
    entry = s["entry"]; sl = s["sl"]; tp1 = s["tp1"]; tp2 = s.get("tp2")
    line1 = f"{emoji} **{symbol}** — **{d}** | Confidence **{conf}%**"
    line2 = f"Entry ~ `{round(entry,4)}` | SL `{sl}` | TP1 `{tp1}`"
    if tp2 is not None:
        line2 += f" | TP2 `{tp2}`"
    line3 = f"Notes: {s['notes']}"
    return f"{line1}\n{line2}\n{line3}"

# ---------- Commands ----------
@bot.command(name="aiidea")
async def aiidea(ctx, symbol: str):
    """Run AI idea engine on a single symbol (daily timeframe)."""
    await ctx.trigger_typing()
    df = fetch_daily_ohlc(symbol)
    if df is None or len(df) < 50:
        return await ctx.reply(f"Couldn't load data for **{symbol}** (Alpha Vantage).")
    res = score_and_signal(df)
    msg = format_signal_text(symbol.upper(), res)
    await ctx.reply(msg)

@bot.command(name="aitop")
async def aitop(ctx):
    """Pick the top idea from each watchlist and print it."""
    await ctx.trigger_typing()
    groups = {
        "Crypto": os.getenv("AIWATCH_CRYPTO_TICKERS", ""),
        "Stocks": os.getenv("AIWATCH_STOCKS_TICKERS", ""),
        "Forex":  os.getenv("AIWATCH_FOREX_TICKERS", "")
    }
    chunks = []
    for name, tickers in groups.items():
        best = None
        best_sym = None
        for s in [t.strip() for t in tickers.split(",") if t.strip()]:
            df = fetch_daily_ohlc(s)
            if df is None or len(df) < 50:
                continue
            res = score_and_signal(df)
            if not res: 
                continue
            if (best is None) or (res["confidence"] > best["confidence"]):
                best, best_sym = res, s.upper()
            # Alpha Vantage free tier: avoid hammering the API
            time.sleep(12)  # ~5 calls/min safety
        if best:
            chunks.append(f"**{name} Top Idea**\n" + format_signal_text(best_sym, best))
        else:
            chunks.append(f"**{name} Top Idea**\n• _no tradable setup right now_")
    await ctx.reply("\n\n".join(chunks))

# ---------- Run ----------
try:
    bot.run(TOKEN)
finally:
    # bot.run blocks; this finally executes after shutdown
    if SESSION and not SESSION.closed:
        try:
            asyncio.get_event_loop().run_until_complete(_shutdown())
        except Exception:
            pass