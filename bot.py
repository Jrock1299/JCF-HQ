import os, json, asyncio, logging, math, statistics as stats, time, csv
from datetime import datetime, timedelta, timezone
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

# Earnings vars
EARNINGS_CHANNEL_ID = int(os.getenv("EARNINGS_CHANNEL_ID", "0"))
EARNINGS_POST_HOUR_UTC = int(os.getenv("EARNINGS_POST_HOUR_UTC", "13"))  # 13=8am ET (approx)
EARNINGS_MAX_COUNT = int(os.getenv("EARNINGS_MAX_COUNT", "15"))
EARNINGS_EXPECTATION_MODE = os.getenv("EARNINGS_EXPECTATION_MODE", "momentum").lower()
MOM_LOOKBACK = int(os.getenv("EARNINGS_MOM_LOOKBACK_DAYS", "20"))
MOM_BEAT = float(os.getenv("EARNINGS_MOM_BEAT_THRESH_PCT", "5"))
MOM_MISS = float(os.getenv("EARNINGS_MOM_MISS_THRESH_PCT", "-5"))

API_BASE = "https://api.coingecko.com/api/v3"
HEADERS = {"accept": "application/json"}
if CG_KEY:
    HEADERS["x-cg-demo-api-key"] = CG_KEY

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO),
                    format="%(levelname)s:%(name)s:%(message)s")
log = logging.getLogger("jcf-hq")

# ───────── DISCORD ─────────
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ───────── STATE (persisted open trades + earnings) ─────────
STATE_PATH = "/tmp/jcf_open_trades.json"
EARNINGS_STATE_PATH = "/tmp/jcf_earnings_state.json"

def load_json(path, default):
    try:
        if not os.path.exists(path):
            return default
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, obj):
    try:
        with open(path, "w") as f:
            json.dump(obj, f)
    except Exception as e:
        log.warning(f"could not save state ({path}): {e}")

open_trades = load_json(STATE_PATH, {})
earn_state = load_json(EARNINGS_STATE_PATH, {"last_daily_date": ""})

next_scan_eta = "n/a"

# ───────── TECH (crypto) ─────────
def ema(series, period):
    if len(series) < period:
        return None
    k = 2 / (period + 1)
    e = series[0]
    for v in series[1:]:
        e = v * k + e * (1 - k)
    return e

def bollinger(series, period=20, mult=2.0):
    if len(series) < period: return (None, None, None)
    last = series[-period:]
    mean = sum(last)/period
    std = math.sqrt(sum((x-mean)**2 for x in last)/period)
    return (mean - mult*std, mean, mean + mult*std)

def recent_pivot(series, lookback=5, mode="high"):
    if len(series) < lookback*2+1: return None
    window = series[-(lookback*2+1):]
    mid = window[lookback]
    if mode == "high": return mid if mid == max(window) else None
    return mid if mid == min(window) else None

RISK_PRESETS = {
    "conservative": {"stop": 1.8, "tp1": 0.7, "tp2": 1.2, "tp3": 1.8},
    "balanced":     {"stop": 2.2, "tp1": 1.0, "tp2": 1.6, "tp3": 2.4},
    "aggressive":   {"stop": 3.0, "tp1": 1.4, "tp2": 2.2, "tp3": 3.0},
}
R = RISK_PRESETS.get(RISK_MODE, RISK_PRESETS["conservative"])

# ───────── DATA (crypto) ─────────
def get_market_prices(coin_id, days="1", interval="minute"):
    # CoinGecko market_chart
    url = f"{API_BASE}/coins/{coin_id}/market_chart"
    params = {"vs_currency": "usd", "days": days, "interval": interval}
    r = requests.get(url, params=params, headers=HEADERS, timeout=20)
    if r.status_code in (400, 401, 429):
        # fallback: try without interval (demo compatibility) with tiny sleep for rate limiting
        time.sleep(0.25)
        params = {"vs_currency": "usd", "days": days}
        r = requests.get(url, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()
    return [p[1] for p in data.get("prices", [])]

def get_simple_changes(ids):
    url = f"{API_BASE}/simple/price"
    params = {"ids": ",".join(ids), "vs_currencies": "usd", "include_24hr_change": "true"}
    r = requests.get(url, params=params, headers=HEADERS, timeout=20)
    # if throttled, just return empty map; scanner still runs
    if r.status_code in (401, 429):
        return {}
    r.raise_for_status()
    return r.json()

# ───────── SIGNAL LOGIC (crypto) ─────────
def build_setup(coin, prices):
    if len(prices) < 120:
        return None
    tail = prices[-600:]
    ds = tail[::5]
    ema50  = ema(ds, 50)  if len(ds) >= 50  else None
    ema200 = ema(ds, 200) if len(ds) >= 200 else None
    lb, mid, ub = bollinger(ds, 20, 2.0)
    price = ds[-1]
    if not all([ema50, ema200, lb, ub]): return None

    piv_hi = recent_pivot(ds, 5, "high")
    piv_lo = recent_pivot(ds, 5, "low")

    bull_bias = price > ema50 and price > ema200 and price <= lb*1.01 and piv_lo is not None
    bear_bias = price < ema50 and price < ema200 and price >= ub*0.99 and piv_hi is not None
    if not (bull_bias or bear_bias): return None

    direction = "bull" if bull_bias else "bear"
    if direction == "bull":
        entry_low, entry_high = price*0.997, price*1.003
        stop = price * (1 - R["stop"]/100.0)
        t1, t2, t3 = (price*(1+R["tp1"]/100.0),
                      price*(1+R["tp2"]/100.0),
                      price*(1+R["tp3"]/100.0))
    else:
        entry_low, entry_high = price*0.997, price*1.003
        stop = price * (1 + R["stop"]/100.0)
        t1, t2, t3 = (price*(1-R["tp1"]/100.0),
                      price*(1-R["tp2"]/100.0),
                      price*(1-R["tp3"]/100.0))

    dist_bb = abs(price - (lb if direction=="bull" else ub)) / price
    ema_sep = abs(ema50 - ema200) / price
    conf = 60 + int(min(30, ema_sep*1000)) - int(min(10, dist_bb*1000))
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

# ───────── MESSAGE BUILDERS (crypto) ─────────
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

async def post(channel_id: int, content: str):
    ch = bot.get_channel(channel_id)
    if ch:
        await ch.send(content)

# ───────── CORE SCAN LOOP (crypto) ─────────
@tasks.loop(seconds=SCAN_INTERVAL_SEC)
async def crypto_scan_loop():
    global next_scan_eta, open_trades
    try:
        next_scan_eta = f"{SCAN_INTERVAL_SEC}s"
        # 24h change map
        try:
            change_map = get_simple_changes(COIN_IDS)
        except Exception as e:
            log.warning(f"[scan] simple/price change fetch failed: {e}")
            change_map = {}

        # small pacing to be gentle on demo limits
        for coin in COIN_IDS:
            try:
                prices = get_market_prices(coin, days="1", interval="minute")
            except Exception as e:
                log.error(f"[scan] {coin}: {e}")
                await asyncio.sleep(0.3)
                continue
            if len(prices) < 60:
                continue

            setup = build_setup(coin, prices)
            last_price = prices[-1]
            change_24h = 0.0
            if isinstance(change_map.get(coin), dict):
                try:
                    change_24h = float(change_map[coin].get("usd_24h_change", 0.0))
                except Exception:
                    pass

            # manage existing open trade for this coin
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
                save_json(STATE_PATH, open_trades)

            # maybe open a new setup (dedupe key)
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
                    save_json(STATE_PATH, open_trades)

        next_scan_eta = f"{SCAN_INTERVAL_SEC}s"
    except Exception as e:
        log.exception(f"[scan] unhandled: {e}")

@crypto_scan_loop.before_loop
async def before_crypto_loop():
    await bot.wait_until_ready()
    log.info("crypto_scan_loop starting…")

# ───────── COMMANDS (crypto) ─────────
@bot.command()
async def status(ctx):
    lines = [
        f"Scanner: **ON** every {SCAN_INTERVAL_SEC}s",
        f"Coins: {', '.join(COIN_IDS)}",
        f"Risk Mode: **{RISK_MODE}**",
        f"Open trades: {len(open_trades)}",
    ]
    await ctx.reply("\n".join(lines))

@bot.command()
async def testcrypto(ctx):
    dummy = {
        "direction": "bull",
        "entry_low": 3000.00, "entry_high": 3008.00, "stop": 2946.00,
        "targets": [3021.0, 3054.0, 3090.0],
        "confidence": 86, "tf": "30m", "momentum": "Moderate", "ref_price": 3004.0,
    }
    msg = fmt_setup_block("ethereum", dummy, 6.2)
    await ctx.reply(msg)

@bot.command()
@commands.has_permissions(administrator=True)
async def resetstate(ctx):
    global open_trades
    open_trades = {}
    save_json(STATE_PATH, open_trades)
    await ctx.reply("State cleared ✅")

# ───────── EARNINGS: helpers (no-key sources) ─────────
# Nasdaq daily earnings calendar (public)
NASDAQ_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json, text/plain, */*",
}

def nasdaq_calendar(date_str):
    # date_str 'YYYY-MM-DD'
    url = f"https://api.nasdaq.com/api/calendar/earnings?date={date_str}"
    r = requests.get(url, headers=NASDAQ_HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()
    items = (data.get("data") or {}).get("rows") or []
    results = []
    for it in items:
        sym = (it.get("symbol") or "").upper()
        name = it.get("companyName") or it.get("companyname") or ""
        when = (it.get("epsTime") or "").upper()  # BMO/AMC/— 
        mcap = it.get("marketCap")
        try:
            mcap = float(mcap.replace(",","")) if isinstance(mcap, str) else float(mcap or 0)
        except Exception:
            mcap = 0.0
        results.append({"symbol": sym, "name": name, "when": when, "marketCap": mcap})
    # sort by market cap desc
    results.sort(key=lambda x: x["marketCap"], reverse=True)
    return results

def stooq_history_daily(symbol, days=220):
    # Stooq uses symbols like aapl, msft, tsla; returns CSV daily history
    sym = symbol.lower()
    url = f"https://stooq.com/q/d/l/?s={sym}&i=d"
    r = requests.get(url, timeout=20)
    if r.status_code != 200 or "Date,Open,High,Low,Close,Volume" not in r.text:
        return []
    rows = list(csv.DictReader(r.text.splitlines()))
    closes = [float(row["Close"]) for row in rows if row.get("Close") not in (None, "", "0")]
    return closes[-days:]

def sma(values, n):
    if len(values) < n: return None
    return sum(values[-n:]) / n

def momentum_label(symbol):
    try:
        closes = stooq_history_daily(symbol, days=max(200, MOM_LOOKBACK+5))
        if len(closes) < MOM_LOOKBACK+1:
            return ("neutral", 0.0, None, None)
        change = (closes[-1]/closes[-(MOM_LOOKBACK+1)] - 1) * 100
        s50 = sma(closes, 50)
        s200 = sma(closes, 200)
        above50 = closes[-1] > (s50 or closes[-1])
        above200 = closes[-1] > (s200 or closes[-1])
        label = "neutral"
        if change >= MOM_BEAT and above50:
            label = "likely beat"
        if change <= MOM_MISS and not above50 and not above200:
            label = "likely miss"
        return (label, round(change,2), s50, s200)
    except Exception as e:
        log.warning(f"[earn] momentum check failed for {symbol}: {e}")
        return ("neutral", 0.0, None, None)

def fmt_earnings_card(entry):
    sym, name, when = entry["symbol"], entry["name"], entry["when"] or "—"
    label, chg, s50, s200 = momentum_label(sym)
    label_icon = {"likely beat":"🟢", "likely miss":"🔴", "neutral":"🟡"}[label]
    line1 = f"**{sym}** — {name}  •  {when}"
    line2 = f"{label_icon} *{label.upper()}*  |  20D: {chg:+.2f}%"
    return f"{line1}\n{line2}"

async def post_earnings_today():
    if not EARNINGS_CHANNEL_ID:
        return
    today = datetime.utcnow().date().isoformat()
    try:
        items = nasdaq_calendar(today)
        if not items:
            await post(EARNINGS_CHANNEL_ID, f"📅 **Today’s Earnings** — no major listings found.")
            return
        top = items[:EARNINGS_MAX_COUNT]
        blocks = [fmt_earnings_card(x) for x in top]
        msg = "📅 **Today’s Earnings (Top by Mkt Cap)**\n" + "\n\n".join(blocks)
        await post(EARNINGS_CHANNEL_ID, msg)
    except Exception as e:
        log.exception(f"[earn] today fetch failed: {e}")
        await post(EARNINGS_CHANNEL_ID, "⚠️ Could not fetch today’s earnings.")

async def post_earnings_week():
    if not EARNINGS_CHANNEL_ID:
        return
    start = datetime.utcnow().date()
    days = [start + timedelta(days=i) for i in range(7)]
    try:
        out = ["🗓 **Weekly Earnings (Top {n}/day)**".format(n=EARNINGS_MAX_COUNT)]
        for d in days:
            ds = d.isoformat()
            items = nasdaq_calendar(ds)[:EARNINGS_MAX_COUNT]
            if not items: 
                continue
            header = f"\n**{ds}**"
            lines = [fmt_earnings_card(x) for x in items]
            out.append(header + "\n" + "\n".join(lines))
        await post(EARNINGS_CHANNEL_ID, "\n".join(out))
    except Exception as e:
        log.exception(f"[earn] week fetch failed: {e}")
        await post(EARNINGS_CHANNEL_ID, "⚠️ Could not fetch weekly earnings.")

# ───────── EARNINGS SCHEDULER ─────────
@tasks.loop(minutes=20.0)
async def earnings_scheduler_loop():
    if not EARNINGS_CHANNEL_ID:
        return
    try:
        now = datetime.utcnow()
        if now.hour == EARNINGS_POST_HOUR_UTC:
            day_str = now.date().isoformat()
            if earn_state.get("last_daily_date") != day_str:
                await post_earnings_today()
                earn_state["last_daily_date"] = day_str
                save_json(EARNINGS_STATE_PATH, earn_state)
    except Exception as e:
        log.warning(f"[earn] scheduler loop error: {e}")

@earnings_scheduler_loop.before_loop
async def before_earn_loop():
    await bot.wait_until_ready()
    log.info("earnings_scheduler_loop starting…")

# ───────── EARNINGS COMMANDS ─────────
@bot.command()
async def earnings(ctx, arg="today"):
    arg = (arg or "today").lower()
    if arg == "today":
        await post_earnings_today()
        await ctx.message.add_reaction("✅")
    elif arg == "week":
        await post_earnings_week()
        await ctx.message.add_reaction("✅")
    else:
        # treat as ticker card
        sym = arg.upper()
        label, chg, s50, s200 = momentum_label(sym)
        label_icon = {"likely beat":"🟢", "likely miss":"🔴", "neutral":"🟡"}[label]
        lines = [
            f"**{sym}** — Momentum snapshot",
            f"{label_icon} *{label.upper()}*",
            f"20D change: {chg:+.2f}%",
            f"50DMA: {('n/a' if s50 is None else f'{s50:.2f}')}",
            f"200DMA: {('n/a' if s200 is None else f'{s200:.2f}')}",
        ]
        await ctx.reply("\n".join(lines))

# ───────── LIFECYCLE ─────────
@bot.event
async def on_ready():
    log.info(f"✅ Logged in as {bot.user} ({bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="JCF HQ online"))

    # crypto announces
    await post(CRYPTO_SETUP_CHANNEL_ID, "✅ **Crypto scanner online** — EMA+BB+OB mode activated.")
    await post(CRYPTO_SETUP_CHANNEL_ID, f"✅ **Crypto scanner online** — Risk: **{RISK_MODE}**. Coins: {', '.join(COIN_IDS)}")

    if not crypto_scan_loop.is_running():
        crypto_scan_loop.start()
    if not earnings_scheduler_loop.is_running():
        earnings_scheduler_loop.start()

# ───────── BOOT ─────────
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN is missing")
    if not CRYPTO_SETUP_CHANNEL_ID or not TRADE_HISTORY_CHANNEL_ID:
        raise SystemExit("Channel IDs missing (CRYPTO_SETUP_CHANNEL_ID / TRADE_HISTORY_CHANNEL_ID)")
    if not COIN_IDS:
        raise SystemExit("COIN_IDS is empty")
    bot.run(DISCORD_TOKEN)