import os
os.environ["DISCORD_NO_AUDIO"] = "1"

import asyncio
import logging
import json
from datetime import datetime, timezone
from typing import List, Dict, Any

import aiohttp
import discord
from discord.ext import commands, tasks

# ========= ENV =========
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CRYPTO_SETUP_CHANNEL_ID = int(os.getenv("CRYPTO_SETUP_CHANNEL_ID", "0"))
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")
COIN_IDS = [c.strip() for c in os.getenv("COIN_IDS", "bitcoin,ethereum").split(",") if c.strip()]

SCAN_INTERVAL_SEC = int(os.getenv("SCAN_INTERVAL_SEC", "300"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
RISK_MODE = os.getenv("RISK_MODE", "balanced").lower()

# ========= LOGGING =========
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
log = logging.getLogger("JCF-CRYPTO")

# ========= DISCORD =========
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ========= RISK PRESETS (tune later if you want) =========
RISK_PRESETS = {
    "conservative": {"min_24h_move": 2.0,  "min_1h_move": 0.8},
    "balanced":     {"min_24h_move": 3.5,  "min_1h_move": 1.2},
    "aggressive":   {"min_24h_move": 5.0,  "min_1h_move": 1.8},
}
RISK = RISK_PRESETS.get(RISK_MODE, RISK_PRESETS["balanced"])

CG_BASE = "https://pro-api.coingecko.com/api/v3"

HEADERS = {"x-cg-pro-api-key": COINGECKO_API_KEY} if COINGECKO_API_KEY else {}

# ========= HELPERS =========
def fmt_pct(x: float) -> str:
    sign = "🔺" if x >= 0 else "🔻"
    return f"{sign} {abs(x):.2f}%"

def chunks(lst: List[str], size: int) -> List[List[str]]:
    return [lst[i:i+size] for i in range(0, len(lst), size)]

async def fetch_markets(session: aiohttp.ClientSession, ids: List[str]) -> List[Dict[str, Any]]:
    """
    Use the markets endpoint (Pro) with 1h & 24h change.
    Note: Some IDs may not support 1h; we guard with defaults.
    """
    params = {
        "vs_currency": "usd",
        "ids": ",".join(ids),
        "order": "market_cap_desc",
        "per_page": len(ids),
        "page": 1,
        "sparkline": "false",
        "price_change_percentage": "1h,24h"
    }
    async with session.get(f"{CG_BASE}/coins/markets", params=params, headers=HEADERS, timeout=20) as r:
        if r.status != 200:
            txt = await r.text()
            raise RuntimeError(f"CoinGecko error {r.status}: {txt}")
        return await r.json()

def screen_signals(row: Dict[str, Any]) -> Dict[str, Any] | None:
    """
    Simple first-pass screener: flags coins with notable 1h/24h movement
    according to current RISK thresholds.
    """
    id_ = row.get("id")
    symbol = (row.get("symbol") or "").upper()
    name = row.get("name") or id_
    price = row.get("current_price") or 0.0

    # price_change_percentage_1h_in_currency and _24h_ keys come back as lists sometimes;
    # normalize to float or 0.0.
    def safe_pct(key: str) -> float:
        val = row.get(f"price_change_percentage_{key}_in_currency")
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, list) and val:
            return float(val[0] or 0)
        return 0.0

    ch1h = safe_pct("1h")
    ch24h = safe_pct("24h")

    if abs(ch24h) >= RISK["min_24h_move"] or abs(ch1h) >= RISK["min_1h_move"]:
        return {
            "id": id_,
            "symbol": symbol,
            "name": name,
            "price": price,
            "ch1h": ch1h,
            "ch24h": ch24h
        }
    return None

async def scan_crypto_and_post():
    if not CRYPTO_SETUP_CHANNEL_ID:
        log.warning("CRYPTO_SETUP_CHANNEL_ID not set; skipping post.")
        return
    chan = bot.get_channel(CRYPTO_SETUP_CHANNEL_ID)
    if not chan:
        log.warning("Discord channel not found (check ID & bot permissions).")
        return

    async with aiohttp.ClientSession() as session:
        signals: List[Dict[str, Any]] = []
        for group in chunks(COIN_IDS, 200):  # markets API supports many IDs, keep it safe
            try:
                data = await fetch_markets(session, group)
                for row in data:
                    sig = screen_signals(row)
                    if sig:
                        signals.append(sig)
            except Exception as e:
                log.error(f"[scan] group {group[:5]}... error: {e}")

    if not signals:
        await chan.send("⏱️ No notable crypto setups this scan (risk: **{0}**).".format(RISK_MODE))
        return

    # Sort by absolute 1h change (biggest first)
    signals.sort(key=lambda s: abs(s["ch1h"]), reverse=True)

    # Build a compact message
    lines = []
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    header = f"**Crypto Setups — {ts}**  *(risk: {RISK_MODE})*"
    for s in signals[:12]:  # post top 12 to keep tidy
        name = s["name"]
        sym = s["symbol"]
        price = s["price"]
        ch1h = fmt_pct(s["ch1h"])
        ch24h = fmt_pct(s["ch24h"])
        lines.append(f"• **{name}** ({sym}) — ${price:,.4f} — 1h {ch1h} | 24h {ch24h}")

    msg = header + "\n" + "\n".join(lines)
    await chan.send(msg)

# ========= COMMANDS =========
@bot.command()
async def ping(ctx):
    await ctx.reply("Pong 🏓")

@bot.command(name="scan")
async def scan_now(ctx):
    await ctx.reply("⏳ Scanning now…")
    try:
        await scan_crypto_and_post()
        await ctx.reply("✅ Scan posted.")
    except Exception as e:
        await ctx.reply(f"⚠️ Scan failed: `{e}`")
        log.exception("manual scan error")

# ========= TASK LOOP =========
@tasks.loop(seconds=5)
async def start_scanner():
    # Wait until bot fully ready, then convert to user-defined interval
    start_scanner.change_interval(seconds=SCAN_INTERVAL_SEC)
    await scan_crypto_and_post()

@bot.event
async def on_ready():
    log.info(f"✅ Logged in as {bot.user} (id: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="JCF HQ — crypto scans"))
    # post a startup message
    ch = bot.get_channel(CRYPTO_SETUP_CHANNEL_ID)
    if ch:
        await ch.send("✅ **JCFWatchBot ONLINE** — Crypto scanner armed. Risk: **{0}**. Interval: **{1}s**".format(RISK_MODE, SCAN_INTERVAL_SEC))
    # kick off the loop
    if not start_scanner.is_running():
        start_scanner.start()

# ========= BOOT =========
if not DISCORD_TOKEN:
    raise SystemExit("DISCORD_TOKEN missing. Set it in Railway variables.")
if not COIN_IDS:
    raise SystemExit("COIN_IDS missing. Example: ethereum,solana,ripple")
if not CRYPTO_SETUP_CHANNEL_ID:
    raise SystemExit("CRYPTO_SETUP_CHANNEL_ID missing. Paste the channel ID.")

bot.run(DISCORD_TOKEN)