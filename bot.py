import os
import asyncio
import random
from math import floor
from datetime import datetime, timezone

# Keep voice disabled to avoid audioop on cloud
os.environ.setdefault("DISCORD_NO_AUDIO", "1")

import discord
from discord.ext import commands, tasks

# =========================
# ENV / CONFIG
# =========================
TOKEN = os.getenv("DISCORD_TOKEN")

ANNOUNCE_CHANNEL_ID = int(os.getenv("ANNOUNCE_CHANNEL_ID", "0") or 0)
CRYPTO_CHANNEL_ID   = int(os.getenv("CRYPTO_SETUPS_CHANNEL_ID", "0") or 0)
STOCK_CHANNEL_ID    = int(os.getenv("STOCK_SETUPS_CHANNEL_ID", "0") or 0)
FOREX_CHANNEL_ID    = int(os.getenv("FOREX_SETUPS_CHANNEL_ID", "0") or 0)

CRYPTO_TICKERS = [s.strip().upper() for s in os.getenv("CRYPTO_TICKERS", "BTC,ETH,SOL").split(",") if s.strip()]
STOCK_TICKERS  = [s.strip().upper() for s in os.getenv("STOCK_TICKERS",  "NVDA,AAPL,TSLA,PLTR,SOFI,MSTR,OKLO").split(",") if s.strip()]
FOREX_TICKERS  = [s.strip().upper() for s in os.getenv("FOREX_TICKERS",  "XAUUSD,SPX,US30,USDJPY,EURUSD,GBPUSD").split(",") if s.strip()]

# Risk knobs (fraction e.g. 0.02 = 2%)
RISK_PCT_CRYPTO = float(os.getenv("RISK_PCT_CRYPTO", "0.02"))
RISK_PCT_STOCKS = float(os.getenv("RISK_PCT_STOCKS", "0.01"))
RISK_PCT_FOREX  = float(os.getenv("RISK_PCT_FOREX",  "0.015"))

# Confidence gates
MIN_CONF_CRYPTO = float(os.getenv("MIN_CONF_CRYPTO", "0.55"))
MIN_CONF_STOCKS = float(os.getenv("MIN_CONF_STOCKS", "0.55"))
MIN_CONF_FOREX  = float(os.getenv("MIN_CONF_FOREX",  "0.65"))

# Scan cadence (minutes)
CRYPTO_SCAN_MIN = int(os.getenv("CRYPTO_SCAN_MIN", "15"))
STOCK_SCAN_MIN  = int(os.getenv("STOCK_SCAN_MIN",  "15"))
FOREX_SCAN_MIN  = int(os.getenv("FOREX_SCAN_MIN",  "15"))

# Daily caps (max per UTC day)
CRYPTO_DAILY_CAP = int(os.getenv("CRYPTO_DAILY_CAP", "12"))
STOCK_DAILY_CAP  = int(os.getenv("STOCK_DAILY_CAP",  "12"))
FOREX_DAILY_CAP  = int(os.getenv("FOREX_DAILY_CAP",  "12"))

# AI / TP config
AI_SCAN_LOOP   = int(os.getenv("AI_SCAN_LOOP", "1"))
AI_TP_MODE     = os.getenv("AI_TP_MODE", "2TP_SL2BE")
AI_TP2_RR      = float(os.getenv("AI_TP2_RR", "2.0"))
ALLOW_DEMO     = os.getenv("ALLOW_DEMO", "1") == "1"

# Balances (support per-asset)
ACCOUNT_BALANCE_CRYPTO = os.getenv("ACCOUNT_BALANCE_CRYPTO")
ACCOUNT_BALANCE_STOCKS = os.getenv("ACCOUNT_BALANCE_STOCKS")
ACCOUNT_BALANCE_FOREX  = os.getenv("ACCOUNT_BALANCE_FOREX")
ACCOUNT_BALANCE_CRYPTO = float(ACCOUNT_BALANCE_CRYPTO) if ACCOUNT_BALANCE_CRYPTO else None
ACCOUNT_BALANCE_STOCKS = float(ACCOUNT_BALANCE_STOCKS) if ACCOUNT_BALANCE_STOCKS else None
ACCOUNT_BALANCE_FOREX  = float(ACCOUNT_BALANCE_FOREX)  if ACCOUNT_BALANCE_FOREX  else None

# ===== Stocks vehicle/option settings (your choices) =====
STOCK_VEHICLE_MODE = os.getenv("STOCK_VEHICLE_MODE", "HYBRID").upper()     # SHARES | OPTIONS | HYBRID
STOCK_OPTION_STYLE = os.getenv("STOCK_OPTION_STYLE", "SWING").upper()       # SWING
EXP_W_MIN = int(os.getenv("STOCK_OPTION_EXP_WEEKS_MIN", "2"))
EXP_W_MAX = int(os.getenv("STOCK_OPTION_EXP_WEEKS_MAX", "4"))
OPT_TP1 = float(os.getenv("OPTIONS_TP1_PCT", "0.25"))   # +25%
OPT_TP2 = float(os.getenv("OPTIONS_TP2_PCT", "0.55"))   # +55%
OPT_SL  = float(os.getenv("OPTIONS_SL_PCT",  "0.22"))   # -22%

# =========================
# DISCORD BOOT
# =========================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# =========================
# UTIL
# =========================
def now_utc():
    return datetime.now(timezone.utc)

def fmt_pct(x: float) -> str:
    return f"{x*100:.1f}%"

def rr_targets(entry: float, sl: float, side: str, tp2_rr: float = AI_TP2_RR):
    risk_per_unit = abs(entry - sl)
    rr1 = 1.0
    rr2 = tp2_rr
    if side.upper() == "LONG":
        tp1 = entry + rr1 * risk_per_unit
        tp2 = entry + rr2 * risk_per_unit
    else:
        tp1 = entry - rr1 * risk_per_unit
        tp2 = entry - rr2 * risk_per_unit
    return tp1, tp2, rr1, rr2, risk_per_unit

def suggested_position_text(balance: float | None, entry: float, sl: float, risk_pct: float, is_forex=False):
    if balance is None:
        return None
    risk_dollars = balance * risk_pct
    stop_dist = abs(entry - sl)
    if stop_dist <= 0:
        return None
    if is_forex:
        units = risk_dollars / stop_dist
        return f"**Risk $:** ${risk_dollars:,.2f}  |  **Units (est.):** {units:,.0f}"
    return f"**Risk $:** ${risk_dollars:,.2f}"

# =========================
# RENDERERS
# =========================
def render_signal_pro(asset_class: str, sig: dict, risk_pct: float, balance: float | None, is_forex=False) -> str:
    tp1, tp2, rr1, rr2, _ = rr_targets(sig["entry"], sig["sl"], sig["side"])
    conf = f"{sig['confidence']*100:.0f}%"
    when = now_utc().strftime("%Y-%m-%d %H:%M UTC")
    style_emoji = "🟢" if sig["style"] == "Confirmed" else "🟡"
    side_emoji = "🟩 LONG" if sig["side"] == "LONG" else "🟥 SHORT"

    header = f"**{style_emoji} {asset_class} Setup – {sig['symbol']} ({sig['timeframe']})**"
    lines = [
        header,
        f"**Side:** {side_emoji}  |  **Confidence:** {conf}  |  **RR:** 1.0R / {AI_TP2_RR:.1f}R",
        f"**Entry:** `{sig['entry']:.4f}`  |  **SL:** `{sig['sl']:.4f}`  |  **TP1/TP2:** `{tp1:.4f}` / `{tp2:.4f}`",
        f"**Risk:** {fmt_pct(risk_pct)}  |  **Mgmt:** TP1 hit → partial & **SL → Entry**, then target TP2.",
    ]
    pos_line = suggested_position_text(balance, sig["entry"], sig["sl"], risk_pct, is_forex=is_forex)
    if pos_line:
        lines.append(pos_line)
    if sig.get("rationale"):
        lines.append(f"**Why:** {sig['rationale']}")
    lines.append(f"**Time:** {when}")
    return "\n".join(lines)

def render_stock_options(sig: dict, risk_pct: float, balance_stocks: float | None) -> str:
    """
    Swing options output (your B profile): TP1 +25%, TP2 +55%, SL -22%.
    Contract sizing: floor( risk$ / (option_price * 100) ).
    """
    when = now_utc().strftime("%Y-%m-%d %H:%M UTC")
    style_emoji = "🟢" if sig["style"] == "Confirmed" else "🟡"
    side_word = "CALL" if sig["side"] == "LONG" else "PUT"
    conf = f"{sig['confidence']*100:.0f}%"
    # naive option price estimate for demo
    opt_price = max(0.25, min(2.50, sig.get("opt_price", random.uniform(0.45, 1.40))))
    risk_line = ""
    contracts_line = ""
    if balance_stocks is not None:
        risk_dollars = balance_stocks * risk_pct
        contracts = max(0, floor(risk_dollars / (opt_price * 100.0)))
        risk_line = f"**Risk $:** ${risk_dollars:,.2f}"
        contracts_line = f"**Contracts:** {contracts} @ ~${opt_price:.2f}"

    lines = [
        f"**🟦 STOCK OPTIONS (SWING) – {sig['symbol']} {side_word} ({sig['timeframe']})**",
        f"**Confidence:** {conf}  |  **Style:** {style_emoji.replace('🟢','Confirmed').replace('🟡','Early')}",
        f"**Entry Zone (shares ref):** `{sig['entry']:.2f}` ± noise  |  **Expiration:** {random.randint(EXP_W_MIN, EXP_W_MAX)} weeks out",
        f"**TP1 / TP2 / SL:** +{int(OPT_TP1*100)}%  /  +{int(OPT_TP2*100)}%  /  -{int(OPT_SL*100)}%",
        f"**Risk per trade:** {fmt_pct(risk_pct)}",
    ]
    if risk_line: lines.append(risk_line)
    if contracts_line: lines.append(contracts_line)
    if sig.get("rationale"):
        lines.append(f"**Why:** {sig['rationale']}")
    lines.append(f"**Time:** {when}")
    return "\n".join(lines)

# =========================
# AI CANDIDATES (demo)
# =========================
def ai_generate_candidates(tickers, asset_class: str):
    out = []
    for symbol in random.sample(tickers, k=min(len(tickers), random.randint(0, 3))):
        side = random.choice(["LONG", "SHORT"])
        base = random.uniform(50, 5000) if asset_class != "FOREX" else random.uniform(0.5, 150)
        entry = round(base, 2 if asset_class == "STOCK" else 4)
        sl = round(entry * (0.985 if side == "LONG" else 1.015), 2 if asset_class == "STOCK" else 4)
        confidence = random.uniform(0.50, 0.95)
        style = random.choice(["Early", "Confirmed"])
        tf = random.choice(["15m", "30m", "1h", "4h"])
        rationale = random.choice([
            "Trend continuation after pullback",
            "Breakout + retest confluence",
            "Volume expansion into key level",
            "Momentum bounce off demand",
            "Mean reversion into VWAP + structure"
        ])
        # lightweight “market context” flags
        high_iv = random.choice([True, False, False])  # skew slightly to False
        out.append({
            "symbol": symbol,
            "timeframe": tf,
            "side": side,
            "entry": entry,
            "sl": sl,
            "confidence": confidence,
            "style": style,
            "rationale": rationale,
            "high_iv": high_iv,
            "opt_price": random.uniform(0.45, 1.40)  # for options sizing
        })
    return out

def choose_top_signals(candidates, top_k=2, min_conf=0.6):
    filtered = [c for c in candidates if c["confidence"] >= min_conf]
    filtered.sort(key=lambda s: s["confidence"], reverse=True)
    return filtered[:top_k]

# =========================
# DAILY CAPS
# =========================
_daily_counts = {"CRYPTO": 0, "STOCK": 0, "FOREX": 0}
_daily_stamp = now_utc().date()

def _roll_daily():
    global _daily_stamp, _daily_counts
    d = now_utc().date()
    if d != _daily_stamp:
        _daily_stamp = d
        _daily_counts = {"CRYPTO": 0, "STOCK": 0, "FOREX": 0}

# =========================
# POST HELPERS
# =========================
async def post_signals(channel: discord.TextChannel, asset_class: str, signals: list, risk_pct: float, daily_cap: int):
    if not channel or not signals:
        return
    _roll_daily()
    remaining = max(0, daily_cap - _daily_counts[asset_class])
    if remaining <= 0:
        return
    to_send = signals[:remaining]
    for sig in to_send:
        if asset_class == "CRYPTO":
            text = render_signal_pro("CRYPTO", sig, risk_pct, ACCOUNT_BALANCE_CRYPTO, is_forex=False)
        elif asset_class == "FOREX":
            text = render_signal_pro("FOREX", sig, risk_pct, ACCOUNT_BALANCE_FOREX, is_forex=True)
        else:
            # STOCKS: Hybrid vehicle selection
            vehicle = STOCK_VEHICLE_MODE
            if vehicle == "HYBRID":
                # choose OPTIONS when high IV or very strong confidence; else SHARES
                vehicle = "OPTIONS" if (sig.get("high_iv") or sig["confidence"] >= 0.75) else "SHARES"
            if vehicle == "OPTIONS":
                text = render_stock_options(sig, RISK_PCT_STOCKS, ACCOUNT_BALANCE_STOCKS)
            else:
                text = render_signal_pro("STOCK", sig, RISK_PCT_STOCKS, ACCOUNT_BALANCE_STOCKS, is_forex=False)
                text = "🟪 **Shares Version**\n" + text  # tag it clearly
        await channel.send(text)
        _daily_counts[asset_class] += 1
        await asyncio.sleep(1.2)

# =========================
# SCAN LOOPS
# =========================
@tasks.loop(minutes=1)
async def crypto_scan_loop():
    if CRYPTO_SCAN_MIN <= 0: return
    if now_utc().minute % CRYPTO_SCAN_MIN != 0: return
    ch = bot.get_channel(CRYPTO_CHANNEL_ID)
    picks = choose_top_signals(ai_generate_candidates(CRYPTO_TICKERS, "CRYPTO"), top_k=2, min_conf=MIN_CONF_CRYPTO)
    await post_signals(ch, "CRYPTO", picks, RISK_PCT_CRYPTO, CRYPTO_DAILY_CAP)

@tasks.loop(minutes=1)
async def stock_scan_loop():
    if STOCK_SCAN_MIN <= 0: return
    if now_utc().minute % STOCK_SCAN_MIN != 0: return
    ch = bot.get_channel(STOCK_CHANNEL_ID)
    picks = choose_top_signals(ai_generate_candidates(STOCK_TICKERS, "STOCK"), top_k=2, min_conf=MIN_CONF_STOCKS)
    await post_signals(ch, "STOCK", picks, RISK_PCT_STOCKS, STOCK_DAILY_CAP)

@tasks.loop(minutes=1)
async def forex_scan_loop():
    if FOREX_SCAN_MIN <= 0: return
    if now_utc().minute % FOREX_SCAN_MIN != 0: return
    ch = bot.get_channel(FOREX_CHANNEL_ID)
    picks = choose_top_signals(ai_generate_candidates(FOREX_TICKERS, "FOREX"), top_k=2, min_conf=MIN_CONF_FOREX)
    await post_signals(ch, "FOREX", picks, RISK_PCT_FOREX, FOREX_DAILY_CAP)

# =========================
# COMMANDS
# =========================
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (id: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="JCF HQ scanning"))
    if ANNOUNCE_CHANNEL_ID:
        ch = bot.get_channel(ANNOUNCE_CHANNEL_ID)
        if ch:
            await ch.send("✅ **JCFWatchBot ONLINE** — AI scanners ready (Crypto/Stocks/Forex).")
    if AI_SCAN_LOOP:
        if not crypto_scan_loop.is_running(): crypto_scan_loop.start()
        if not stock_scan_loop.is_running():  stock_scan_loop.start()
        if not forex_scan_loop.is_running():  forex_scan_loop.start()
        print("✅ Scan loops started.")

@bot.command()
async def ping(ctx): await ctx.reply("Pong 🏓")

@bot.command()
async def status(ctx):
    _roll_daily()
    msg = (
        "**JCF HQ Status**\n"
        f"• AI_SCAN_LOOP: {AI_SCAN_LOOP}\n"
        f"• Crypto: scan {CRYPTO_SCAN_MIN}m | min conf {MIN_CONF_CRYPTO:.2f} | daily { _daily_counts['CRYPTO'] } / {CRYPTO_DAILY_CAP}\n"
        f"• Stocks: scan {STOCK_SCAN_MIN}m | min conf {MIN_CONF_STOCKS:.2f} | daily { _daily_counts['STOCK'] } / {STOCK_DAILY_CAP}\n"
        f"  └ Vehicle: {STOCK_VEHICLE_MODE} | Option swing TP1/TP2/SL: +{int(OPT_TP1*100)}% / +{int(OPT_TP2*100)}% / -{int(OPT_SL*100)}%\n"
        f"• Forex:  scan {FOREX_SCAN_MIN}m | min conf {MIN_CONF_FOREX:.2f} | daily { _daily_counts['FOREX'] } / {FOREX_DAILY_CAP}\n"
        + (f"• Balances — CRYPTO ${ACCOUNT_BALANCE_CRYPTO:,.0f} | STOCKS ${ACCOUNT_BALANCE_STOCKS:,.0f} | FOREX ${ACCOUNT_BALANCE_FOREX:,.0f}\n"
           if all([ACCOUNT_BALANCE_CRYPTO, ACCOUNT_BALANCE_STOCKS, ACCOUNT_BALANCE_FOREX]) else "")
    )
    await ctx.reply(msg)

async def _do_testsig(ctx, asset_class: str):
    if not ALLOW_DEMO:
        await ctx.reply("Demo/test signals are disabled.")
        return
    mapping = {
        "CRYPTO": (CRYPTO_TICKERS, CRYPTO_CHANNEL_ID, RISK_PCT_CRYPTO, MIN_CONF_CRYPTO),
        "STOCK":  (STOCK_TICKERS,  STOCK_CHANNEL_ID,  RISK_PCT_STOCKS, MIN_CONF_STOCKS),
        "FOREX":  (FOREX_TICKERS,  FOREX_CHANNEL_ID,  RISK_PCT_FOREX,  MIN_CONF_FOREX),
    }
    tickers, chan_id, risk_pct, min_conf = mapping[asset_class]
    ch = bot.get_channel(chan_id)
    picks = choose_top_signals(ai_generate_candidates(tickers, asset_class), top_k=2, min_conf=min_conf)
    if not picks:
        await ctx.reply(f"No {asset_class.lower()} test signals passed the confidence filter.")
        return
    await post_signals(ch, asset_class, picks, risk_pct, daily_cap=9999)
    await ctx.reply(f"Sent {len(picks)} test {asset_class.lower()} signal(s).")

@bot.command(name="testsig_crypto")
async def testsig_crypto(ctx): await _do_testsig(ctx, "CRYPTO")

@bot.command(name="testsig_stock")
async def testsig_stock(ctx):  await _do_testsig(ctx, "STOCK")

@bot.command(name="testsig_forex")
async def testsig_forex(ctx):  await _do_testsig(ctx, "FOREX")

@bot.command()
async def scanonce(ctx):
    for asset_class in ["CRYPTO", "STOCK", "FOREX"]:
        mapping = {
            "CRYPTO": (CRYPTO_TICKERS, CRYPTO_CHANNEL_ID, RISK_PCT_CRYPTO, CRYPTO_DAILY_CAP, MIN_CONF_CRYPTO),
            "STOCK":  (STOCK_TICKERS,  STOCK_CHANNEL_ID,  RISK_PCT_STOCKS,  STOCK_DAILY_CAP,  MIN_CONF_STOCKS),
            "FOREX":  (FOREX_TICKERS,  FOREX_CHANNEL_ID,  RISK_PCT_FOREX,  FOREX_DAILY_CAP,  MIN_CONF_FOREX),
        }
        tickers, chan_id, risk_pct, cap, min_conf = mapping[asset_class]
        ch = bot.get_channel(chan_id)
        picks = choose_top_signals(ai_generate_candidates(tickers, asset_class), top_k=2, min_conf=min_conf)
        if picks:
            await post_signals(ch, asset_class, picks, risk_pct, cap)
    await ctx.reply("Manual scan completed.")

# =========================
# RUN
# =========================
if not TOKEN:
    raise SystemExit("DISCORD_TOKEN is missing.")
bot.run(TOKEN)