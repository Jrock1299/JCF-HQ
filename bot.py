# bot.py  — JCF-HQ Crypto Setups (CoinGecko) ✅
# Env vars used (exact names):
# DISCORD_TOKEN, CRYPTO_SETUP_CHANNEL_ID, COINGECKO_API_KEY,
# COIN_IDS, RISK_MODE, SCAN_INTERVAL_SEC, LOG_LEVEL

import os
os.environ["DISCORD_NO_AUDIO"] = "1"  # avoid audio deps on hosts

import asyncio
import logging
from typing import List, Tuple

import requests
import discord
from discord.ext import commands, tasks

# ---------- Config from ENV ----------
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CRYPTO_SETUP_CHANNEL_ID = int(os.getenv("CRYPTO_SETUP_CHANNEL_ID", "0"))
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "")
COIN_IDS = [c.strip().lower() for c in os.getenv("COIN_IDS", "").split(",") if c.strip()]
RISK_MODE = os.getenv("RISK_MODE", "conservative").strip().lower()  # conservative|balanced|aggressive
SCAN_INTERVAL_SEC = int(os.getenv("SCAN_INTERVAL_SEC", "300"))  # default 5 min
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# ---------- Logging ----------
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
log = logging.getLogger("jcf-hq")

# ---------- Discord Setup ----------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- Helpers ----------
def threshold_for_risk(mode: str) -> float:
    """returns 24h % change threshold for signaling"""
    if mode == "aggressive":
        return 1.5
    if mode == "balanced":
        return 3.5
    return 6.0  # conservative (default)

def fetch_prices(coin_ids: List[str]) -> dict:
    """Call CoinGecko /simple/price for the given ids."""
    url = "https://api.coingecko.com/api/v3/simple/price"
    headers = {"x-cg-demo-api-key": COINGECKO_API_KEY}
    params = {
        "ids": ",".join(coin_ids),
        "vs_currencies": "usd",
        "include_24hr_change": "true"
    }
    r = requests.get(url, params=params, headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()

def analyze_setups(data: dict, risk_mode: str) -> List[Tuple[str, float, float]]:
    """Return list of (coin, price, change%) that exceed the risk threshold."""
    thr = threshold_for_risk(risk_mode)
    notable = []
    for coin, info in data.items():
        price = float(info.get("usd", 0) or 0)
        chg = float(info.get("usd_24h_change", 0) or 0)
        if abs(chg) >= thr and price > 0:
            notable.append((coin, price, chg))
    return notable

def fmt_signal(coin: str, price: float, chg: float) -> str:
    direction = "🚀 **BULLISH MOVE**" if chg >= 0 else "🔻 **BEARISH MOVE**"
    return (
        f"**{coin.upper()} — Setup Detected**\n"
        f"Price: **${price:,.4f}**\n"
        f"24h Change: **{chg:+.2f}%**\n"
        f"Risk Mode: `{RISK_MODE}`\n"
        f"{direction}"
    )

# ---------- Scanner Task ----------
@tasks.loop(seconds=SCAN_INTERVAL_SEC)
async def crypto_scan_loop():
    try:
        if not COIN_IDS:
            log.warning("No COIN_IDS set; skipping scan.")
            return
        data = fetch_prices(COIN_IDS)
        notable = analyze_setups(data, RISK_MODE)

        channel = bot.get_channel(CRYPTO_SETUP_CHANNEL_ID)
        if channel is None:
            log.error("CRYPTO_SETUP_CHANNEL_ID invalid or bot lacks access.")
            return

        if not notable:
            log.info("[scan] no notable crypto setups this cycle")
            return

        for coin, price, chg in notable:
            await channel.send(fmt_signal(coin, price, chg))

        log.info("[scan] posted %d crypto setups", len(notable))

    except requests.HTTPError as e:
        log.error("[scan] HTTPError: %s", e)
    except Exception as e:
        log.exception("[scan] unexpected error: %s", e)

# ---------- Bot Events & Commands ----------
@bot.event
async def on_ready():
    log.info("✅ Logged in as %s (%s)", bot.user, bot.user.id)
    # kick off the loop (start once)
    if not crypto_scan_loop.is_running():
        crypto_scan_loop.start()
        log.info("🔁 crypto_scan_loop started: every %ss", SCAN_INTERVAL_SEC)

@bot.command(name="status")
async def status(ctx: commands.Context):
    """Show live config status."""
    await ctx.reply(
        "**JCF-HQ Crypto Watch — Status**\n"
        f"Risk: `{RISK_MODE}` | Interval: `{SCAN_INTERVAL_SEC}s`\n"
        f"Coins: `{', '.join(COIN_IDS)}`\n"
        f"Channel: `{CRYPTO_SETUP_CHANNEL_ID}`\n"
        f"Loop running: `{crypto_scan_loop.is_running()}`"
    )

@bot.command(name="testcrypto")
async def testcrypto(ctx: commands.Context):
    """Push a sample alert to the setups channel."""
    channel = bot.get_channel(CRYPTO_SETUP_CHANNEL_ID) or ctx.channel
    await channel.send(
        "**ETHEREUM — Setup Detected (TEST)**\n"
        "Price: **$3,000.00**\n"
        "24h Change: **+6.20%**\n"
        f"Risk Mode: `{RISK_MODE}`\n"
        "🚀 **BULLISH MOVE**"
    )
    await ctx.reply("Test crypto alert sent ✅")

# ---------- Startup guards ----------
def _validate_env():
    problems = []
    if not DISCORD_TOKEN:
        problems.append("DISCORD_TOKEN missing")
    if not COINGECKO_API_KEY:
        problems.append("COINGECKO_API_KEY missing")
    if not CRYPTO_SETUP_CHANNEL_ID:
        problems.append("CRYPTO_SETUP_CHANNEL_ID missing")
    if not COIN_IDS:
        problems.append("COIN_IDS missing or empty")
    if problems:
        for p in problems:
            log.error("ENV ERROR: %s", p)
        raise SystemExit("Fix env variables above and redeploy.")

if __name__ == "__main__":
    _validate_env()
    bot.run(DISCORD_TOKEN)