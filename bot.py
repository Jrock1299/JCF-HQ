import os
import json
import time
import math
import asyncio
import logging
import threading
from pathlib import Path
from typing import Dict, List, Tuple

import requests
import discord
from discord.ext import commands, tasks

# ===============================
# Environment / Config
# ===============================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
CRYPTO_SETUP_CHANNEL_ID = int(os.getenv("CRYPTO_SETUP_CHANNEL_ID", "0") or "0")

# Comma-separated CoinGecko IDs, e.g. "bitcoin,ethereum,solana,cardano,chainlink,hedera-hashgraph,sui"
COIN_IDS_RAW = os.getenv("COIN_IDS", "") or ""
COIN_IDS: List[str] = [c.strip().lower() for c in COIN_IDS_RAW.split(",") if c.strip()]

# CoinGecko free/demo key header: x-cg-demo-api-key
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "").strip()

RISK_MODE = (os.getenv("RISK_MODE", "conservative") or "conservative").lower()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
SCAN_INTERVAL_SEC = int(os.getenv("SCAN_INTERVAL_SEC", "300") or "300")  # default 5 min

# Discord intents
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ===============================
# Logging
# ===============================

logger = logging.getLogger("jcf-hq")
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(levelname)s:%(name)s:%(message)s",
)

# ===============================
# Persistence: AlertGuard
# ===============================

STATE_FILE = Path("state.json")
STATE_LOCK = threading.Lock()


def _load_state():
    if STATE_FILE.exists():
        try:
            with STATE_FILE.open("r") as f:
                return json.load(f)
        except Exception:
            return {"active": {}, "history": []}
    return {"active": {}, "history": []}


def _save_state(state):
    tmp = STATE_FILE.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(state, f, indent=2)
    tmp.replace(STATE_FILE)


def _setup_key(symbol: str, tf: str, side: str, entry_lo: float, entry_hi: float, sl: float, tp1: float) -> str:
    return f"{symbol}|{tf}|{side}|{entry_lo:.6f}:{entry_hi:.6f}|SL:{sl:.6f}|TP1:{tp1:.6f}"


class AlertGuard:
    """Keeps exactly one active alert per unique setup; resolves on TP/SL."""
    def __init__(self):
        self.state = _load_state()

    def should_alert(self, key: str) -> bool:
        with STATE_LOCK:
            return key not in self.state["active"]

    def register_alert(self, key: str, payload: dict):
        payload = dict(payload)
        payload["created_ts"] = int(time.time())
        payload["status"] = "active"
        with STATE_LOCK:
            self.state["active"][key] = payload
            _save_state(self.state)

    def resolve(self, key: str, resolution: str):
        with STATE_LOCK:
            if key in self.state["active"]:
                item = self.state["active"].pop(key)
                item["status"] = resolution
                item["resolved_ts"] = int(time.time())
                self.state["history"].append(item)
                _save_state(self.state)

    def active_for_symbol(self, symbol: str):
        with STATE_LOCK:
            return {k: v for k, v in self.state["active"].items() if k.startswith(symbol + "|")}

    def all_active(self):
        with STATE_LOCK:
            return dict(self.state["active"])


ALERT_GUARD = AlertGuard()

# ===============================
# Market helpers (CoinGecko free)
# ===============================

CG_BASE = "https://api.coingecko.com/api/v3/simple/price"


def fetch_prices(ids: List[str]) -> Dict[str, Dict[str, float]]:
    """Get {id: {'usd': price, 'usd_24h_change': change}}"""
    if not ids:
        return {}

    headers = {}
    if COINGECKO_API_KEY:
        # Free/demo header
        headers["x-cg-demo-api-key"] = COINGECKO_API_KEY

    params = {
        "ids": ",".join(ids),
        "vs_currencies": "usd",
        "include_24hr_change": "true",
    }
    r = requests.get(CG_BASE, params=params, headers=headers, timeout=20)
    r.raise_for_status()
    data = r.json() or {}
    # Normalize: ensure 'usd' and 'usd_24h_change' keys exist
    out = {}
    for cid in ids:
        row = data.get(cid, {})
        if "usd" in row:
            out[cid] = {
                "usd": float(row.get("usd", 0.0)),
                "usd_24h_change": float(row.get("usd_24h_change", 0.0)),
            }
    return out


# ===============================
# Setup logic (simple, risk-aware)
# ===============================

def compute_setup_from_price(symbol: str, price: float, change_24h: float) -> Tuple[str, Dict]:
    """
    Very lightweight heuristic setup builder using only last price + 24h change.
    - If change <= -3% => bearish setup (short bias)
    - If change >= +3% => bullish setup (long bias)
    - Else: None (no setup)
    Entry/SL/TP scaled by RISK_MODE.
    """
    tf = "30m"
    momentum = "Strong" if abs(change_24h) >= 6 else ("Moderate" if abs(change_24h) >= 3 else "Calm")

    if RISK_MODE == "conservative":
        band = 0.006  # 0.6%
        rr_tp2 = 1.33
        conf = 86
    elif RISK_MODE == "balanced":
        band = 0.009
        rr_tp2 = 1.5
        conf = 80
    else:  # aggressive
        band = 0.012
        rr_tp2 = 1.7
        conf = 72

    if change_24h <= -3.0:
        side = "short"
        entry_lo = price * (1 - band * 0.8)
        entry_hi = price * (1 + band * 0.2)
        sl = price * (1 + band * 2.1)
        tp1 = price * (1 - band * 1.0)
        tp2 = price * (1 - band * 2.0)
        tp3 = price * (1 - band * 3.0)
        label = "Bearish Move Setup"
    elif change_24h >= 3.0:
        side = "long"
        entry_lo = price * (1 - band * 0.2)
        entry_hi = price * (1 + band * 0.8)
        sl = price * (1 - band * 2.1)
        tp1 = price * (1 + band * 1.0)
        tp2 = price * (1 + band * 2.0)
        tp3 = price * (1 + band * 3.0)
        label = "Bullish Move Setup"
    else:
        return ("none", {})

    doc = {
        "symbol": symbol.upper(),
        "tf": tf,
        "momentum": momentum,
        "side": side,  # 'long' or 'short'
        "entry_low": entry_lo,
        "entry_high": entry_hi,
        "sl": sl,
        "targets": [tp1, tp2, tp3],
        "rr_to_tp2": rr_tp2,
        "confidence": conf,
        "price_now": price,
        "change_24h": change_24h,
        "label": label,
    }
    return ("ok", doc)


def fmt_price(x: float) -> str:
    # Pretty rounded price
    if x == 0 or math.isnan(x):
        return "0"
    if x >= 100:
        return f"{x:,.2f}"
    if x >= 1:
        return f"{x:,.4f}"
    return f"{x:.6f}"


async def send_setup_card(ch: discord.TextChannel, setup: Dict):
    side = setup["side"]
    title_icon = "🚀" if side == "long" else "🔻"
    name = setup["symbol"].replace("-", "").upper()

    lines = [
        f"{title_icon} **{name} — {setup['label']} ( {RISK_MODE} )**",
        f"Timeframe: **{setup['tf']}** | Momentum: **{setup['momentum']}**",
        "",
        f"• **Entry Zone:** {fmt_price(setup['entry_low'])} — {fmt_price(setup['entry_high'])}",
        f"• **Stop Loss:** {fmt_price(setup['sl'])}",
        f"• **Targets:** {fmt_price(setup['targets'][0])} / {fmt_price(setup['targets'][1])} / {fmt_price(setup['targets'][2])}",
        f"• **R:R (to TP2):** {setup['rr_to_tp2']}",
        f"• **Confidence:** {setup['confidence']}%",
    ]

    await ch.send("\n".join(lines))


async def send_resolution_card(ch: discord.TextChannel, payload: Dict, last_price: float, resolution: str):
    sym = payload["symbol"]
    tf = payload["tf"]
    side = payload["side"].upper()
    if resolution == "tp_hit":
        txt = f"✅ **TP hit — setup closed**\n**{sym} {tf} {side}** @ **{fmt_price(last_price)}**"
    else:
        txt = f"🛑 **Stop Loss hit — setup closed**\n**{sym} {tf} {side}** @ **{fmt_price(last_price)}**"
    await ch.send(txt)


def price_hit_short(sl: float, tp_levels: List[float], last_price: float):
    if last_price >= sl:
        return "sl_hit"
    if any(last_price <= tp for tp in tp_levels):
        return "tp_hit"
    return None


def price_hit_long(sl: float, tp_levels: List[float], last_price: float):
    if last_price <= sl:
        return "sl_hit"
    if any(last_price >= tp for tp in tp_levels):
        return "tp_hit"
    return None


# ===============================
# Discord events & commands
# ===============================

@bot.event
async def on_ready():
    logger.info("✅ Logged in as %s#%s (%s)", bot.user.name, bot.user.discriminator, bot.user.id)
    await bot.change_presence(activity=discord.Game(name="JCF HQ — Crypto Scan"))
    if CRYPTO_SETUP_CHANNEL_ID:
        ch = bot.get_channel(CRYPTO_SETUP_CHANNEL_ID)
        if ch:
            await ch.send("✅ **Crypto scanner online** — listening for setups…")


@bot.command(name="ping")
async def ping_cmd(ctx):
    await ctx.reply("Pong 🏓")


@bot.command(name="status")
async def status_cmd(ctx):
    await ctx.reply(
        f"**Status**\n"
        f"- Coins: `{', '.join(COIN_IDS) or 'none'}`\n"
        f"- Risk: `{RISK_MODE}` | Interval: `{SCAN_INTERVAL_SEC}s`\n"
        f"- Active setups: `{len(ALERT_GUARD.all_active())}`"
    )


@bot.command(name="testcrypto")
async def testcrypto_cmd(ctx):
    """Send a single mock setup for ETH (no guard)."""
    ch = bot.get_channel(CRYPTO_SETUP_CHANNEL_ID)
    if not ch:
        await ctx.reply("Crypto channel not configured.")
        return
    mock = {
        "symbol": "ETHEREUM",
        "tf": "30m",
        "momentum": "Moderate",
        "side": "long",
        "entry_low": 3000 * 0.995,
        "entry_high": 3000 * 1.005,
        "sl": 3000 * 0.985,
        "targets": [3000 * 1.01, 3000 * 1.02, 3000 * 1.03],
        "rr_to_tp2": 1.33,
        "confidence": 86,
        "price_now": 3000,
        "change_24h": 6.2,
        "label": "Bullish Move Setup",
    }
    await send_setup_card(ch, mock)
    await ctx.reply("Test crypto alert sent ✅")


@bot.command(name="state")
async def state_cmd(ctx, symbol: str = None):
    if symbol:
        act = ALERT_GUARD.active_for_symbol(symbol.upper())
    else:
        act = ALERT_GUARD.all_active()
    if not act:
        await ctx.reply("No active setups.")
        return
    lines = []
    for _, v in act.items():
        lines.append(
            f"- {v['symbol']} {v['tf']} {v['side']} | SL {fmt_price(v['sl'])} | "
            f"TP1 {fmt_price(v['targets'][0])}"
        )
    await ctx.reply("Active setups:\n" + "\n".join(lines))


@bot.command(name="clearsetup")
async def clearsetup_cmd(ctx, symbol: str):
    symbol = symbol.upper()
    to_clear = []
    active = ALERT_GUARD.all_active()
    for k in list(active.keys()):
        if k.startswith(symbol + "|"):
            to_clear.append(k)
    for k in to_clear:
        ALERT_GUARD.resolve(k, "manual_clear")
    await ctx.reply(f"Cleared {len(to_clear)} active setup(s) for {symbol}.")


# ===============================
# Scan loop
# ===============================

@tasks.loop(seconds=max(30, SCAN_INTERVAL_SEC))
async def crypto_scan_loop():
    if not COIN_IDS:
        logger.warning("No COIN_IDS configured; skipping scan.")
        return
    try:
        prices = fetch_prices(COIN_IDS)  # {id: {usd, usd_24h_change}}
    except requests.HTTPError as e:
        logger.error("[scan] HTTPError: %s", e)
        return
    except Exception as e:
        logger.exception("[scan] unexpected error: %s", e)
        return

    ch = bot.get_channel(CRYPTO_SETUP_CHANNEL_ID) if CRYPTO_SETUP_CHANNEL_ID else None
    if not ch:
        logger.warning("CRYPTO_SETUP_CHANNEL_ID not set or channel not found.")
        return

    # 1) Build new setups (if any) and post (guarded)
    for cid, row in prices.items():
        price = float(row.get("usd", 0.0))
        chg = float(row.get("usd_24h_change", 0.0))
        if price <= 0:
            continue

        status, setup = compute_setup_from_price(cid, price, chg)
        if status != "ok":
            continue

        key = _setup_key(setup["symbol"], setup["tf"], setup["side"], setup["entry_low"], setup["entry_high"], setup["sl"], setup["targets"][0])
        if ALERT_GUARD.should_alert(key):
            await send_setup_card(ch, setup)
            ALERT_GUARD.register_alert(key, setup)
        else:
            # duplicate of an active setup — skip
            pass

    # 2) Resolve any active setups (TP/SL) using latest prices
    latest_by_symbol = {}
    # Map our active symbols (stored uppercase) back to lowercase ids for the price dict
    for cid, row in prices.items():
        latest_by_symbol[cid.upper()] = float(row.get("usd", 0.0))

    active_copy = ALERT_GUARD.all_active()
    for key, payload in active_copy.items():
        sym = payload["symbol"].upper()
        last_price = latest_by_symbol.get(sym)
        if not last_price:
            continue
        side = payload["side"]
        sl = float(payload["sl"])
        tps = [float(x) for x in payload["targets"]]

        if side == "short":
            hit = price_hit_short(sl, tps, last_price)
        else:
            hit = price_hit_long(sl, tps, last_price)

        if hit in ("tp_hit", "sl_hit"):
            await send_resolution_card(ch, payload, last_price, hit)
            ALERT_GUARD.resolve(key, hit)


@crypto_scan_loop.before_loop
async def before_scan():
    await bot.wait_until_ready()
    logger.info("🛰️  crypto_scan_loop started: every %ss", SCAN_INTERVAL_SEC)


# ===============================
# Main
# ===============================

def validate_env():
    problems = []
    if not DISCORD_TOKEN:
        problems.append("DISCORD_TOKEN missing")
    if not CRYPTO_SETUP_CHANNEL_ID:
        problems.append("CRYPTO_SETUP_CHANNEL_ID missing or invalid")
    if not COIN_IDS:
        problems.append("COIN_IDS empty")
    if problems:
        raise RuntimeError("Config error: " + ", ".join(problems))


if __name__ == "__main__":
    validate_env()
    crypto_scan_loop.start()
    bot.run(DISCORD_TOKEN)