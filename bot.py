import os
os.environ["DISCORD_NO_AUDIO"] = "1"

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import discord
from discord.ext import commands

# ---------------- Discord Setup ----------------
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None  # avoid help collision
)

TOKEN = os.getenv("DISCORD_TOKEN")

ANNOUNCE_CHANNEL_ID = os.getenv("ANNOUNCE_CHANNEL_ID")
ANNOUNCE_CHANNEL_ID = int(ANNOUNCE_CHANNEL_ID) if ANNOUNCE_CHANNEL_ID and ANNOUNCE_CHANNEL_ID.isdigit() else None

# Target posting channels for autoscan
CHAN_CRYPTO_ID = os.getenv("CHANNEL_CRYPTO_SETUPS_ID")
CHAN_STOCKS_ID = os.getenv("CHANNEL_STOCK_SETUPS_ID")
CHAN_FOREX_ID  = os.getenv("CHANNEL_FOREX_SETUPS_ID")
CHAN_CRYPTO_ID = int(CHAN_CRYPTO_ID) if CHAN_CRYPTO_ID and CHAN_CRYPTO_ID.isdigit() else None
CHAN_STOCKS_ID = int(CHAN_STOCKS_ID) if CHAN_STOCKS_ID and CHAN_STOCKS_ID.isdigit() else None
CHAN_FOREX_ID  = int(CHAN_FOREX_ID)  if CHAN_FOREX_ID  and CHAN_FOREX_ID.isdigit()  else None

# Autoscan controls
AI_SCAN_LOOP = os.getenv("AI_SCAN_LOOP", "0") == "1"
SCAN_INTERVAL_MIN = float(os.getenv("SCAN_INTERVAL_MIN", "20"))

# Beginner mode
BEGINNER_MODE = os.getenv("BEGINNER_MODE", "0") == "1"

# Session filters (UTC)
SESSION_FILTER_STOCKS = os.getenv("SESSION_FILTER_STOCKS", "0") == "1"
SESSION_FILTER_FOREX  = os.getenv("SESSION_FILTER_FOREX", "0") == "1"
STOCKS_SESSION_UTC = os.getenv("STOCKS_SESSION_UTC", "13:30-20:00")  # US core, UTC
FOREX_SESSION_UTC  = os.getenv("FOREX_SESSION_UTC", "07:00-16:00,13:00-21:00")  # London + overlap + NY, UTC

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
    expl = [
        "",
        "🧠 **Beginner Explain:**",
        f"- **{side.title()}** = we expect price to move {'up' if side.upper().startswith('L') else 'down'}.",
        f"- **Entry** is where we get in ({fmt_price(entry)}).",
        f"- **Stop (SL)** is where we exit if wrong ({fmt_price(sl)}).",
    ]
    if tp1 is not None: expl.append(f"- **TP1** = first profit target ({fmt_price(tp1)}).")
    if tp2 is not None: expl.append(f"- **TP2** = second profit target ({fmt_price(tp2)}).")
    expl.append("- Keep risk small. Long game wins.")
    return "\n".join(expl)

# ---------------- AI Analyzer Bridge ----------------
def call_analyzer(symbol: str, domain: str) -> Dict[str, Any]:
    # reuse prior analyzer if present
    for name in ("analyze_symbol", "ai_analyze_symbol", "ai_select_for_symbol", "scan_one_symbol"):
        fn = globals().get(name)
        if callable(fn):
            try:
                return fn(symbol, domain)
            except Exception:
                pass
    # fallback
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

# ---------------- Session Gating ----------------
def _parse_ranges(spec: str) -> List[tuple]:
    """
    "HH:MM-HH:MM,HH:MM-HH:MM" -> [(start_min,end_min), ...] in minutes-from-midnight
    """
    out = []
    for block in spec.split(","):
        block = block.strip()
        if not block: continue
        try:
            a,b = block.split("-")
            h1,m1 = [int(x) for x in a.split(":")]
            h2,m2 = [int(x) for x in b.split(":")]
            out.append((h1*60+m1, h2*60+m2))
        except Exception:
            continue
    return out

STOCKS_RANGES = _parse_ranges(STOCKS_SESSION_UTC)
FOREX_RANGES  = _parse_ranges(FOREX_SESSION_UTC)

def is_session_open(domain: str, now_utc: Optional[datetime]=None) -> bool:
    """
    Crypto: always True.
    Stocks: gate by STOCKS_SESSION_UTC if SESSION_FILTER_STOCKS=1 and weekday.
    Forex:  gate by FOREX_SESSION_UTC  if SESSION_FILTER_FOREX=1 and weekday (forex 24/5).
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    dow = now_utc.weekday()  # 0=Mon ... 6=Sun
    minutes = now_utc.hour*60 + now_utc.minute

    if domain == "crypto":
        return True  # 24/7

    if domain == "stocks":
        if not SESSION_FILTER_STOCKS:
            return True
        if dow >= 5:  # Sat/Sun closed
            return False
        for s,e in STOCKS_RANGES:
            if s <= minutes <= e:
                return True
        return False

    if domain == "forex":
        if not SESSION_FILTER_FOREX:
            return True
        if dow == 6:  # Sunday: often partial; keep it simple: closed
            return False
        # Monday open from Asia; but we're gating to London/NY windows for quality
        for s,e in FOREX_RANGES:
            if s <= minutes <= e:
                return True
        return False

    return True

# ---------------- TP/SL Tracking ----------------
# Simple in-memory open-trade registry (resets on redeploy; good enough for now)
OPEN_TRADES: Dict[str, Dict[str, Any]] = {}
# key = f"{domain}:{symbol}"
# value keys: side, entry, sl, tp1, tp2, posted (bool), closed (bool)

def register_open_trade(domain: str, symbol: str, side: str, entry: Optional[float], sl: Optional[float], tp1: Optional[float], tp2: Optional[float]):
    if entry is None or sl is None:
        return
    key = f"{domain}:{symbol.upper()}"
    OPEN_TRADES[key] = {
        "side": side.upper(),
        "entry": float(entry),
        "sl": float(sl),
        "tp1": float(tp1) if tp1 is not None else None,
        "tp2": float(tp2) if tp2 is not None else None,
        "closed": False,
    }

async def monitor_open_trades():
    """
    Every loop: check price vs entry/SL/TP1 for basic milestones and post updates.
    """
    for key, d in list(OPEN_TRADES.items()):
        if d.get("closed"):
            continue
        domain, symbol = key.split(":")
        # fetch live price
        if domain == "crypto":
            price = fetch_price_crypto(symbol)
        elif domain == "stocks":
            price = fetch_price_stock(symbol)
        else:
            price = None  # can extend to FX later

        if price is None:
            continue

        side = d["side"]
        entry = d["entry"]
        sl    = d["sl"]
        tp1   = d.get("tp1")

        # Determine status
        hit_tp1 = False
        hit_sl  = False
        if side.startswith("L"):
            if tp1 is not None and price >= tp1: hit_tp1 = True
            if price <= sl: hit_sl = True
        else:
            if tp1 is not None and price <= tp1: hit_tp1 = True
            if price >= sl: hit_sl = True

        # pick a channel to post updates (use the same domain channel)
        channel_id = CHAN_CRYPTO_ID if domain=="crypto" else (CHAN_STOCKS_ID if domain=="stocks" else CHAN_FOREX_ID)
        ch = bot.get_channel(channel_id) if channel_id else None

        if hit_tp1 and ch:
            await ch.send(f"✅ **{symbol} TP1 hit** at {fmt_price(price)} (entry {fmt_price(entry)})")
            # keep trade open for TP2 or manual closure

        if hit_sl and ch:
            await ch.send(f"🛑 **{symbol} SL hit** at {fmt_price(price)} (entry {fmt_price(entry)})")
            d["closed"] = True  # stop tracking after SL

# ---------------- Core Scan Logic ----------------
def _num(x):
    try: return float(x) if x is not None else None
    except: return None

async def scan_watchlist(domain: str, channel: discord.abc.Messageable):
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

    # session gating
    if not is_session_open(domain):
        await channel.send(f"⏳ {domain.title()} session closed right now (UTC rules). Skipping scan.")
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
            live = None  # extend for FX later

        entry = _num(ai.get("entry")) or live
        sl    = _num(ai.get("sl"))
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
            # Register trade for TP/SL monitoring if we have enough info
            register_open_trade(domain, sym, side, entry, sl, tp1, tp2)
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
            await ch.send("✅ **JCFWatchBot ONLINE** — Auto-scan + TP/SL tracking enabled.")

    if AI_SCAN_LOOP and not getattr(bot, "_scan_task_started", False):
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
            # First: monitor open trades for TP1/SL hits
            await monitor_open_trades()

            # Crypto (24/7)
            if CHAN_CRYPTO_ID:
                ch = bot.get_channel(CHAN_CRYPTO_ID)
                if ch: await scan_watchlist("crypto", ch)

            # Stocks (session gated)
            if CHAN_STOCKS_ID:
                ch = bot.get_channel(CHAN_STOCKS_ID)
                if ch: await scan_watchlist("stocks", ch)

            # Forex (session gated)
            if CHAN_FOREX_ID:
                ch = bot.get_channel(CHAN_FOREX_ID)
                if ch: await scan_watchlist("forex", ch)

        except Exception as e:
            print(f"[AutoScan] Error: {e}")

        await asyncio.sleep(int(SCAN_INTERVAL_MIN * 60))

# ---------------- Boot ----------------
if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Missing DISCORD_TOKEN env var.")
    bot.run(TOKEN)