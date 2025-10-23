import os
os.environ["DISCORD_NO_AUDIO"] = "1"

import asyncio
from typing import Any, Dict, List, Optional

import discord
from discord.ext import commands

# ---------------- Discord Setup ----------------
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None  # avoid collision with built-in help
)

TOKEN = os.getenv("DISCORD_TOKEN")

# Optional announce channel for startup ping
ANNOUNCE_CHANNEL_ID = os.getenv("ANNOUNCE_CHANNEL_ID")
ANNOUNCE_CHANNEL_ID = int(ANNOUNCE_CHANNEL_ID) if ANNOUNCE_CHANNEL_ID and ANNOUNCE_CHANNEL_ID.isdigit() else None

# Target posting channels for autoscan
CHAN_CRYPTO_ID = os.getenv("CHANNEL_CRYPTO_SETUPS_ID")
CHAN_STOCKS_ID = os.getenv("CHANNEL_STOCK_SETUPS_ID")
CHAN_FOREX_ID = os.getenv("CHANNEL_FOREX_SETUPS_ID")
CHAN_CRYPTO_ID = int(CHAN_CRYPTO_ID) if CHAN_CRYPTO_ID and CHAN_CRYPTO_ID.isdigit() else None
CHAN_STOCKS_ID = int(CHAN_STOCKS_ID) if CHAN_STOCKS_ID and CHAN_STOCKS_ID.isdigit() else None
CHAN_FOREX_ID  = int(CHAN_FOREX_ID)  if CHAN_FOREX_ID  and CHAN_FOREX_ID.isdigit()  else None

# Autoscan controls
AI_SCAN_LOOP = os.getenv("AI_SCAN_LOOP", "0") == "1"
SCAN_INTERVAL_MIN = float(os.getenv("SCAN_INTERVAL_MIN", "20"))

# Beginner mode
BEGINNER_MODE = os.getenv("BEGINNER_MODE", "0") == "1"

# Watchlists
WATCH_CRYPTO = [s.strip().upper() for s in os.getenv("WATCH_CRYPTO", "").split(",") if s.strip()]
WATCH_STOCKS = [s.strip().upper() for s in os.getenv("WATCH_STOCKS", "").split(",") if s.strip()]
WATCH_FOREX  = [s.strip().upper() for s in os.getenv("WATCH_FOREX", "").split(",") if s.strip()]

AI_SCORE_THRESHOLD = float(os.getenv("AI_SCORE_THRESHOLD", "0.77"))

# ---------------- Price Helpers ----------------
import requests
import yfinance as yf

COINGECKO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "XRP": "ripple",
    "LINK": "chainlink",
    "ADA": "cardano",
    # add more symbols here if needed
}

def fetch_price_crypto(symbol: str) -> Optional[float]:
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
    try:
        t = yf.Ticker(symbol)
        p = t.fast_info.last_price or t.fast_info.regular_market_price
        return float(p) if p is not None else None
    except Exception:
        return None

# ---------------- Formatting ----------------
def fmt_price(v: Any) -> str:
    if v is None:
        return "n/a"
    try:
        val = float(v)
        if val < 1:   return f"${val:,.6f}"
        if val < 100: return f"${val:,.4f}"
        return f"${val:,.2f}"
    except:
        return str(v)

def format_signal_card(
    symbol: str,
    side: str,
    entry: Optional[float],
    sl: Optional[float],
    confidence: float,
    timeframe: str,
    reasons: List[str],
    stage: str = "CONFIRMED",
    tp1: Optional[float] = None,
    tp2: Optional[float] = None,
) -> str:
    side = side.upper()
    header_emoji = "🟢" if side.startswith("L") else "🔴"
    title = f"{header_emoji} **{symbol} {side}** — {stage} Setup ({timeframe})"
    lines = [title]
    lines.append(f"• Entry: {fmt_price(entry)}")
    lines.append(f"• Stop:  {fmt_price(sl)}")
    if tp1 is not None: lines.append(f"• TP1:   {fmt_price(tp1)}")
    if tp2 is not None: lines.append(f"• TP2:   {fmt_price(tp2)}")
    lines.append(f"• Confidence: {confidence:.2f}")
    if reasons:
        bullet = "\n".join([f"   - {r}" for r in reasons[:5]])
        lines.append("• Why:\n" + bullet)
    lines.append("—")
    lines.append("_Use risk management. Not financial advice._")
    return "\n".join(lines)

def add_beginner_explainer(symbol: str, side: str, entry: Optional[float], sl: Optional[float], tp1: Optional[float], tp2: Optional[float]) -> str:
    if not BEGINNER_MODE:
        return ""
    # Simple, friendly explainer
    expl = [
        "",
        "🧠 **Beginner Explain:**",
        f"- **{side.title()}** means we expect price to move {'up' if side.upper().startswith('L') else 'down'}.",
        f"- **Entry** is where we get in ({fmt_price(entry)}).",
        f"- **Stop (SL)** is where we exit if wrong to limit loss ({fmt_price(sl)}).",
    ]
    if tp1 is not None: expl.append(f"- **TP1** is first profit target ({fmt_price(tp1)}).")
    if tp2 is not None: expl.append(f"- **TP2** is second profit target ({fmt_price(tp2)}).")
    expl.append("- Keep risk small per trade. We’re playing a long game.")
    return "\n".join(expl)

# ---------------- AI Analyzer Bridge ----------------
def call_analyzer(symbol: str, domain: str) -> Dict[str, Any]:
    """
    Reuse your EXISTING analyzer from earlier (!scanonce).
    Expected keys: side, score, entry, sl, tf, reasons, stage, tp1, tp2
    """
    for name in ("analyze_symbol", "ai_analyze_symbol", "ai_select_for_symbol", "scan_one_symbol"):
        fn = globals().get(name)
        if callable(fn):
            try:
                return fn(symbol, domain)
            except Exception:
                pass
    # fallback no-signal
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

# ---------------- Core Scan Logic ----------------
async def scan_watchlist(domain: str, channel: discord.abc.Messageable):
    """
    Scan a single domain ('crypto' or 'stocks' or 'forex') and post qualified signals to channel.
    """
    domain = domain.lower()
    if domain == "crypto":
        watch = WATCH_CRYPTO
    elif domain == "stocks":
        watch = WATCH_STOCKS
    else:
        watch = WATCH_FOREX

    if not watch:
        await channel.send(f"ℹ️ No {domain} watchlist set.")
        return

    found = 0
    await channel.send(f"🔎 Scanning **{domain}** watchlist: {', '.join(watch)} …")

    for sym in watch:
        ai = call_analyzer(sym, domain)
        score = float(ai.get("score", 0.0))
        if score < AI_SCORE_THRESHOLD:
            continue

        side = ai.get("side", "LONG")
        tf   = ai.get("tf", "1H")
        reasons = ai.get("reasons", [])
        stage = ai.get("stage", "CONFIRMED")

        # Live price
        if domain == "crypto":
            live = fetch_price_crypto(sym)
        elif domain == "stocks":
            live = fetch_price_stock(sym)
        else:
            # quick placeholder: try yfinance for common FX tickers later (e.g. "EURUSD=X")
            live = None

        # Entry/SL
        def _num(x):
            try:
                return float(x) if x is not None else None
            except:
                return None

        entry = _num(ai.get("entry")) or live
        sl    = _num(ai.get("sl"))

        # Defaults if SL missing
        if sl is None and entry is not None:
            if domain == "crypto":
                sl = entry * (0.985 if side.upper().startswith("L") else 1.015)
            else:
                sl = entry * (0.995 if side.upper().startswith("L") else 1.005)

        tp1 = _num(ai.get("tp1"))
        tp2 = _num(ai.get("tp2"))

        card = format_signal_card(
            symbol=sym, side=side, entry=entry, sl=sl,
            confidence=score, timeframe=tf, reasons=reasons,
            stage=stage, tp1=tp1, tp2=tp2
        )
        expl = add_beginner_explainer(sym, side, entry, sl, tp1, tp2)

        try:
            await channel.send(card + (("\n" + expl) if expl else ""))
            found += 1
        except Exception as e:
            await channel.send(f"⚠️ Error posting {sym}: {e}")

    if found == 0:
        await channel.send("ℹ️ No strong signals found on your watchlist.")

# ---------------- Commands ----------------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (id: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="JCF HQ online"))
    if ANNOUNCE_CHANNEL_ID:
        ch = bot.get_channel(ANNOUNCE_CHANNEL_ID)
        if ch:
            await ch.send("✅ **JCFWatchBot ONLINE** — Auto-scan ready. Use `!scan crypto` or wait for autoscan.")

    # Start autoscan loop once
    if AI_SCAN_LOOP:
        # Ensure we don't start multiple loops on reconnects
        if not getattr(bot, "_scan_task_started", False):
            bot._scan_task_started = True
            bot.loop.create_task(background_scan_loop())

@bot.command()
async def ping(ctx):
    await ctx.reply("Pong 🏓")

@bot.command(name="scan")
async def scan_cmd(ctx, which: str = "crypto"):
    which = which.lower().strip()
    if which not in ("crypto", "stocks", "forex"):
        return await ctx.reply("Use `!scan crypto`, `!scan stocks`, or `!scan forex`")
    await scan_watchlist(which, ctx.channel)

# ---------------- Background Auto-Scan ----------------
async def background_scan_loop():
    await bot.wait_until_ready()
    print("⏱️ Auto-scan loop started")

    while not bot.is_closed():
        try:
            # Crypto first (you prioritized intraday crypto earlier)
            if CHAN_CRYPTO_ID:
                ch = bot.get_channel(CHAN_CRYPTO_ID)
                if ch: await scan_watchlist("crypto", ch)

            # Stocks (optional—only if channel provided)
            if CHAN_STOCKS_ID:
                ch = bot.get_channel(CHAN_STOCKS_ID)
                if ch: await scan_watchlist("stocks", ch)

            # Forex (optional—only if channel provided)
            if CHAN_FOREX_ID:
                ch = bot.get_channel(CHAN_FOREX_ID)
                if ch: await scan_watchlist("forex", ch)

        except Exception as e:
            print(f"[AutoScan] Error: {e}")

        # Sleep
        await asyncio.sleep(int(SCAN_INTERVAL_MIN * 60))

# ---------------- Boot ----------------
if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Missing DISCORD_TOKEN env var.")
    bot.run(TOKEN)