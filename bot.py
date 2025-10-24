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