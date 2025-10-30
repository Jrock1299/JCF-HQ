import os
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional

import aiohttp
import discord
from discord.ext import commands, tasks

# ----------------------------
# Logging
# ----------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)8s] %(name)s: %(message)s")
log = logging.getLogger("ai-bot")

# ----------------------------
# ENV / Config
# ----------------------------
TOKEN = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("BOT_TOKEN")

# Channel IDs (strings or ints both ok)
CHAN_SIGNALS = int(os.getenv("CHAN_SIGNALS_ID", "0") or "0")
CHAN_SYSTEM  = int(os.getenv("CHAN_SYSTEM_ID",  "0") or "0")

# Alpha Vantage (for forex)
AV_KEY = os.getenv("ALPHAVANTAGE_API_KEY") or os.getenv("ALPHA_VANTAGE_API_KEY") or ""

# Loop toggles and cadence (minutes). Hard-looped by default as requested.
AI_CRYPTO_LOOP = os.getenv("AI_CRYPTO_LOOP", "1") == "1"
AI_FOREX_LOOP  = os.getenv("AI_FOREX_LOOP",  "1") == "1"

CRYPTO_EVERY_MIN = int(os.getenv("AI_CRYPTO_EVERY_MIN", "25"))
FOREX_EVERY_MIN  = int(os.getenv("AI_FOREX_EVERY_MIN",  "45"))

# Thresholds (can tweak from Railway)
CRYPTO_MIN_STARS     = float(os.getenv("AI_CRYPTO_MIN_STARS", "2"))
CRYPTO_MIN_CONF      = float(os.getenv("AI_CRYPTO_MIN_CONF",  "0.50"))
CRYPTO_MIN_STRENGTH  = float(os.getenv("AI_CRYPTO_MIN_STRENGTH", "2.5"))

FOREX_MIN_STARS      = float(os.getenv("AI_FOREX_MIN_STARS", "2"))
FOREX_MIN_CONF       = float(os.getenv("AI_FOREX_MIN_CONF",  "0.50"))
FOREX_MIN_STRENGTH   = float(os.getenv("AI_FOREX_MIN_STRENGTH", "2.0"))

# Lists
def _parse_list(name: str, default: str = "") -> List[str]:
    raw = os.getenv(name, default)
    if not raw:
        return []
    return [t.strip().upper() for t in raw.split(",") if t.strip()]

CRYPTO_LIST = _parse_list("AI_CRYPTO_AI_TICKERS")  # e.g. XRP,ETH,SOL,SUI,ADA,LINK,HBAR
FOREX_LIST  = _parse_list("AI_FOREX_AI_TICKERS")   # e.g. USDJPY,EURUSD,GBPUSD,XAUUSD

# ----------------------------
# Discord bot
# ----------------------------
intents = discord.Intents.none()
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# ----------------------------
# HTTP Session (shared)
# ----------------------------
_session: Optional[aiohttp.ClientSession] = None

async def get_http() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
    return _session

# ----------------------------
# CoinGecko helpers (Crypto)
# ----------------------------
# Map common symbols -> CoinGecko IDs
CG_IDS: Dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "XRP": "ripple",
    "ADA": "cardano",
    "LINK": "chainlink",
    "SUI": "sui",
    "HBAR": "hedera-hashgraph",
    # add more here as needed
}

def cg_id_for(sym: str) -> Optional[str]:
    s = sym.upper()
    return CG_IDS.get(s)

async def cg_simple_price(symbols: List[str]) -> Dict[str, Dict[str, float]]:
    """
    Returns {coingecko_id: {"usd": price, "usd_24h_change": pct}} for given symbols.
    """
    ids = []
    for s in symbols:
        cid = cg_id_for(s)
        if cid:
            ids.append(cid)
    if not ids:
        return {}

    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {
        "ids": ",".join(ids),
        "vs_currencies": "usd",
        "include_24hr_change": "true",
    }
    sess = await get_http()
    async with sess.get(url, params=params, headers={"Accept": "application/json"}) as r:
        if r.status != 200:
            log.error(f"[cg] bad status {r.status}")
            return {}
        return await r.json()

async def get_crypto_snapshot(sym: str) -> Optional[Tuple[float, float]]:
    """
    Returns (price_usd, change_24h_pct) or None
    """
    data = await cg_simple_price([sym])
    cid = cg_id_for(sym)
    if not cid:
        return None
    node = data.get(cid)
    if not node:
        return None
    price = float(node.get("usd", 0) or 0)
    chg   = float(node.get("usd_24h_change", 0) or 0)
    if price <= 0:
        return None
    return price, chg

# ----------------------------
# Alpha Vantage helpers (Forex)
# ----------------------------
def _fx_split(pair: str) -> Optional[Tuple[str, str]]:
    p = pair.upper()
    if len(p) == 6 and p.isalpha():  # e.g. EURUSD
        return (p[:3], p[3:])
    if len(p) == 7 and p.endswith("USD") and p.startswith("XAU"):  # crude guard for XAUUSD textual variants
        return ("XAU", "USD")
    if len(p) == 6 and p.startswith("X") and p.endswith("USD"):    # XAUUSD -> handled above anyway
        return (p[:3], p[3:])
    if p == "XAUUSD":
        return ("XAU", "USD")
    # fallbacks like USDJPY, GBPUSD, etc.
    if len(p) == 6:
        return (p[:3], p[3:])
    return None

async def av_fx_rate(pair: str) -> Optional[float]:
    if not AV_KEY:
        log.warning("[av] missing API key")
        return None
    cur = _fx_split(pair)
    if not cur:
        return None
    frm, to = cur
    url = "https://www.alphavantage.co/query"
    params = {"function": "CURRENCY_EXCHANGE_RATE", "from_currency": frm, "to_currency": to, "apikey": AV_KEY}
    sess = await get_http()
    async with sess.get(url, params=params) as r:
        if r.status != 200:
            log.error(f"[av] bad status {r.status} for {pair}")
            return None
        j = await r.json()
    node = j.get("Realtime Currency Exchange Rate") or {}
    price = node.get("5. Exchange Rate")
    try:
        return float(price) if price else None
    except Exception:
        return None

# ----------------------------
# Scoring / Filters
# ----------------------------
def score_crypto(chg24: float) -> Tuple[int, float, float, Dict[str, float]]:
    """
    Turn 24h % change into stars/conf/strength.
    Very simple but effective for initial signal gating.
    """
    strength = abs(chg24)
    # confidence increases with absolute move
    if strength >= 6:
        conf = 0.75
        stars = 4
    elif strength >= 3:
        conf = 0.62
        stars = 3
    elif strength >= 1.5:
        conf = 0.55
        stars = 2
    else:
        conf = 0.45
        stars = 1
    return stars, conf, strength, {"chg24": chg24}

def score_forex(rate: float) -> Tuple[int, float, float, Dict[str, float]]:
    """
    Minimal placeholder: we only have spot; give modest confidence.
    (We’ll upgrade to intraday momentum later.)
    """
    if rate <= 0:
        return 0, 0.0, 0.0, {"rate": rate}
    # Neutral baseline
    return 3, 0.60, 1.8, {"rate": rate}

def passes_gate(kind: str, stars: int, conf: float, strength: float) -> bool:
    if kind == "crypto":
        return (stars >= CRYPTO_MIN_STARS and conf >= CRYPTO_MIN_CONF and strength >= CRYPTO_MIN_STRENGTH)
    if kind == "forex":
        return (stars >= FOREX_MIN_STARS and conf >= FOREX_MIN_CONF and strength >= FOREX_MIN_STRENGTH)
    return False

def stars_bar(n: int, out_of: int = 5) -> str:
    n = max(0, min(n, out_of))
    return "★" * n + "☆" * (out_of - n)

# ----------------------------
# Formatting
# ----------------------------
def fmt_signal(kind: str, sym: str, price: float, stars: int, conf: float, strength: float, metrics: Dict[str, float]) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"**[{kind.upper()}] {sym}** — ${price:,.4f}" if kind == "crypto" else f"**[{kind.upper()}] {sym}** — {price:,.5f}",
        f"{stars_bar(stars)}  |  Conf: {conf:.2f}  |  Strength: {strength:.2f}",
    ]
    if kind == "crypto" and "chg24" in metrics:
        lines.append(f"24h: {metrics['chg24']:+.2f}%")
    lines.append(f"*{ts}*")
    return "\n".join(lines)

# ----------------------------
# Core scan
# ----------------------------
async def scan_crypto(symbols: List[str]) -> List[str]:
    msgs = []
    for sym in symbols:
        snap = await get_crypto_snapshot(sym)
        if not snap:
            log.info(f"[crypto] {sym} -> no data")
            await asyncio.sleep(0.3)
            continue
        price, chg24 = snap
        stars, conf, strength, metrics = score_crypto(chg24)
        if not passes_gate("crypto", stars, conf, strength):
            log.info(f"[filter] crypto {sym}: blocked stars={stars} conf={conf:.2f} strength={strength:.2f}")
            await asyncio.sleep(0.15)
            continue
        msgs.append(fmt_signal("crypto", sym, price, stars, conf, strength, metrics))
        await asyncio.sleep(0.15)
    return msgs

async def scan_forex(pairs: List[str]) -> List[str]:
    msgs = []
    for pair in pairs:
        rate = await av_fx_rate(pair)
        if rate is None:
            log.info(f"[forex] {pair} -> no data")
            await asyncio.sleep(0.3)
            continue
        stars, conf, strength, metrics = score_forex(rate)
        if not passes_gate("forex", stars, conf, strength):
            log.info(f"[filter] forex {pair}: blocked stars={stars} conf={conf:.2f} strength={strength:.2f}")
            await asyncio.sleep(0.15)
            continue
        msgs.append(fmt_signal("forex", pair, rate, stars, conf, strength, metrics))
        await asyncio.sleep(0.15)
    return msgs

async def post_to_channel(channel_id: int, messages: List[str]):
    if not channel_id or not messages:
        return
    ch = bot.get_channel(channel_id)
    if not ch:
        log.warning(f"[discord] channel {channel_id} not found")
        return
    # batch if needed
    chunk = []
    size = 0
    for m in messages:
        if size + len(m) > 1800:
            await ch.send("\n\n".join(chunk))
            chunk, size = [], 0
        chunk.append(m)
        size += len(m)
    if chunk:
        await ch.send("\n\n".join(chunk))

# ----------------------------
# Commands
# ----------------------------
@bot.command(name="ping")
async def ping(ctx: commands.Context):
    await ctx.reply("pong")

@bot.command(name="scancrypto")
async def cmd_scancrypto(ctx: commands.Context):
    msgs = await scan_crypto(CRYPTO_LIST)
    if msgs:
        await ctx.reply("\n\n".join(msgs))
    else:
        await ctx.reply("No crypto signals passed the filters.")

@bot.command(name="scanforex")
async def cmd_scanforex(ctx: commands.Context):
    msgs = await scan_forex(FOREX_LIST)
    if msgs:
        await ctx.reply("\n\n".join(msgs))
    else:
        await ctx.reply("No forex signals passed the filters.")

@bot.command(name="scanall")
async def cmd_scanall(ctx: commands.Context):
    out = []
    out += await scan_crypto(CRYPTO_LIST)
    out += await scan_forex(FOREX_LIST)
    if out:
        await ctx.reply("\n\n".join(out))
    else:
        await ctx.reply("No signals passed the filters.")

# ----------------------------
# Loops (hard-looped as requested)
# ----------------------------
@tasks.loop(minutes=CRYPTO_EVERY_MIN)
async def crypto_loop():
    if not AI_CRYPTO_LOOP or not CRYPTO_LIST:
        return
    msgs = await scan_crypto(CRYPTO_LIST)
    await post_to_channel(CHAN_SIGNALS, msgs)

@crypto_loop.before_loop
async def _before_crypto_loop():
    await bot.wait_until_ready()

@tasks.loop(minutes=FOREX_EVERY_MIN)
async def forex_loop():
    if not AI_FOREX_LOOP or not FOREX_LIST:
        return
    msgs = await scan_forex(FOREX_LIST)
    await post_to_channel(CHAN_SIGNALS, msgs)

@forex_loop.before_loop
async def _before_forex_loop():
    await bot.wait_until_ready()

# ----------------------------
# Boot
# ----------------------------
@bot.event
async def on_ready():
    log.info(f"✅ Logged in as {bot.user} ({bot.user.id})")
    log.info("🧠 AI scan loops status:")
    log.info(f"    - Crypto loop: {AI_CRYPTO_LOOP} every {CRYPTO_EVERY_MIN}m, symbols={CRYPTO_LIST}")
    log.info(f"    - Forex loop:  {AI_FOREX_LOOP} every {FOREX_EVERY_MIN}m, symbols={FOREX_LIST}")
    if AI_CRYPTO_LOOP:
        crypto_loop.start()
    if AI_FOREX_LOOP:
        forex_loop.start()
    sys = bot.get_channel(CHAN_SYSTEM) if CHAN_SYSTEM else None
    if sys:
        await sys.send("✅ Bot online. Crypto via CoinGecko; Forex via Alpha Vantage. Stocks paused.")

async def _close_http():
    global _session
    if _session and not _session.closed:
        await _session.close()

async def _amain():
    try:
        await bot.start(TOKEN)
    finally:
        await _close_http()

if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Missing DISCORD_BOT_TOKEN")
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        pass