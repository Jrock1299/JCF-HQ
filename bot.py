# bot.py
import os
import asyncio
import logging
from typing import Dict, List

# Prevent discord.py from touching voice deps
os.environ["DISCORD_NO_AUDIO"] = "1"

import discord
from discord.ext import commands, tasks
import aiohttp

# -----------------------------
# Environment / Config
# -----------------------------
TOKEN = os.getenv("DISCORD_TOKEN")
CRYPTO_CHANNEL_ID = int(os.getenv("CRYPTO_SETUP_CHANNEL_ID", "0"))
COIN_IDS = [c.strip().lower() for c in os.getenv("COIN_IDS", "").split(",") if c.strip()]
CG_KEY = os.getenv("COINGECKO_API_KEY", "").strip()
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL_SEC", "300"))
RISK_MODE = os.getenv("RISK_MODE", "conservative").lower()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO),
                    format="%(levelname)s:%(name)s:%(message)s")
log = logging.getLogger("jcf-hq")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing")
if not CRYPTO_CHANNEL_ID:
    raise RuntimeError("CRYPTO_SETUP_CHANNEL_ID is missing")
if not COIN_IDS:
    raise RuntimeError("COIN_IDS is empty (comma-separated CoinGecko ids expected)")

# Decide CoinGecko base URL & headers based on key type
if CG_KEY.startswith("cg-pro-"):
    CG_BASE = "https://pro-api.coingecko.com/api/v3"
    CG_HEADERS = {"x-cg-pro-api-key": CG_KEY}
else:
    # Free/demo keys use the public endpoint (header not required/used)
    CG_BASE = "https://api.coingecko.com/api/v3"
    CG_HEADERS = {}

# -----------------------------
# Discord Bot
# -----------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ------------- Formatting helpers (Format A) -------------
def build_setup_message(symbol: str, direction: str,
                        entry_low: float, entry_high: float,
                        stop: float, tp1: float, tp2: float, tp3: float,
                        rr_to_tp2: float, confidence: int,
                        timeframe: str = "30m",
                        momentum: str = "Neutral",
                        risk_mode: str = "conservative") -> str:
    arrow = "🚀" if direction.lower().startswith("bull") else "🔻"
    return (
        "```"
        f"\n{arrow} {symbol.upper()} — {direction.title()} Setup Detected ({risk_mode})"
        f"\nTimeframe: {timeframe} | Momentum: {momentum}"
        "\n"
        f"\n• Entry Zone: {entry_low:.4f} – {entry_high:.4f}"
        f"\n• Stop Loss: {stop:.4f}"
        f"\n• Targets: {tp1:.4f} / {tp2:.4f} / {tp3:.4f}"
        f"\n• R:R (to TP2): {rr_to_tp2:.2f}"
        f"\n• Confidence: {confidence}%"
        "\n```"
    )

def make_levels(price: float, is_bull: bool, risk_mode: str):
    """
    Lightweight placeholder math for entry/stop/targets.
    Replace with real TA later (ATR/Keltner/EMA/etc.).
    """
    zone_pct = 0.006 if risk_mode == "conservative" else 0.010
    entry_low  = price * (1 - zone_pct/2)
    entry_high = price * (1 + zone_pct/2)

    stop = price * (0.985 if is_bull else 1.015)
    tp1  = price * (1.010 if is_bull else 0.990)
    tp2  = price * (1.020 if is_bull else 0.980)
    tp3  = price * (1.035 if is_bull else 0.965)

    rr_to_tp2 = abs(tp2 - price) / max(1e-9, abs(price - stop))
    momentum  = "Strong" if rr_to_tp2 >= 1.8 else "Moderate"
    confidence = max(60, min(95, 60 + int(20 * rr_to_tp2)))

    return entry_low, entry_high, stop, tp1, tp2, tp3, rr_to_tp2, momentum, confidence

async def post_formatted_crypto_alert(channel: discord.TextChannel,
                                      symbol: str,
                                      price: float,
                                      is_bull: bool,
                                      risk_mode: str):
    entry_low, entry_high, stop, tp1, tp2, tp3, rr, momentum, conf = make_levels(price, is_bull, risk_mode)
    direction = "Bullish move" if is_bull else "Bearish move"
    msg = build_setup_message(symbol, direction, entry_low, entry_high, stop, tp1, tp2, tp3, rr, conf,
                              timeframe="30m", momentum=momentum, risk_mode=risk_mode)
    await channel.send(msg)

# ------------- CoinGecko client -------------
async def cg_simple_price(session: aiohttp.ClientSession, ids: List[str]) -> Dict:
    """
    Calls /simple/price for multiple ids with 24h change.
    Returns dict like:
      { "ethereum": {"usd": 3000.12, "usd_24h_change": 3.2}, ... }
    """
    url = f"{CG_BASE}/simple/price"
    params = {
        "ids": ",".join(ids),
        "vs_currencies": "usd",
        "include_24hr_change": "true",
    }
    async with session.get(url, params=params, headers=CG_HEADERS, timeout=20) as r:
        if r.status != 200:
            text = await r.text()
            raise aiohttp.ClientResponseError(r.request_info, r.history, status=r.status, message=text)
        return await r.json()

# ------------- Scanning task -------------
@tasks.loop(seconds=SCAN_INTERVAL)
async def crypto_scan_loop():
    await bot.wait_until_ready()
    ch = bot.get_channel(CRYPTO_CHANNEL_ID)
    if not isinstance(ch, discord.TextChannel):
        log.error("Crypto channel not found or wrong type: %s", CRYPTO_CHANNEL_ID)
        return

    try:
        async with aiohttp.ClientSession() as session:
            data = await cg_simple_price(session, COIN_IDS)
    except Exception as e:
        log.error("[scan] HTTPError: %s", e)
        return

    # Very simple “conservative” gate: only alert on strong ± moves
    # You can tighten/loosen per coin later.
    threshold = 5.0 if RISK_MODE == "conservative" else 3.0

    any_alerts = False
    for coin_id in COIN_IDS:
        info = data.get(coin_id)
        if not info:
            continue
        price = float(info.get("usd", 0.0) or 0.0)
        chg = float(info.get("usd_24h_change", 0.0) or 0.0)

        # Decide direction from 24h momentum
        if abs(chg) >= threshold and price > 0:
            is_bull = chg > 0
            symbol = coin_id.upper().replace("-", "")
            await post_formatted_crypto_alert(ch, symbol, price, is_bull, RISK_MODE)
            any_alerts = True

    if not any_alerts:
        await ch.send("`No notable crypto setups this scan.`")

# -----------------------------
# Events / Commands
# -----------------------------
@bot.event
async def on_ready():
    log.info("✅ Logged in as %s (%s)", bot.user, bot.user.id)
    await bot.change_presence(activity=discord.Game(name="JCF HQ online"))
    if not crypto_scan_loop.is_running():
        crypto_scan_loop.start()
        log.info("📡 crypto_scan_loop started: every %ss", SCAN_INTERVAL)

@bot.command(name="ping")
async def ping(ctx: commands.Context):
    await ctx.reply("Pong 🏓", mention_author=False)

@bot.command(name="status")
async def status_cmd(ctx: commands.Context):
    cfg = (
        f"```\n"
        f"Coins: {', '.join(COIN_IDS)}\n"
        f"Risk: {RISK_MODE}\n"
        f"Scan Interval: {SCAN_INTERVAL}s\n"
        f"CG Base: {CG_BASE}\n"
        f"Channel: {CRYPTO_CHANNEL_ID}\n"
        f"```"
    )
    await ctx.reply(cfg, mention_author=False)

@bot.command(name="testcrypto")
async def testcrypto(ctx: commands.Context):
    # ETH sample test in the current channel
    price = 3000.0
    await post_formatted_crypto_alert(ctx.channel, "ETHUSDT", price, True, RISK_MODE)
    await ctx.reply("Test crypto alert sent ✅", mention_author=False)

# -----------------------------
# Run
# -----------------------------
bot.run(TOKEN)