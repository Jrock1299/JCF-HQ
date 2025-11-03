import os, json, asyncio, logging, math
from datetime import datetime, timezone
import requests
import discord
from discord.ext import commands, tasks

# ───────── CONFIG FROM ENV ─────────
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CRYPTO_SETUP_CHANNEL_ID = int(os.getenv("CRYPTO_SETUP_CHANNEL_ID", "0"))
TRADE_HISTORY_CHANNEL_ID = int(os.getenv("TRADE_HISTORY_CHANNEL_ID", "0"))

COIN_IDS = [c.strip().lower() for c in os.getenv("COIN_IDS", "").split(",") if c.strip()]
SCAN_INTERVAL_SEC = int(os.getenv("SCAN_INTERVAL_SEC", "300"))
RISK_MODE = os.getenv("RISK_MODE", "conservative").lower()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
CG_KEY = os.getenv("COINGECKO_API_KEY", "").strip()

API_BASE = "https://api.coingecko.com/api/v3"
HEADERS = {"accept": "application/json"}
if CG_KEY:
    # CoinGecko demo key header
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

open_trades = load_state()   # { key: {..., log_msg_id:int} }
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

# Risk presets (% of price)
RISK_PRESETS = {
    "conservative": {"stop": 1.8, "tp1": 0.7, "tp2": 1.2, "tp3": 1.8},
    "balanced":     {"stop": 2.2, "tp1": 1.0, "tp2": 1.6, "tp3": 2.4},
    "aggressive":   {"stop": 3.0, "tp1": 1.4, "tp2": 2.2, "tp3": 3.0},
}
R = RISK_PRESETS.get(RISK_MODE, RISK_PRESETS["conservative"])

# ───────── DATA FETCH ─────────
def get_market_prices(coin_id, days="1", interval="minute"):
    url = f"{API_BASE}/coins/{coin_id}/market_chart"
    params = {"vs_currency": "usd", "days": days, "interval": interval}
    r = requests.get(url, params=params, headers=HEADERS, timeout=20)
    if r.status_code == 400:
        # fallback if minute interval not allowed on demo; use default interval
        params = {"vs_currency": "usd", "days": days}
        r = requests.get(url, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()
    prices = [p[1] for p in data.get("prices", [])]
    return prices

def get_simple_changes(ids):
    url = f"{API_BASE}/simple/price"
    params = {"ids": ",".join(ids), "vs_currencies": "usd", "include_24hr_change": "true"}
    r = requests.get(url, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.json()  # {id: {"usd": x, "usd_24h_change": y}}

# ───────── SIGNAL LOGIC ─────────
def build_setup(coin, prices):
    if len(prices) < 120:
        return None

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

# ───────── MESSAGE BUILDERS (setups) ─────────
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

# ───────── TRADE HISTORY LOGGER ─────────
def _fmt_dt(ts: float | None = None):
    dt = datetime.fromtimestamp(ts or datetime.now(timezone.utc).timestamp(), tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")

def _trade_key(symbol: str, side: str):
    return f"{symbol.upper()}|{side.lower()}"

async def post_trade_open(bot_obj, trade: dict):
    """
    trade = {
      "symbol": "ETH", "timeframe": "30m", "side": "long",
      "entry": "3000.00 – 3008.00", "sl": "2975.00",
      "targets": ["3020.00","3040.00","3060.00"],
      "rr": 1.8, "confidence": 90, "reason": "EMA+BB+OB", "id": "ETH-30m-..."
    }
    """
    ch = bot_obj.get_channel(TRADE_HISTORY_CHANNEL_ID)
    if not ch:
        return

    header = f"📗 **OPEN** {trade['symbol']} — {trade['side'].upper()} ({trade.get('timeframe','')})"
    body = (
        f"• Entry: {trade['entry']}\n"
        f"• Stop: {trade['sl']}\n"
        f"• Targets: {' / '.join(trade['targets'])}\n"
        f"• R:R: {trade.get('rr','–')}\n"
        f"• Confidence: {trade.get('confidence','–')}%\n"
        f"• Reason: {trade.get('reason','–')}\n"
        f"• Opened: {_fmt_dt()}\n"
        f"• ID: `{trade.get('id','n/a')}`"
    )
    msg = await ch.send(f"{header}\n```{body}```")

    key = _trade_key(trade["symbol"], trade["side"])
    open_trades[key] = {
        "trade": trade,
        "opened_at": datetime.now(timezone.utc).timestamp(),
        "log_msg_id": msg.id,
    }
    save_state(open_trades)

async def post_trade_close(bot_obj, symbol: str, side: str, result: str, price: str, pnl: str, note: str = ""):
    ch = bot_obj.get_channel(TRADE_HISTORY_CHANNEL_ID)
    if not ch:
        return

    key = _trade_key(symbol, side)
    rec = open_trades.pop(key, None)
    save_state(open_trades)

    tag = "✅" if result.upper().startswith("TP") else "❌" if result.upper()=="SL" else "🟨"
    duration = ""

    if rec:
        opened_ts = rec.get("opened_at")
        if opened_ts:
            dur_sec = int(datetime.now(timezone.utc).timestamp() - opened_ts)
            hrs = dur_sec // 3600
            mins = (dur_sec % 3600) // 60
            duration = f" • Duration: {hrs}h {mins}m"

        try:
            msg = await ch.fetch_message(rec["log_msg_id"])
            trade = rec["trade"]
            header = f"📕 **CLOSED** {trade['symbol']} — {trade['side'].upper()} ({trade.get('timeframe','')})"
            body = (
                f"• Entry: {trade['entry']}\n"
                f"• Stop: {trade['sl']}\n"
                f"• Targets: {' / '.join(trade['targets'])}\n"
                f"• Result: {result} at {price}\n"
                f"• PnL: {pnl}{duration}\n"
                f"• Reason: {note or trade.get('reason','–')}\n"
                f"• Closed: {_fmt_dt()}\n"
                f"• ID: `{trade.get('id','n/a')}`"
            )
            await msg.edit(content=f"{header}\n```{body}```")
        except Exception:
            pass

    await ch.send(f"{tag} **CLOSE** {symbol.upper()} — {side.upper()} • {result} at {price} • PnL {pnl}" + duration + (f" — {note}" if note else ""))

# ───────── SIMPLE POST HELPER ─────────
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
            change_map = get_simple_changes(COIN_IDS)
        except Exception as e:
            log.warning(f"[scan] simple/price change fetch failed: {e}")

        for coin in COIN_IDS:
            try:
                prices = get_market_prices(coin, days="1", interval="minute")
            except Exception as e:
                log.error(f"[scan] {coin}: {e}")
                await asyncio.sleep(0.2)
                continue
            if len(prices) < 60:
                continue

            setup = build_setup(coin, prices)
            last_price = prices[-1]
            change_24h = 0.0
            if isinstance(change_map.get(coin), dict):
                change_24h = float(change_map[coin].get("usd_24h_change", 0.0))

            # Manage existing open trade for this coin
            to_delete = []
            for key, trade in list(open_trades.items()):
                if trade.get("coin") != coin:
                    continue
                dirn = trade["direction"]
                if dirn == "bull":
                    if last_price >= trade["targets"][1]:
                        pnl_pct = (trade["targets"][1] / trade["entry_mid"] - 1) * 100
                        await post_trade_close(bot, coin, "long", "TP2", f"{trade['targets'][1]:.4f}", f"{pnl_pct:+.2f}%")
                        to_delete.append(key)
                    elif last_price <= trade["stop"]:
                        pnl_pct = (trade["stop"] / trade["entry_mid"] - 1) * 100
                        await post_trade_close(bot, coin, "long", "SL", f"{trade['stop']:.4f}", f"{pnl_pct:+.2f}%")
                        to_delete.append(key)
                else:
                    if last_price <= trade["targets"][1]:
                        pnl_pct = (1 - trade["targets"][1] / trade["entry_mid"]) * 100
                        await post_trade_close(bot, coin, "short", "TP2", f"{trade['targets'][1]:.4f}", f"{pnl_pct:+.2f}%")
                        to_delete.append(key)
                    elif last_price >= trade["stop"]:
                        pnl_pct = (1 - trade["stop"] / trade["entry_mid"]) * 100
                        await post_trade_close(bot, coin, "short", "SL", f"{trade['stop']:.4f}", f"{pnl_pct:+.2f}%")
                        to_delete.append(key)

            for k in to_delete:
                open_trades.pop(k, None)
            if to_delete:
                save_state(open_trades)

            # Maybe open new trade
            if setup:
                key = f"{coin}|{setup['direction']}"
                if key not in open_trades:
                    # Post to setups
                    await post(CRYPTO_SETUP_CHANNEL_ID, fmt_setup_block(coin, setup, change_24h))

                    # Build trade dict for logger
                    side = "long" if setup["direction"] == "bull" else "short"
                    entry_mid = (setup["entry_low"] + setup["entry_high"]) / 2
                    trade_dict = {
                        "symbol": coin.upper(),
                        "timeframe": setup["tf"],
                        "side": side,
                        "entry": f"{setup['entry_low']:.4f} – {setup['entry_high']:.4f}",
                        "sl": f"{setup['stop']:.4f}",
                        "targets": [f"{setup['targets'][0]:.4f}", f"{setup['targets'][1]:.4f}", f"{setup['targets'][2]:.4f}"],
                        "rr": rr_to_tp2(setup),
                        "confidence": setup["confidence"],
                        "reason": "EMA+BB+OB",
                        "id": f"{coin}-{setup['tf']}-{int(datetime.now(timezone.utc).timestamp())}"
                    }
                    await post_trade_open(bot, trade_dict)

                    # Persist open
                    open_trades[key] = {
                        "coin": coin,
                        "direction": setup["direction"],
                        "entry_low": setup["entry_low"],
                        "entry_high": setup["entry_high"],
                        "entry_mid": entry_mid,
                        "stop": setup["stop"],
                        "targets": setup["targets"],
                        "opened_at": datetime.now(timezone.utc).isoformat(),
                        # post_trade_open() also stores log_msg_id in open_trades via trade key with side;
                        # keep this minimal record for scanner checks:
                    }
                    save_state(open_trades)

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

# --- NEW: trade-history test & manual close ---
@bot.command()
async def logtest(ctx):
    """Posts a sample OPEN to 📜-trade-history then auto-closes it after 10s."""
    sample = {
        "symbol": "ETH",
        "timeframe": "30m",
        "side": "long",
        "entry": "3000.00 – 3008.00",
        "sl": "2975.00",
        "targets": ["3020.00","3040.00","3060.00"],
        "rr": 1.8,
        "confidence": 90,
        "reason": "EMA+BB+OB confluence",
        "id": "ETH-30m-demo"
    }
    await post_trade_open(bot, sample)
    await ctx.reply("Posted sample OPEN to 📜-trade-history.")
    try:
        await asyncio.sleep(10)
        await post_trade_close(bot, "ETH", "long", "TP2", "3040.00", "+1.3%", "demo close")
    except Exception:
        pass

@bot.command()
async def closeit(ctx, symbol: str, side: str, result: str, price: str, pnl: str, *, note: str = ""):
    """
    Manually close and log an open trade.
    Example: !closeit eth long TP1 3040 +1.2% partials hit
    """
    await post_trade_close(bot, symbol, side, result, price, pnl, note)
    await ctx.reply("Close logged.")

# ───────── LIFECYCLE ─────────
@bot.event
async def on_ready():
    log.info(f"✅ Logged in as {bot.user} ({bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="JCF HQ online"))

    # Announce mode & settings once
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