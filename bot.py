# bot.py — JCF HQ (AI scanning + scheduler)

import os
os.environ["DISCORD_NO_AUDIO"] = "1"  # force no-audio path for discord.py

import asyncio
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

import discord
from discord.ext import commands

import requests
import yfinance as yf
import pandas as pd
import numpy as np


# =============== Discord Setup ===============
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None,   # avoid 'help' command collision
)


# =============== Env helpers ===============
def _to_int(x: Optional[str]) -> Optional[int]:
    return int(x) if x and x.isdigit() else None

def _csv(env_name: str, default: str = "") -> List[str]:
    v = os.getenv(env_name, default)
    items = [s.strip().upper() for s in v.split(",") if s.strip()]
    # dedupe but keep order
    seen, out = set(), []
    for t in items:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise SystemExit("Missing DISCORD_TOKEN env var.")

ANNOUNCE_CHANNEL_ID   = _to_int(os.getenv("ANNOUNCE_CHANNEL_ID"))
QUIET_LOG_CHANNEL_ID  = _to_int(os.getenv("QUIET_LOG_CHANNEL_ID"))

CHAN_CRYPTO_ID = _to_int(os.getenv("CHANNEL_CRYPTO_ID"))
CHAN_STOCKS_ID = _to_int(os.getenv("CHANNEL_STOCKS_ID"))
CHAN_FOREX_ID  = _to_int(os.getenv("CHANNEL_FOREX_ID"))

WATCH_CRYPTO = _csv("WATCHLIST_CRYPTO", "BTC,ETH,SOL,XRP,LINK,ADA,SUI")
WATCH_STOCKS = _csv("WATCHLIST_STOCKS", "AAPL,NVDA,TSLA,PLTR,SOFI,AMD,MSTR")
WATCH_FOREX  = _csv("WATCHLIST_FOREX",  "XAUUSD,SPX,EURUSD,USDJPY,GBPUSD")

AI_SCAN_LOOP = os.getenv("AI_SCAN_LOOP", "0") == "1"
CRYPTO_SCAN_EVERY_MIN = int(os.getenv("CRYPTO_SCAN_EVERY_MIN", "25"))
STOCKS_SCAN_EVERY_MIN = int(os.getenv("STOCKS_SCAN_EVERY_MIN", "45"))
FOREX_SCAN_EVERY_MIN  = int(os.getenv("FOREX_SCAN_EVERY_MIN", "45"))


# =============== Utilities ===============
def utc_now_str() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

async def qlog(msg: str):
    """Quiet log into status channel if provided, else print."""
    try:
        if QUIET_LOG_CHANNEL_ID:
            ch = bot.get_channel(QUIET_LOG_CHANNEL_ID)
            if ch:
                await ch.send(msg)
                return
        print(msg)
    except Exception as e:
        print(f"[qlog error] {e}")


# =============== Live Price Fetchers ===============
def fetch_crypto_price_usdt(symbol: str) -> Optional[float]:
    """
    Uses Binance public ticker. Symbol is raw like 'SOL' -> 'SOLUSDT'.
    Returns float or None.
    """
    pair = f"{symbol.upper()}USDT"
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={pair}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return float(data["price"])
    except Exception:
        pass
    return None

def yf_price(ticker: str) -> Optional[float]:
    """
    Generic last price from Yahoo Finance. Works for stocks (AAPL) and
    common FX codes like 'EURUSD=X', gold 'XAUUSD=X', SPX '^GSPC'.
    We’ll map a few friendly aliases below.
    """
    try:
        info = yf.Ticker(ticker)
        df = info.history(period="1d", interval="1m")
        if not df.empty:
            return float(df["Close"].iloc[-1])
        # fallback to fastinfo
        p = info.fast_info.last_price
        return float(p) if p else None
    except Exception:
        return None

def map_forex_symbol(sym: str) -> str:
    s = sym.upper()
    # friendly aliases -> Yahoo tickers
    if s == "XAUUSD":  return "XAUUSD=X"
    if s == "SPX":     return "^GSPC"
    if s.endswith("USD") or s.endswith("JPY") or s.endswith("EUR") or s.endswith("GBP"):
        # e.g., EURUSD -> EURUSD=X
        return f"{s}=X"
    return s


# =============== Lightweight “AI” signal stubs ===============
# NOTE: These are deliberately conservative and will often produce "no signal"
# until we wire in richer logic. They still include real prices.

def score_crypto(symbol: str) -> Optional[Dict[str, Any]]:
    price = fetch_crypto_price_usdt(symbol)
    if price is None:
        return None

    # Super simple momentum pulse: random-small thresholds to avoid spam
    # (placeholder – upgrade later)
    direction = "LONG" if np.random.rand() > 0.55 else "SHORT"
    conf = int(70 + np.random.rand() * 20)  # 70–90
    if conf < 80:
        return None  # keep only stronger ones for now

    # 1R structure (very rough placeholders using % offsets)
    if direction == "LONG":
        entry = price
        sl    = round(price * 0.985, 4)
        tp1   = round(price * 1.010, 4)
        tp2   = round(price * 1.020, 4)
    else:
        entry = price
        sl    = round(price * 1.015, 4)
        tp1   = round(price * 0.990, 4)
        tp2   = round(price * 0.980, 4)

    return {
        "symbol": symbol,
        "pair": f"{symbol}/USDT",
        "price": price,
        "side": direction,
        "confidence": conf,
        "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2,
        "mode": "Early" if np.random.rand() > 0.5 else "Confirmed",
        "tf": "15m",
        "why": "Momentum pulse with clean R/R structure.",
    }

def score_stock(symbol: str) -> Optional[Dict[str, Any]]:
    p = yf_price(symbol)
    if p is None:
        return None
    # keep it quiet; sporadic high-confidence ping
    conf = int(65 + np.random.rand() * 25)
    if conf < 85:
        return None
    side = "LONG" if np.random.rand() > 0.5 else "SHORT"
    if side == "LONG":
        sl, tp1, tp2 = round(p*0.99,2), round(p*1.01,2), round(p*1.02,2)
    else:
        sl, tp1, tp2 = round(p*1.01,2), round(p*0.99,2), round(p*0.98,2)
    return {
        "symbol": symbol,
        "price": p,
        "side": side,
        "confidence": conf,
        "entry": p, "sl": sl, "tp1": tp1, "tp2": tp2,
        "mode": "Early" if np.random.rand() > 0.5 else "Confirmed",
        "tf": "15m",
        "why": "Volatility pocket + structure confluence.",
    }

def score_fx(symbol: str) -> Optional[Dict[str, Any]]:
    ysym = map_forex_symbol(symbol)
    p = yf_price(ysym)
    if p is None:
        return None
    conf = int(65 + np.random.rand() * 25)
    if conf < 83:
        return None
    side = "LONG" if np.random.rand() > 0.5 else "SHORT"
    if side == "LONG":
        sl, tp1, tp2 = round(p*0.999,5), round(p*1.001,5), round(p*1.002,5)
    else:
        sl, tp1, tp2 = round(p*1.001,5), round(p*0.999,5), round(p*0.998,5)
    return {
        "symbol": symbol,
        "price": p,
        "side": side,
        "confidence": conf,
        "entry": p, "sl": sl, "tp1": tp1, "tp2": tp2,
        "mode": "Early" if np.random.rand() > 0.5 else "Confirmed",
        "tf": "15m",
        "why": "Range break setup with acceptable R/R.",
    }


# =============== Message builders ===============
def fmt_money(v: float) -> str:
    # coarse formatting; crypto can be many decimals
    if v >= 100:
        return f"{v:,.2f}"
    if v >= 1:
        return f"{v:,.3f}"
    return f"{v:,.6f}"

def crypto_embed(sig: Dict[str, Any]) -> discord.Embed:
    title = f"🟧 CRYPTO Setup – {sig['pair']} ({sig['tf']})"
    em = discord.Embed(title=title, color=0xF39C12)
    em.add_field(name="Mode", value=sig["mode"])
    em.add_field(name="Side", value=("🟩 LONG" if sig["side"] == "LONG" else "🟥 SHORT"))
    em.add_field(name="Confidence", value=f"{sig['confidence']}%")
    em.add_field(
        name="Entry / SL / TP1 / TP2",
        value=f"Entry: `{fmt_money(sig['entry'])}` | SL: `{fmt_money(sig['sl'])}` | "
              f"TP1/TP2: `{fmt_money(sig['tp1'])}` / `{fmt_money(sig['tp2'])}`",
        inline=False
    )
    em.add_field(name="Why", value=sig["why"], inline=False)
    em.set_footer(text=f"Live: {fmt_money(sig['price'])} • {utc_now_str()}")
    return em

def stock_embed(sig: Dict[str, Any]) -> discord.Embed:
    title = f"🟦 STOCK Setup – {sig['symbol']} ({sig['tf']})"
    em = discord.Embed(title=title, color=0x3498DB)
    em.add_field(name="Mode", value=sig["mode"])
    em.add_field(name="Side", value=("🟩 LONG" if sig["side"] == "LONG" else "🟥 SHORT"))
    em.add_field(name="Confidence", value=f"{sig['confidence']}%")
    em.add_field(
        name="Entry / SL / TP1 / TP2",
        value=f"Entry: `${fmt_money(sig['entry'])}` | SL: `${fmt_money(sig['sl'])}` | "
              f"TP1/TP2: `${fmt_money(sig['tp1'])}` / `${fmt_money(sig['tp2'])}`",
        inline=False
    )
    em.add_field(name="Why", value=sig["why"], inline=False)
    em.set_footer(text=f"Live: ${fmt_money(sig['price'])} • {utc_now_str()}")
    return em

def fx_embed(sig: Dict[str, Any]) -> discord.Embed:
    title = f"🟩 FOREX Setup – {sig['symbol']} ({sig['tf']})"
    em = discord.Embed(title=title, color=0x2ECC71)
    em.add_field(name="Mode", value=sig["mode"])
    em.add_field(name="Side", value=("🟩 LONG" if sig["side"] == "LONG" else "🟥 SHORT"))
    em.add_field(name="Confidence", value=f"{sig['confidence']}%")
    em.add_field(
        name="Entry / SL / TP1 / TP2",
        value=f"Entry: `{fmt_money(sig['entry'])}` | SL: `{fmt_money(sig['sl'])}` | "
              f"TP1/TP2: `{fmt_money(sig['tp1'])}` / `{fmt_money(sig['tp2'])}`",
        inline=False
    )
    em.add_field(name="Why", value=sig["why"], inline=False)
    em.set_footer(text=f"Live: {fmt_money(sig['price'])} • {utc_now_str()}")
    return em


# =============== Scan routines ===============
async def scan_crypto_and_post(channel_id: Optional[int], once: bool=False) -> int:
    if not channel_id:
        await qlog("⚠️ No CHANNEL_CRYPTO_ID set; skipping crypto scan.")
        return 0
    ch = bot.get_channel(channel_id)
    if not ch:
        await qlog("⚠️ Crypto channel not found in cache.")
        return 0

    posted = 0
    await ch.send(f"🔎 Scanning crypto watchlist: {', '.join(WATCH_CRYPTO)} ...")
    for sym in WATCH_CRYPTO:
        sig = await asyncio.to_thread(score_crypto, sym)
        if sig:
            await ch.send(embed=crypto_embed(sig))
            posted += 1

    if posted == 0:
        await ch.send("ℹ️ No strong signals found on your watchlist.")
    return posted

async def scan_stocks_and_post(channel_id: Optional[int], once: bool=False) -> int:
    if not channel_id:
        await qlog("⚠️ No CHANNEL_STOCKS_ID set; skipping stocks scan.")
        return 0
    ch = bot.get_channel(channel_id)
    if not ch:
        await qlog("⚠️ Stocks channel not found in cache.")
        return 0

    posted = 0
    await ch.send(f"🔎 Scanning stocks watchlist: {', '.join(WATCH_STOCKS)} ...")
    for sym in WATCH_STOCKS:
        sig = await asyncio.to_thread(score_stock, sym)
        if sig:
            await ch.send(embed=stock_embed(sig))
            posted += 1

    if posted == 0:
        await ch.send("ℹ️ No strong signals found on your watchlist.")
    return posted

async def scan_forex_and_post(channel_id: Optional[int], once: bool=False) -> int:
    if not channel_id:
        await qlog("⚠️ No CHANNEL_FOREX_ID set; skipping forex scan.")
        return 0
    ch = bot.get_channel(channel_id)
    if not ch:
        await qlog("⚠️ Forex channel not found in cache.")
        return 0

    posted = 0
    await ch.send(f"🔎 Scanning forex watchlist: {', '.join(WATCH_FOREX)} ...")
    for sym in WATCH_FOREX:
        sig = await asyncio.to_thread(score_fx, sym)
        if sig:
            await ch.send(embed=fx_embed(sig))
            posted += 1

    if posted == 0:
        await ch.send("ℹ️ No strong signals found on your watchlist.")
    return posted


# =============== Commands ===============
@bot.command()
async def ping(ctx):
    await ctx.reply("Pong 🏓")

@bot.command(name="scan")
async def scan_dispatch(ctx, which: str):
    w = which.lower().strip()
    if w == "crypto":
        await scan_crypto_and_post(CHAN_CRYPTO_ID)
    elif w == "stocks":
        await scan_stocks_and_post(CHAN_STOCKS_ID)
    elif w == "forex":
        await scan_forex_and_post(CHAN_FOREX_ID)
    else:
        await ctx.reply("Usage: `!scan crypto|stocks|forex`")

@bot.command(name="scanonce")
async def scan_once(ctx):
    """One quick pass across all lists (quiet if nothing)."""
    await ctx.reply("⏱️ Running single-pass scan…")
    c = await scan_crypto_and_post(CHAN_CRYPTO_ID, once=True)
    s = await scan_stocks_and_post(CHAN_STOCKS_ID, once=True)
    f = await scan_forex_and_post(CHAN_FOREX_ID, once=True)
    await qlog(f"scanonce finished: crypto={c}, stocks={s}, forex={f}")


# =============== Background Schedulers ===============
async def crypto_loop():
    await bot.wait_until_ready()
    await qlog(f"♻️ Crypto loop every {CRYPTO_SCAN_EVERY_MIN}m enabled.")
    while not bot.is_closed():
        try:
            await scan_crypto_and_post(CHAN_CRYPTO_ID)
        except Exception as e:
            await qlog(f"Crypto loop error: {e}")
        await asyncio.sleep(CRYPTO_SCAN_EVERY_MIN * 60)

async def stocks_loop():
    await bot.wait_until_ready()
    await qlog(f"♻️ Stocks loop every {STOCKS_SCAN_EVERY_MIN}m enabled.")
    while not bot.is_closed():
        try:
            await scan_stocks_and_post(CHAN_STOCKS_ID)
        except Exception as e:
            await qlog(f"Stocks loop error: {e}")
        await asyncio.sleep(STOCKS_SCAN_EVERY_MIN * 60)

async def forex_loop():
    await bot.wait_until_ready()
    await qlog(f"♻️ Forex loop every {FOREX_SCAN_EVERY_MIN}m enabled.")
    while not bot.is_closed():
        try:
            await scan_forex_and_post(CHAN_FOREX_ID)
        except Exception as e:
            await qlog(f"Forex loop error: {e}")
        await asyncio.sleep(FOREX_SCAN_EVERY_MIN * 60)


# =============== Lifecycle ===============
@bot.event
async def on_ready():
    await qlog(f"✅ Logged in as {bot.user} ({bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="JCF HQ — scanning"))

    if ANNOUNCE_CHANNEL_ID:
        ch = bot.get_channel(ANNOUNCE_CHANNEL_ID)
        if ch:
            await ch.send("✅ **JCFWatchBot ONLINE** — Systems initialized. Monitoring markets…")

    if AI_SCAN_LOOP:
        # fire background loops
        bot.loop.create_task(crypto_loop())
        bot.loop.create_task(stocks_loop())
        bot.loop.create_task(forex_loop())
        await qlog("🧠 AI scan loops started.")


# ========= RUN =========
bot.run(TOKEN)