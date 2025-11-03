import os, json, asyncio, logging, math, time
from datetime import datetime, timezone
import requests
import discord
from discord.ext import commands, tasks

# ───────── CONFIG FROM ENV ─────────
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CRYPTO_SETUP_CHANNEL_ID = int(os.getenv("CRYPTO_SETUP_CHANNEL_ID", "0"))
TRADE_HISTORY_CHANNEL_ID = int(os.getenv("TRADE_HISTORY_CHANNEL_ID", "0"))
COIN_IDS = [c.strip().lower() for c in os.getenv("COIN_IDS", "").split(",") if c.strip()]
SCAN_INTERVAL_SEC = int(os.getenv("SCAN_INTERVAL_SEC", "600"))  # safer default: 10m
RISK_MODE = os.getenv("RISK_MODE", "conservative").lower()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
CG_KEY = os.getenv("COINGECKO_API_KEY", "").strip()

API_BASE = "https://api.coingecko.com/api/v3"
HEADERS = {"accept": "application/json"}
if CG_KEY:
    # CoinGecko demo/free key goes here
    HEADERS["x-cg-demo-api-key"] = CG_KEY

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(levelname)s:%(name)s:%(message)s"
)
log = logging.getLogger("jcf-hq")

# ───────── DISCORD BOT ─────────
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ───────── STATE (persisted open trades) ─────────
STATE_PATH = "/tmp/jcf_open_trades.json"

def load_state():
    try:
        if not os.path.exists(STATE_PATH):
            return {}
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

open_trades = load_state()   # { key: { … } }
next_scan_eta = "n/a"

# ───────── TECH UTILS ─────────
def ema(series, period):
    if len(series) < period:
        return None
    k = 2 / (period + 1)
    e = series[0]
    for v in series[1:]:
        e = v * k + e * (1 - k)
    return e

def bollinger(series, period=20, mult=2.0):
    if len(series) < period:
        return None, None, None
    last = series[-period:]
    mean = sum(last) / period
    std = math.sqrt(sum((x - mean) ** 2 for x in last) / period)
    upper = mean + mult * std
    lower = mean - mult * std
    return lower, mean, upper

def recent_pivot(series, lookback=5, mode="high"):
    if len(series) < lookback * 2 + 1:
        return None
    window = series[-(lookback*2+1):]
    mid = window[lookback]
    if mode == "high":
        return mid if mid == max(window) else None
    else:
        return mid if mid == min(window) else None

# Risk presets (in % of price)
RISK_PRESETS = {
    "conservative": {"stop": 1.8, "tp1": 0.7, "tp2": 1.2, "tp3": 1.8},
    "balanced":     {"stop": 2.2, "tp1": 1.0, "tp2": 1.6, "tp3": 2.4},
    "aggressive":   {"stop": 3.0, "tp1": 1.4, "tp2": 2.2, "tp3": 3.0},
}
R = RISK_PRESETS.get(RISK_MODE, RISK_PRESETS["conservative"])

# ───────── DATA FETCH (demo-safe) ─────────
def get_market_prices(coin_id, days="1"):
    """
    Demo/free-safe price fetcher:
    - No 'interval=minute' (which causes 401 on demo)
    - Backoff on HTTP 429
    Returns list of floats [p1, p2, ...]
    """
    url = f"{API_BASE}/coins/{coin_id}/market_chart"
    params = {"vs_currency": "usd", "days": days}  # <-- no interval param
    for attempt in range(3):
        r = requests.get(url, params=params, headers=HEADERS, timeout=20)
        if r.status_code == 429:
            # gentle backoff
            sleep_s = 5 * (attempt + 1)
            log.warning(f"[scan] {coin_id}: 429 rate limited, sleeping {sleep_s}s…")
            time.sleep(sleep_s)
            continue
        r.raise_for_status()
        data = r.json()
        return [p[1] for p in data.get("prices", [])]
    raise RuntimeError(f"{coin_id}: failed after retries")

def get_simple_changes(ids):
    # 24h change using simple/price for the header block
    url = f"{API_BASE}/simple/price"
    params = {"ids": ",".join(ids), "vs_currencies": "usd", "include_24hr_change": "true"}
    r = requests.get(url, params=params, headers=HEADERS, timeout=20)
    if r.status_code == 429:
        time.sleep(5)
        r = requests.get(url, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.json()  # {id: {"usd": x, "usd_24h_change": y}}

# ───────── SIGNAL LOGIC ─────────
def build_setup(coin, prices):
    """
    Returns dict or None:
      {
        'direction': 'bull'|'bear',
        'entry_low': float, 'entry_high': float,
        'stop': float, 'targets':[t1,t2,t3],
        'confidence': int, 'tf': '30m', 'momentum':'Moderate'
      }
    """
    if len(prices) < 120:
        return None

    # Use last chunk and downsample for smoothness
    tail = prices[-600:]
    ds = tail[::5]

    ema50  = ema(ds, 50)  if len(ds) >= 50  else None
    ema200 = ema(ds, 200) if len(ds) >= 200 else None
    lb, mid, ub = bollinger(ds, 20, 2.0)
    price = ds[-1]

    if not all([ema50, ema200, lb, ub]):
        return None

    piv_hi = recent_pivot(ds, lookback=5, mode="high")
    piv_lo = recent_pivot(ds, lookback=5, mode="low")

    bull_bias = price > ema50 and price > ema200 and price <= lb * 1.01 and piv_lo is not None
    bear_bias = price < ema50 and price < ema200 and price >= ub * 0.99 and piv_hi is not None

    if not (bull_bias or bear_bias):
        return None

    direction = "bull" if bull_bias else "bear"

    if direction == "bull":
        entry_low  = price * (1 - 0.003)
        entry_high = price * (1 + 0.003)
        stop       = price * (1 - R["stop"]/100.0)
        t1         = price * (1 + R["tp1"]/100.0)
        t2         = price * (1 + R["tp2"]/100.0)
        t3         = price * (1 + R["tp3"]/100.0)
    else:
        entry_low  = price * (1 - 0.003)
        entry_high = price * (1 + 0.003)
        stop       = price * (1 + R["stop"]/100.0)
        t1         = price * (1 - R["tp1"]/100.0)
        t2         = price * (1 - R["tp2"]/100.0)
        t3         = price * (1 - R["tp3"]/100.0)

    dist_bb = abs(price - (lb if direction == "bull" else ub)) / price
    ema_sep = abs(ema50 - ema200) / price
    conf = 60 + int(min(30, ema_sep * 1000)) - int(min(10, dist_bb * 1000))
    conf = max(60, min(95, conf))

    return {
        "direction": direction,
        "entry_low": round(entry_low, 6),
        "entry_high": round(entry_high, 6),
        "stop": round(stop, 6),
        "targets": [round(t1, 6), round(t2, 6), round(t3, 6)],
        "confidence": conf,
        "tf": "30m",
        "momentum": "Moderate",
        "ref_price": round(price, 6),
    }

def rr_to_tp2(setup):
    if setup["direction"] == "bull":
        risk = setup["entry_high"] - setup["stop"]
        reward = setup["targets"][1] - setup["entry_low"]
    else:
        risk = setup["stop"] - setup["entry_low"]
        reward = setup["entry_high"] - setup["targets"][1]
    return round(reward / risk, 2) if risk > 0 else 0.0

# ───────── MESSAGE BUILDERS ─────────
def fmt_setup_block(name, setup, change_24h):
    arrow = "🚀" if setup["direction"] == "bull" else "🔻"
    title = f"{arrow} {name.upper()} — {'Bullish' if setup['direction']=='bull' else 'Bearish'} Move Setup Detected ({RISK_MODE})"
    rr = rr_to_tp2(setup)
    lines = [
        f"Timeframe: {setup['tf']} | Momentum: {setup['momentum']}",
        "",
        f"• Entry Zone: {setup['entry_low']:.4f} - {setup['entry_high']:.4f}",
        f"• Stop Loss: {setup['stop']:.4f}",
        f"• Targets: {setup['targets'][0]:.4f} / {setup['targets'][1]:.4f} / {setup['targets'][2]:.4f}",
        f"• R:R (to TP2): {rr}",
        f"• Confidence: {setup['confidence']}%",
        f"• 24h Change: {change_24h:+.2f}%",
    ]
    return f"**{title}**\n```• " + "\n• ".join(lines) + "```"

def fmt_trade_open(name, setup):
    icon = "📈" if setup["direction"] == "bull" else "📉"
    return (
        f"{icon} **TRADE OPENED — {name.upper()} ({'Bullish' if setup['direction']=='bull' else 'Bearish'})**\n"
        f"Entry: {setup['entry_low']:.4f} – {setup['entry_high']:.4f}\n"
        f"Stop Loss: {setup['stop']:.4f}\n"
        f"Targets: {setup['targets'][0]:.4f} / {setup['targets'][1]:.4f} / {setup['targets'][2]:.4f}\n"
        f"Confidence: {setup['confidence']}%"
    )

def fmt_trade_close(name, direction, reason, pnl_pct):
    badge = "✅" if "TP" in reason else "❌"
    arrow = "Bullish" if direction == "bull" else "Bearish"
    return f"{badge} **TRADE CLOSED — {name.upper()} ({reason})**\nPnL: {pnl_pct:+.2f}% ({arrow})"

# ───────── POST HELPERS ─────────
async def post(channel_id: int, content: str):
    ch = bot.get_channel(channel_id)
    if ch:
        await ch.send(content)

# ───────── CORE SCAN LOOP ─────────
@tasks.loop(seconds=SCAN_INTERVAL_SEC)
async def crypto_scan_loop():
    global next_scan_eta, open_trades
    try:
        next_scan_eta = f"{SCAN_INTERVAL_SEC}s"
        # Pre-fetch simple 24h change for all coins
        change_map = {}
        try:
            if COIN_IDS:
                change_map = get_simple_changes(COIN_IDS)
        except Exception as e:
            log.warning(f"[scan] simple/price change fetch failed: {e}")

        # small pacing between coins to avoid bursts
        for idx, coin in enumerate(COIN_IDS):
            try:
                prices = get_market_prices(coin, days="1")
            except Exception as e:
                log.error(f"[scan] {coin}: {e}")
                await asyncio.sleep(0.3)
                continue
            if len(prices) < 60:
                await asyncio.sleep(0.2)
                continue

            setup = build_setup(coin, prices)
            last_price = prices[-1]
            change_24h = 0.0
            if isinstance(change_map.get(coin), dict):
                change_24h = float(change_map[coin].get("usd_24h_change", 0.0))

            # Manage existing open trade for this coin
            to_delete = []
            for key, trade in list(open_trades.items()):
                if trade["coin"] != coin:
                    continue
                dirn = trade["direction"]
                if dirn == "bull":
                    if last_price >= trade["targets"][1]:
                        await post(TRADE_HISTORY_CHANNEL_ID, fmt_trade_close(coin, dirn, "TP2 HIT", (trade["targets"][1] / trade["entry_mid"] - 1)*100))
                        to_delete.append(key)
                    elif last_price <= trade["stop"]:
                        await post(TRADE_HISTORY_CHANNEL_ID, fmt_trade_close(coin, dirn, "STOP LOSS HIT", (trade["stop"] / trade["entry_mid"] - 1)*100))
                        to_delete.append(key)
                else:
                    if last_price <= trade["targets"][1]:
                        await post(TRADE_HISTORY_CHANNEL_ID, fmt_trade_close(coin, dirn, "TP2 HIT", (1 - trade["targets"][1] / trade["entry_mid"])*100))
                        to_delete.append(key)
                    elif last_price >= trade["stop"]:
                        await post(TRADE_HISTORY_CHANNEL_ID, fmt_trade_close(coin, dirn, "STOP LOSS HIT", (1 - trade["stop"] / trade["entry_mid"])*100))
                        to_delete.append(key)

            for k in to_delete:
                open_trades.pop(k, None)
            if to_delete:
                save_state(open_trades)

            # Open new setup if no open trade in that direction
            if setup:
                key = f"{coin}|{setup['direction']}"
                if key not in open_trades:
                    await post(CRYPTO_SETUP_CHANNEL_ID, fmt_setup_block(coin, setup, change_24h))
                    await post(TRADE_HISTORY_CHANNEL_ID, fmt_trade_open(coin, setup))
                    entry_mid = (setup["entry_low"] + setup["entry_high"]) / 2
                    open_trades[key] = {
                        "coin": coin,
                        "direction": setup["direction"],
                        "entry_low": setup["entry_low"],
                        "entry_high": setup["entry_high"],
                        "entry_mid": entry_mid,
                        "stop": setup["stop"],
                        "targets": setup["targets"],
                        "opened_at": datetime.now(timezone.utc).isoformat(),
                    }
                    save_state(open_trades)

            # tiny pause between coins to be kind to API
            await asyncio.sleep(0.2)

        next_scan_eta = f"{SCAN_INTERVAL_SEC}s"
    except Exception as e:
        log.exception(f"[scan] unhandled: {e}")

@crypto_scan_loop.before_loop
async def before_loop():
    await bot.wait_until_ready()
    log.info("crypto_scan_loop starting…")

# ───────── COMMANDS ─────────
@bot.command()
async def status(ctx):
    """Show scanner status and open trades"""
    lines = [
        f"Scanner: **ON** every {SCAN_INTERVAL_SEC}s",
        f"Coins: {', '.join(COIN_IDS)}",
        f"Risk Mode: **{RISK_MODE}**",
        f"Open trades: {len(open_trades)}",
    ]
    await ctx.reply("\n".join(lines))

@bot.command()
async def testcrypto(ctx):
    """Send a test setup block (ETH bullish dummy)"""
    dummy = {
        "direction": "bull",
        "entry_low": 3000.00,
        "entry_high": 3008.00,
        "stop": 2946.00,
        "targets": [3021.0, 3054.0, 3090.0],
        "confidence": 86,
        "tf": "30m",
        "momentum": "Moderate",
        "ref_price": 3004.0,
    }
    msg = fmt_setup_block("ethereum", dummy, 6.2)
    await ctx.reply(msg)

@bot.command()
@commands.has_permissions(administrator=True)
async def resetstate(ctx):
    """Admin: clears open trade state"""
    global open_trades
    open_trades = {}
    save_state(open_trades)
    await ctx.reply("State cleared ✅")

# ───────── LIFECYCLE ─────────
@bot.event
async def on_ready():
    log.info(f"✅ Logged in as {bot.user} ({bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="JCF HQ online"))

    await post(CRYPTO_SETUP_CHANNEL_ID, "✅ **Crypto scanner online** — EMA+BB+OB mode activated.")
    await post(CRYPTO_SETUP_CHANNEL_ID, f"✅ **Crypto scanner online** — Risk: **{RISK_MODE}**. Coins: {', '.join(COIN_IDS)}")

    if not crypto_scan_loop.is_running():
        crypto_scan_loop.start()

# ───────── BOOT ─────────
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN is missing")
    if not CRYPTO_SETUP_CHANNEL_ID or not TRADE_HISTORY_CHANNEL_ID:
        raise SystemExit("Channel IDs missing (CRYPTO_SETUP_CHANNEL_ID / TRADE_HISTORY_CHANNEL_ID)")
    if not COIN_IDS:
        raise SystemExit("COIN_IDS is empty")
    bot.run(DISCORD_TOKEN)