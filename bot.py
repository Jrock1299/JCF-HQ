import os, json, asyncio, logging, math
from datetime import datetime, timezone, timedelta
import requests

import discord
from discord.ext import commands, tasks

# ──────────────────────────────
# CONFIG (ENV)
# ──────────────────────────────
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()

# Channels
CRYPTO_SETUP_CHANNEL_ID   = int(os.getenv("CRYPTO_SETUP_CHANNEL_ID", "0"))
TRADE_HISTORY_CHANNEL_ID  = int(os.getenv("TRADE_HISTORY_CHANNEL_ID", "0"))
EARNINGS_CHANNEL_ID       = int(os.getenv("EARNINGS_CHANNEL_ID", "0"))

# Crypto scanning
COIN_IDS          = [c.strip().lower() for c in os.getenv("COIN_IDS", "").split(",") if c.strip()]
SCAN_INTERVAL_SEC = int(os.getenv("SCAN_INTERVAL_SEC", "300"))
RISK_MODE         = os.getenv("RISK_MODE", "conservative").lower()
LOG_LEVEL         = os.getenv("LOG_LEVEL", "INFO").upper()
CG_KEY            = os.getenv("COINGECKO_API_KEY", "").strip()

# Earnings
EARNINGS_TOP_N           = int(os.getenv("EARNINGS_TOP_N", "15"))
EARNINGS_SUMMARY_DAY     = os.getenv("EARNINGS_SUMMARY_DAY", "mon").strip().lower()
EARNINGS_SUMMARY_HOUR_UTC= int(os.getenv("EARNINGS_SUMMARY_HOUR_UTC", "14"))
FINNHUB_API_KEY          = os.getenv("FINNHUB_API_KEY", "").strip()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(levelname)s:%(name)s:%(message)s"
)
log = logging.getLogger("jcf-hq")

# ──────────────────────────────
# HTTP CONFIG
# ──────────────────────────────
CG_API_BASE = "https://api.coingecko.com/api/v3"
CG_HEADERS  = {"accept": "application/json"}
if CG_KEY:
    CG_HEADERS["x-cg-demo-api-key"] = CG_KEY  # Demo header for free key

FINNHUB_BASE = "https://finnhub.io/api/v1"
FH_HEADERS   = {"X-Finnhub-Token": FINNHUB_API_KEY} if FINNHUB_API_KEY else {}

# ──────────────────────────────
# DISCORD BOT
# ──────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ──────────────────────────────
# STATE
# ──────────────────────────────
STATE_PATH = "/tmp/jcf_open_trades.json"
EARNINGS_META_PATH = "/tmp/jcf_earnings_meta.json"

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
        log.warning(f"could not save {path}: {e}")

open_trades = load_json(STATE_PATH, {})   # { key: {...} }
earnings_meta = load_json(EARNINGS_META_PATH, {"last_posted_week": None})

next_scan_eta = "n/a"

# ──────────────────────────────
# TECH UTILS (EMA, BB, PIVOT)
# ──────────────────────────────
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
    var  = sum((x - mean) ** 2 for x in last) / period
    std  = math.sqrt(var)
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

# ──────────────────────────────
# COINGECKO FETCHERS
# ──────────────────────────────
def cg_market_prices(coin_id, days="1", interval="minute"):
    """Return list of floats [prices...] for given coin via CoinGecko market_chart."""
    url = f"{CG_API_BASE}/coins/{coin_id}/market_chart"
    params = {"vs_currency": "usd", "days": days, "interval": interval}
    r = requests.get(url, params=params, headers=CG_HEADERS, timeout=20)
    if r.status_code == 400:
        # demo plan often rejects minute interval → retry without interval
        params = {"vs_currency": "usd", "days": days}
        r = requests.get(url, params=params, headers=CG_HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()
    return [p[1] for p in data.get("prices", [])]

def cg_simple_changes(ids):
    """Return 24h change map for ids using /simple/price."""
    if not ids:
        return {}
    url = f"{CG_API_BASE}/simple/price"
    params = {"ids": ",".join(ids), "vs_currencies": "usd", "include_24hr_change": "true"}
    r = requests.get(url, params=params, headers=CG_HEADERS, timeout=20)
    r.raise_for_status()
    return r.json()

# ──────────────────────────────
# SIGNAL BUILDERS
# ──────────────────────────────
def build_setup(coin, prices):
    """
    Confluence: EMA(50/200) trend + BB extremes + pivot proxy.
    Returns dict or None.
    """
    if len(prices) < 120:
        return None

    tail = prices[-600:]
    ds = tail[::5]  # smooth

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
        risk   = setup["entry_high"] - setup["stop"]
        reward = setup["targets"][1] - setup["entry_low"]
    else:
        risk   = setup["stop"] - setup["entry_low"]
        reward = setup["entry_high"] - setup["targets"][1]
    return round(reward / risk, 2) if risk > 0 else 0.0

# ──────────────────────────────
# MESSAGE BUILDERS (CRYPTO)
# ──────────────────────────────
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

# ──────────────────────────────
# CRYPTO SCAN LOOP
# ──────────────────────────────
@tasks.loop(seconds=SCAN_INTERVAL_SEC)
async def crypto_scan_loop():
    global next_scan_eta, open_trades
    try:
        next_scan_eta = f"{SCAN_INTERVAL_SEC}s"
        # simple/price map
        change_map = {}
        try:
            change_map = cg_simple_changes(COIN_IDS)
        except Exception as e:
            log.warning(f"[scan] simple/price change fetch failed: {e}")

        for coin in COIN_IDS:
            try:
                prices = cg_market_prices(coin, days="1", interval="minute")
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

            # manage open trade exits
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

            # open new setups (dedupe by coin|direction)
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

# ──────────────────────────────
# EARNINGS HELPERS (FINNHUB)
# ──────────────────────────────
WEEKDAY_MAP = {"mon":0,"tue":1,"wed":2,"thu":3,"fri":4,"sat":5,"sun":6}

def this_week_monday_utc(dt_utc):
    return dt_utc - timedelta(days=dt_utc.weekday())

def week_range_utc(dt_utc):
    """Return (start_date_str, end_date_str) for Mon..Sun in UTC (YYYY-MM-DD)."""
    mon = this_week_monday_utc(dt_utc).date()
    sun = mon + timedelta(days=6)
    return mon.isoformat(), sun.isoformat()

def fetch_earnings_week(dt_utc):
    """Fetch earnings for the current week using Finnhub (if key provided)."""
    if not FINNHUB_API_KEY:
        return []
    start, end = week_range_utc(dt_utc)
    url = f"{FINNHUB_BASE}/calendar/earnings"
    params = {"from": start, "to": end}
    r = requests.get(url, params=params, headers=FH_HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json() or {}
    items = data.get("earningsCalendar", []) or data.get("earnings", []) or []
    # Normalize a tiny bit
    out = []
    for it in items:
        sym = it.get("symbol") or it.get("Symbol")
        date = it.get("date") or it.get("Date")
        time = it.get("hour") or it.get("Hour") or ""   # BMO/AMC/— (before/after market)
        eps_est = it.get("epsEstimate") or it.get("EpsEstimate")
        eps_act = it.get("epsActual") or it.get("EpsActual")
        rev_est = it.get("revenueEstimate") or it.get("RevenueEstimate")
        rev_act = it.get("revenueActual") or it.get("RevenueActual")
        if sym and date:
            out.append({
                "symbol": sym,
                "date": date,
                "hour": time,
                "eps_est": eps_est,
                "eps_act": eps_act,
                "rev_est": rev_est,
                "rev_act": rev_act,
            })
    return out

def fetch_market_cap(symbol):
    """Get market cap (USD) via profile2. If fails, return 0."""
    if not FINNHUB_API_KEY:
        return 0
    try:
        url = f"{FINNHUB_BASE}/stock/profile2"
        params = {"symbol": symbol}
        r = requests.get(url, params=params, headers=FH_HEADERS, timeout=10)
        r.raise_for_status()
        prof = r.json() or {}
        mc = prof.get("marketCapitalization") or prof.get("marketcap") or 0
        try:
            return float(mc)
        except:
            return 0
    except Exception:
        return 0

async def build_earnings_digest(dt_utc, top_n=15):
    """Build a markdown digest string for the week, ranked by market cap."""
    if not EARNINGS_CHANNEL_ID:
        return None, "EARNINGS_CHANNEL_ID not set."

    if not FINNHUB_API_KEY:
        return None, "FINNHUB_API_KEY not set — earnings digest disabled."

    items = fetch_earnings_week(dt_utc)
    if not items:
        return None, "No earnings found for this week (API returned empty)."

    # Collect unique symbols and attach market caps (rate-limited friendly)
    symbols = list({it["symbol"] for it in items})
    caps = {}
    # Cap the number of market cap requests to a sane amount
    for sym in symbols[:150]:
        caps[sym] = fetch_market_cap(sym)

    # Pick the biggest by cap that actually appear this week
    # Create a map date -> [symbols]
    by_date = {}
    for it in items:
        by_date.setdefault(it["date"], []).append(it)

    # Flatten and score by cap
    scored = []
    for it in items:
        mc = caps.get(it["symbol"], 0)
        scored.append((mc, it))
    scored.sort(reverse=True, key=lambda x: x[0])

    top = [it for _, it in scored[:top_n]]

    # Format
    mon, sun = week_range_utc(dt_utc)
    header = f"**🗓️ Earnings Leaks — Top {top_n} for {mon} → {sun} (UTC)**"
    lines = []
    for it in top:
        hour = it["hour"] or "—"
        est_ok = "✅" if (it["eps_est"] is not None or it["rev_est"] is not None) else "•"
        dir_hint = ""
        # As a *very* light hint: if rev_act and eps_act exist and both > estimates → likely "beat"
        if it["eps_act"] is not None and it["rev_act"] is not None and it["eps_est"] and it["rev_est"]:
            try:
                beat_eps = float(it["eps_act"]) > float(it["eps_est"])
                beat_rev = float(it["rev_act"]) > float(it["rev_est"])
                if beat_eps and beat_rev:
                    dir_hint = " (beat last reported)"
                elif (not beat_eps) and (not beat_rev):
                    dir_hint = " (miss last reported)"
            except Exception:
                pass
        lines.append(f"- **{it['symbol']}** — {it['date']} ({hour}) {est_ok}{dir_hint}")

    body = header + "\n" + "\n".join(lines)
    return body, None

# ──────────────────────────────
# EARNINGS SCHEDULER
# ──────────────────────────────
@tasks.loop(minutes=5.0)
async def earnings_scheduler_loop():
    """
    Every 5 minutes, check if it's the configured weekday/hour in UTC.
    Post once per week, tracked via EARNINGS_META_PATH.
    """
    try:
        now = datetime.now(timezone.utc)
        want_wd = WEEKDAY_MAP.get(EARNINGS_SUMMARY_DAY, 0)
        if now.weekday() != want_wd:
            return
        if now.hour != EARNINGS_SUMMARY_HOUR_UTC:
            return

        # week key = Monday ISO date
        wk_key = this_week_monday_utc(now).date().isoformat()
        last_posted = earnings_meta.get("last_posted_week")
        if last_posted == wk_key:
            return  # already posted this week

        digest, err = await build_earnings_digest(now, EARNINGS_TOP_N)
        if err:
            log.warning(f"[earnings] {err}")
            return
        if digest:
            await post(EARNINGS_CHANNEL_ID, digest)
            earnings_meta["last_posted_week"] = wk_key
            save_json(EARNINGS_META_PATH, earnings_meta)
    except Exception as e:
        log.exception(f"[earnings] scheduler error: {e}")

@earnings_scheduler_loop.before_loop
async def before_earnings_loop():
    await bot.wait_until_ready()
    log.info("earnings_scheduler_loop starting…")

# ──────────────────────────────
# COMMANDS
# ──────────────────────────────
@bot.command()
async def status(ctx):
    """Show scanner status and open trades + earnings schedule."""
    wd = EARNINGS_SUMMARY_DAY
    hr = EARNINGS_SUMMARY_HOUR_UTC
    coins = ", ".join(COIN_IDS) if COIN_IDS else "(none)"
    lines = [
        f"Scanner: **ON** every {SCAN_INTERVAL_SEC}s",
        f"Coins: {coins}",
        f"Risk Mode: **{RISK_MODE}**",
        f"Open trades: {len(open_trades)}",
        f"Earnings digest: {'ON' if EARNINGS_CHANNEL_ID and FINNHUB_API_KEY else 'OFF'} (posts {wd}@{hr:02d} UTC, Top {EARNINGS_TOP_N})"
    ]
    await ctx.reply("\n".join(lines))

@bot.command()
async def testcrypto(ctx):
    """Send a test crypto setup block (ETH bullish dummy)."""
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
    """Admin: clears open trade state."""
    global open_trades
    open_trades = {}
    save_json(STATE_PATH, open_trades)
    await ctx.reply("State cleared ✅")

@bot.command()
async def earningsnext(ctx):
    """Show a preview of the upcoming week's earnings digest."""
    now = datetime.now(timezone.utc)
    digest, err = await build_earnings_digest(now, EARNINGS_TOP_N)
    if err:
        await ctx.reply(f"⚠️ {err}")
    else:
        await ctx.reply(digest[:1900])  # keep under Discord limit a bit

@bot.command()
@commands.has_permissions(administrator=True)
async def earningsnow(ctx):
    """Admin: force-post the earnings digest to the configured channel."""
    now = datetime.now(timezone.utc)
    digest, err = await build_earnings_digest(now, EARNINGS_TOP_N)
    if err:
        await ctx.reply(f"⚠️ {err}")
        return
    await post(EARNINGS_CHANNEL_ID, digest)
    # mark this week as posted
    wk_key = this_week_monday_utc(now).date().isoformat()
    earnings_meta["last_posted_week"] = wk_key
    save_json(EARNINGS_META_PATH, earnings_meta)
    await ctx.reply("Earnings digest posted ✅")

# ──────────────────────────────
# LIFECYCLE
# ──────────────────────────────
@bot.event
async def on_ready():
    log.info(f"✅ Logged in as {bot.user} ({bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="JCF HQ online"))

    if CRYPTO_SETUP_CHANNEL_ID:
        await post(CRYPTO_SETUP_CHANNEL_ID, "✅ **Crypto scanner online** — EMA+BB+OB mode activated.")
        if COIN_IDS:
            await post(CRYPTO_SETUP_CHANNEL_ID, f"✅ **Crypto scanner online** — Risk: **{RISK_MODE}**. Coins: {', '.join(COIN_IDS)}")

    if not crypto_scan_loop.is_running() and COIN_IDS:
        crypto_scan_loop.start()

    # Earnings loop starts regardless; it will no-op if FINNHUB key is missing
    if not earnings_scheduler_loop.is_running():
        earnings_scheduler_loop.start()

# ──────────────────────────────
# BOOT
# ──────────────────────────────
if __name__ == "__main__":
    # hard checks
    if not DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN is missing")
    if not CRYPTO_SETUP_CHANNEL_ID or not TRADE_HISTORY_CHANNEL_ID:
        raise SystemExit("Channel IDs missing (CRYPTO_SETUP_CHANNEL_ID / TRADE_HISTORY_CHANNEL_ID)")
    if not COIN_IDS:
        raise SystemExit("COIN_IDS is empty")

    # earnings is optional: warn if misconfigured
    if EARNINGS_CHANNEL_ID and not FINNHUB_API_KEY:
        log.warning("EARNINGS_CHANNEL_ID set but FINNHUB_API_KEY is missing — earnings digest will be skipped.")

    bot.run(DISCORD_TOKEN)