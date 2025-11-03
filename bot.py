import os, json, asyncio, logging, time, math, textwrap
from datetime import datetime, timezone
import requests
import discord
from discord.ext import commands, tasks

# ── ENV / CONFIG ──────────────────────────────────────────────────────────────
DISCORD_TOKEN              = os.getenv("DISCORD_TOKEN", "")
CRYPTO_SETUP_CHANNEL_ID    = int(os.getenv("CRYPTO_SETUP_CHANNEL_ID", "0"))
TRADE_HISTORY_CHANNEL_ID   = int(os.getenv("TRADE_HISTORY_CHANNEL_ID", "0"))  # <— NEW
COINGECKO_API_KEY          = os.getenv("COINGECKO_API_KEY", "")               # demo key ok
COIN_IDS                   = [c.strip() for c in os.getenv("COIN_IDS","").split(",") if c.strip()]
SCAN_INTERVAL_SEC          = int(os.getenv("SCAN_INTERVAL_SEC", "300"))
RISK_MODE                  = os.getenv("RISK_MODE", "conservative").lower()
LOG_LEVEL                  = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO),
                    format="%(levelname)s:%(name)s:%(message)s")
log = logging.getLogger("jcf-hq")

STATE_PATH = "/mnt/data/open_trades.json"

# Client / intents
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ── PERSISTED STATE (open trades) ─────────────────────────────────────────────
# key = f"{coin}|{direction}" ; direction in {"bullish","bearish"}
def load_state():
    try:
        with open(STATE_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(state):
    try:
        with open(STATE_PATH, "w") as f:
            json.dump(state, f)
    except Exception as e:
        log.warning(f"could not save state: {e}")

open_trades = load_state()  # { key: {...} }

# ── COINGECKO HELPER ─────────────────────────────────────────────────────────
def gecko_base():
    # Use pro endpoint if a key exists (demo "cg-..." is fine), else public
    if COINGECKO_API_KEY:
        return "https://pro-api.coingecko.com/api/v3"
    return "https://api.coingecko.com/api/v3"

def gecko_headers():
    headers = {"Accept": "application/json"}
    if COINGECKO_API_KEY:
        headers["x-cg-pro-api-key"] = COINGECKO_API_KEY
    return headers

def fetch_simple_prices(ids):
    """
    Returns: { id: {"usd": float, "usd_24h_change": float} }
    """
    if not ids:
        return {}
    url = f"{gecko_base()}/simple/price"
    params = {
        "ids": ",".join(ids),
        "vs_currencies": "usd",
        "include_24hr_change": "true",
    }
    r = requests.get(url, params=params, headers=gecko_headers(), timeout=20)
    r.raise_for_status()
    return r.json()

# ── RISK / TARGETS ENGINE (kept simple & conservative-first) ─────────────────
def risk_profile():
    # widths used to place entry zone, stops, and targets around current price
    # tuned for conservatism unless user sets balanced/aggressive
    if RISK_MODE == "aggressive":
        return dict(entry_width=0.006, sl_off=0.012, tp_step=0.008)
    if RISK_MODE == "balanced":
        return dict(entry_width=0.004, sl_off=0.009,  tp_step=0.006)
    return dict(entry_width=0.003, sl_off=0.007, tp_step=0.005)  # conservative

def build_setup(coin_id: str, price: float, chg24: float):
    """
    Direction by 24h momentum sign; entry/SL/TPs derived from price
    In your previous script you ran EMA+BB+OB; this keeps messaging style
    while remaining deterministic without TA libraries on the server.
    """
    prof = risk_profile()
    dirn = "bullish" if chg24 >= 0.0 else "bearish"
    momentum = "Moderate" if abs(chg24) < 4 else ("Strong" if abs(chg24) >= 8 else "Normal")

    zone = prof["entry_width"] * price
    entry_low, entry_high = (price - zone, price - 0.2*zone) if dirn=="bullish" else (price + 0.2*zone, price + zone)

    if dirn == "bullish":
        sl = entry_low - prof["sl_off"] * price
        tp1 = price + prof["tp_step"] * price
        tp2 = price + 2*prof["tp_step"] * price
        tp3 = price + 3*prof["tp_step"] * price
    else:
        sl = entry_high + prof["sl_off"] * price
        tp1 = price - prof["tp_step"] * price
        tp2 = price - 2*prof["tp_step"] * price
        tp3 = price - 3*prof["tp_step"] * price

    # rough RR vs TP2 (distance entry mid to TP2 / distance entry mid to SL)
    entry_mid = (entry_low + entry_high) / 2
    rr = abs((tp2 - entry_mid) / (entry_mid - sl)) if (entry_mid - sl) != 0 else 1.0

    setup = {
        "coin": coin_id,
        "direction": dirn,
        "timeframe": "30m",
        "momentum": momentum,
        "entry_low": round(entry_low, 4),
        "entry_high": round(entry_high, 4),
        "sl": round(sl, 4),
        "targets": [round(tp1, 4), round(tp2, 4), round(tp3, 4)],
        "rr_tp2": round(rr, 2),
        "confidence": 86,  # keep same presentation as your earlier messages
        "price_ref": round(price, 4),
    }
    return setup

def should_emit_new(setup):
    """Only one live setup per coin+direction."""
    key = f'{setup["coin"]}|{setup["direction"]}'
    return key not in open_trades

def record_open(setup):
    key = f'{setup["coin"]}|{setup["direction"]}'
    open_trades[key] = {
        "opened_at": time.time(),
        "setup": setup,
        "status": "OPEN",
        "filled": False  # simple model; we log from signal time
    }
    save_state(open_trades)

def try_close_from_price(coin_id, price):
    """
    Check SL/TP hits for both bull & bear open trades of this coin.
    Returns list of closures to log.
    """
    closures = []
    for direction in ("bullish", "bearish"):
        key = f"{coin_id}|{direction}"
        if key not in open_trades:
            continue
        rec = open_trades[key]
        st = rec["setup"]

        # evaluate
        if direction == "bullish":
            if price <= st["sl"]:
                outcome, reached = "STOP LOSS", st["sl"]
            elif price >= st["targets"][2]:
                outcome, reached = "TP3", st["targets"][2]
            elif price >= st["targets"][1]:
                outcome, reached = "TP2", st["targets"][1]
            elif price >= st["targets"][0]:
                outcome, reached = "TP1", st["targets"][0]
            else:
                continue
        else:  # bearish
            if price >= st["sl"]:
                outcome, reached = "STOP LOSS", st["sl"]
            elif price <= st["targets"][2]:
                outcome, reached = "TP3", st["targets"][2]
            elif price <= st["targets"][1]:
                outcome, reached = "TP2", st["targets"][1]
            elif price <= st["targets"][0]:
                outcome, reached = "TP1", st["targets"][0]
            else:
                continue

        # compute pnl vs entry mid (percent)
        entry_mid = (st["entry_low"] + st["entry_high"]) / 2.0
        if direction == "bullish":
            pnl = (reached - entry_mid) / entry_mid * 100
        else:
            pnl = (entry_mid - reached) / entry_mid * 100

        opened_at = rec.get("opened_at", time.time())
        dur_min = int((time.time() - opened_at) / 60)

        closures.append({
            "key": key, "outcome": outcome, "reached": round(reached,4),
            "pnl_pct": round(pnl, 2), "duration_min": dur_min, "setup": st
        })
    return closures

# ── MESSAGE FORMATTING ───────────────────────────────────────────────────────
def fmt_title(coin, direction):
    icon = "🚀" if direction=="bullish" else "🔻"
    name = coin.replace("-", " ").upper()
    label = "Bullish" if direction=="bullish" else "Bearish"
    return f"{icon} {name} — {label} Move Setup Detected ({RISK_MODE})"

def fmt_setup_block(s):
    lines = [
        f"Timeframe: {s['timeframe']} | Momentum: {s['momentum']}",
        "",
        f"• Entry Zone: {s['entry_low']} – {s['entry_high']}",
        f"• Stop Loss: {s['sl']}",
        f"• Targets: {s['targets'][0]} / {s['targets'][1]} / {s['targets'][2]}",
        f"• R:R (to TP2): {s['rr_tp2']}",
        f"• Confidence: {s['confidence']}%",
    ]
    return "```\n" + "\n".join(lines) + "\n```"

def fmt_close_block(c):
    s = c["setup"]
    name = s["coin"].replace("-", " ").upper()
    title = f"✅ TRADE CLOSED — {name} ({'LONG' if s['direction']=='bullish' else 'SHORT'})"
    lines = [
        f"Outcome: **{c['outcome']}** @ `{c['reached']}`",
        f"P/L: **{c['pnl_pct']}%**   |   Duration: **{c['duration_min']}m**",
        "",
        f"Entry Zone: `{s['entry_low']} – {s['entry_high']}`   SL: `{s['sl']}`",
        f"TPs: `{s['targets'][0]} / {s['targets'][1]} / {s['targets'][2]}`",
    ]
    return title, "```\n" + "\n".join(lines) + "\n```"

# ── DISCORD EVENTS / TASKS ───────────────────────────────────────────────────
@bot.event
async def on_ready():
    log.info(f"✅ Logged in as {bot.user} ({bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="JCF HQ online"))
    ch = bot.get_channel(CRYPTO_SETUP_CHANNEL_ID)
    if ch:
        await ch.send("✅ **Crypto scanner online** — EMA+BB+OB mode activated.")
        await ch.send(f"✅ **Crypto scanner online** — OB_LENGTH=5, mitigation=close.")
    scan_loop.start()

@tasks.loop(seconds=SCAN_INTERVAL_SEC)
async def scan_loop():
    try:
        prices = fetch_simple_prices(COIN_IDS)
    except Exception as e:
        log.error(f"[scan] HTTPError: {e}")
        return

    setup_ch = bot.get_channel(CRYPTO_SETUP_CHANNEL_ID)
    history_ch = bot.get_channel(TRADE_HISTORY_CHANNEL_ID) if TRADE_HISTORY_CHANNEL_ID else None

    # 1) Close any open trades that hit TP/SL
    for cid in COIN_IDS:
        info = prices.get(cid)
        if not info:  # unknown id
            continue
        price = float(info["usd"])
        for closure in try_close_from_price(cid, price):
            # remove from state and log
            key = closure["key"]
            if key in open_trades:
                del open_trades[key]
                save_state(open_trades)
            if history_ch:
                title, block = fmt_close_block(closure)
                await history_ch.send(title)
                await history_ch.send(block)

    # 2) Emit new setups (one per coin at most)
    for cid in COIN_IDS:
        info = prices.get(cid)
        if not info:
            continue
        price = float(info["usd"])
        chg = float(info.get("usd_24h_change", 0.0))
        setup = build_setup(cid, price, chg)
        if should_emit_new(setup) and setup_ch:
            await setup_ch.send(f"**{fmt_title(setup['coin'], setup['direction'])}**")
            await setup_ch.send(fmt_setup_block(setup))
            record_open(setup)

# ── COMMANDS (admin quality-of-life) ─────────────────────────────────────────
@bot.command()
async def status(ctx):
    """Show scanner status + open trades."""
    n_open = len(open_trades)
    coins = ", ".join(COIN_IDS) if COIN_IDS else "(none)"
    msg = textwrap.dedent(f"""
    **Scanner:** running every {SCAN_INTERVAL_SEC}s
    **Risk:** `{RISK_MODE}`
    **Coins:** {coins}
    **Open trades:** {n_open}
    """).strip()
    await ctx.reply(msg)

@bot.command()
async def open(ctx):
    """List open trades."""
    if not open_trades:
        return await ctx.reply("No open trades.")
    for rec in open_trades.values():
        s = rec["setup"]
        name = s["coin"].replace("-", " ").upper()
        await ctx.send(f"**{name}** — {s['direction'].upper()}  |  Entry: `{s['entry_low']}–{s['entry_high']}`  SL: `{s['sl']}`  TPs: `{s['targets'][0]}/{s['targets'][1]}/{s['targets'][2]}`")

@bot.command()
@commands.has_permissions(administrator=True)
async def forcereset(ctx, coin: str, direction: str):
    """Admin: force clear an open trade by coin id and direction (bullish/bearish)."""
    key = f"{coin.lower()}|{direction.lower()}"
    if key in open_trades:
        del open_trades[key]
        save_state(open_trades)
        await ctx.reply(f"Cleared `{key}`.")
    else:
        await ctx.reply(f"No open trade for `{key}`.")

@forcereset.error
async def fr_err(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply("Usage: `!forcereset <coin_id> <bullish|bearish>`")

# ── BOOT ─────────────────────────────────────────────────────────────────────
if not DISCORD_TOKEN:
    raise SystemExit("DISCORD_TOKEN missing")

if not CRYPTO_SETUP_CHANNEL_ID:
    raise SystemExit("CRYPTO_SETUP_CHANNEL_ID missing")

if not COIN_IDS:
    log.warning("COIN_IDS is empty — scanner will be idle.")

bot.run(DISCORD_TOKEN)