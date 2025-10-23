import os
os.environ["DISCORD_NO_AUDIO"] = "1"

import asyncio
import json
import time
from typing import Any, Dict, List, Optional

import discord
from discord.ext import commands

# -------- Discord Bot Setup --------
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None  # avoid collision with built-in help
)

TOKEN = os.getenv("DISCORD_TOKEN")
ANNOUNCE_CHANNEL_ID = os.getenv("ANNOUNCE_CHANNEL_ID")
ANNOUNCE_CHANNEL_ID = int(ANNOUNCE_CHANNEL_ID) if ANNOUNCE_CHANNEL_ID and ANNOUNCE_CHANNEL_ID.isdigit() else None

# -------- Live Price Helpers --------
import requests
import yfinance as yf

COINGECKO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "XRP": "ripple",
    "LINK": "chainlink",
    "ADA": "cardano",
    # add more here if you expand your crypto watchlist
}

def fetch_price_crypto(symbol: str) -> Optional[float]:
    """
    Fetch spot USD price from CoinGecko for a common ticker (BTC/ETH/SOL...).
    """
    sym = symbol.upper().replace("USDT","").replace("/","").strip()
    cid = COINGECKO_IDS.get(sym)
    if not cid:
        return None
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": cid, "vs_currencies": "usd"},
            timeout=6,
        )
        r.raise_for_status()
        return float(r.json()[cid]["usd"])
    except Exception:
        return None

def fetch_price_stock(symbol: str) -> Optional[float]:
    """
    Fetch last price from Yahoo Finance.
    """
    try:
        t = yf.Ticker(symbol)
        p = t.fast_info.last_price or t.fast_info.regular_market_price
        return float(p) if p is not None else None
    except Exception:
        return None

# -------- Formatting Helpers --------
def fmt_price(v: Any) -> str:
    if v is None:
        return "n/a"
    try:
        val = float(v)
        if val < 1:
            return f"${val:,.6f}"
        if val < 100:
            return f"${val:,.4f}"
        return f"${val:,.2f}"
    except:
        return str(v)

def fmt_pct(x: float) -> str:
    try:
        return f"{x*100:.2f}%"
    except:
        return "n/a"

def format_signal_b(
    symbol: str,
    side: str,
    entry: Optional[float],
    sl: Optional[float],
    confidence: float,
    timeframe: str,
    reasons: List[str],
    stage: str = "CONFIRMED",  # or "EARLY"
    tp1: Optional[float] = None,
    tp2: Optional[float] = None,
) -> str:
    """
    Clean, compact card-style text. Assumes entry/sl/tps are numeric when possible.
    """
    side = side.upper()
    header_emoji = "🟢" if side.startswith("L") else "🔴"
    title = f"{header_emoji} **{symbol} {side}** — {stage} Setup ({timeframe})"

    lines = [title]
    lines.append(f"• Entry: {fmt_price(entry)}")
    lines.append(f"• Stop:  {fmt_price(sl)}")

    if tp1 is not None:
        lines.append(f"• TP1:   {fmt_price(tp1)}")
    if tp2 is not None:
        lines.append(f"• TP2:   {fmt_price(tp2)}")

    lines.append(f"• Confidence: {confidence:.2f}")

    if reasons:
        bullet = "\n".join([f"   - {r}" for r in reasons[:5]])
        lines.append("• Why:\n" + bullet)

    lines.append("—")
    lines.append("_Use risk management. Not financial advice._")
    return "\n".join(lines)

# -------- AI Analyzer Bridge --------
def call_analyzer(symbol: str, domain: str) -> Dict[str, Any]:
    """
    Reuse your EXISTING analyzer from !scanonce if it exists.
    We try common names; if not found, return a benign 'no signal'.
    Expected return keys if available: side, score, entry, sl, tf, reasons, stage, tp1, tp2
    """
    # try to find a function you already have wired from your earlier !scanonce
    for name in ("analyze_symbol", "ai_analyze_symbol", "ai_select_for_symbol", "scan_one_symbol"):
        fn = globals().get(name)
        if callable(fn):
            try:
                return fn(symbol, domain)
            except Exception:
                pass

    # fallback: no signal
    return {
        "side": "LONG",
        "score": 0.0,
        "entry": None,
        "sl": None,
        "tf": "1H",
        "reasons": [],
        "stage": "EARLY",
        "tp1": None,
        "tp2": None,
    }

# -------- Discord Events & Commands --------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (id: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="JCF HQ online"))

    if ANNOUNCE_CHANNEL_ID:
        ch = bot.get_channel(ANNOUNCE_CHANNEL_ID)
        if ch:
            await ch.send("✅ **JCFWatchBot ONLINE** — AI scanning ready. Use `!scanonce` or `!scan crypto`.")

@bot.command()
async def ping(ctx):
    await ctx.reply("Pong 🏓")

# keep your working !scanonce command in your file if you already have it
# (we don't redefine it here to avoid conflicts)

@bot.command(name="scan")
async def scan_cmd(ctx, which: str = "crypto"):
    which = which.lower().strip()
    if which not in ("crypto", "stocks"):
        return await ctx.reply("Use `!scan crypto` or `!scan stocks`")

    # read watchlist from env
    wl_env = "WATCH_CRYPTO" if which == "crypto" else "WATCH_STOCKS"
    wl = os.getenv(wl_env, "")
    watch = [s.strip().upper() for s in wl.split(",") if s.strip()]
    if not watch:
        return await ctx.reply(f"No {which} watchlist set. Add `{wl_env}` in Railway.")

    threshold = float(os.getenv("AI_SCORE_THRESHOLD", "0.77"))

    await ctx.reply(f"🔎 Scanning **{which}** watchlist: {', '.join(watch)} …")

    found = 0
    for sym in watch:
        # ---- AI score/select
        ai = call_analyzer(sym, which)
        score = float(ai.get("score", 0.0))
        if score < threshold:
            continue

        side = ai.get("side", "LONG")
        tf = ai.get("tf", "1H")
        reasons = ai.get("reasons", [])
        stage = ai.get("stage", "CONFIRMED")

        # ---- Live price
        live = fetch_price_crypto(sym) if which == "crypto" else fetch_price_stock(sym)

        # prefer AI's entry/sl if numeric; otherwise use live
        entry = ai.get("entry")
        try:
            entry = float(entry) if entry is not None else None
        except:
            entry = None
        if entry is None and live is not None:
            entry = live

        sl = ai.get("sl")
        try:
            sl = float(sl) if sl is not None else None
        except:
            sl = None

        # If SL still missing, set a simple default based on domain
        if sl is None and entry is not None:
            if which == "crypto":
                # default 1.5% away for demo; tune later via env if you like
                sl = entry * (0.985 if side.upper().startswith("L") else 1.015)
            else:
                sl = entry * (0.995 if side.upper().startswith("L") else 1.005)

        # Optional TP tiers (use AI if provided; else 1R/2R mock for formatting)
        tp1 = ai.get("tp1")
        tp2 = ai.get("tp2")
        for name in ("tp1", "tp2"):
            try:
                if locals()[name] is not None:
                    locals()[name] = float(locals()[name])
            except:
                locals()[name] = None

        # Build the card
        card = format_signal_b(
            symbol=sym,
            side=side,
            entry=entry,
            sl=sl,
            confidence=score,
            timeframe=tf,
            reasons=reasons if isinstance(reasons, list) else [],
            stage=stage if isinstance(stage, str) else "CONFIRMED",
            tp1=tp1,
            tp2=tp2,
        )

        try:
            await ctx.send(card)
            found += 1
        except Exception as e:
            await ctx.send(f"⚠️ Error posting {sym}: {e}")

    if found == 0:
        await ctx.send("ℹ️ No strong signals found on your watchlist.")

# -------- Boot --------
if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Missing DISCORD_TOKEN env var.")
    bot.run(TOKEN)