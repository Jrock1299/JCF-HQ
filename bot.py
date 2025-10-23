import os
import asyncio
import math
import random
from datetime import datetime, timezone

# Make sure discord never tries to load voice/audio (fixes audioop issue)
os.environ.setdefault("DISCORD_NO_AUDIO", "1")

import discord
from discord.ext import commands, tasks

# -------------------------
# ENV / CONFIG
# -------------------------
TOKEN = os.getenv("DISCORD_TOKEN")

ANNOUNCE_CHANNEL_ID = int(os.getenv("ANNOUNCE_CHANNEL_ID", "0") or 0)

CRYPTO_CHANNEL_ID = int(os.getenv("CRYPTO_SETUPS_CHANNEL_ID", "0") or 0)
STOCK_CHANNEL_ID  = int(os.getenv("STOCK_SETUPS_CHANNEL_ID", "0") or 0)
FOREX_CHANNEL_ID  = int(os.getenv("FOREX_SETUPS_CHANNEL_ID", "0") or 0)

CRYPTO_TICKERS = [s.strip().upper() for s in os.getenv("CRYPTO_TICKERS", "BTC,ETH,SOL,MSTR").split(",") if s.strip()]
STOCK_TICKERS  = [s.strip().upper() for s in os.getenv("STOCK_TICKERS",  "NVDA,AAPL,TSLA,PLTR,SOFI,OKLO,MSTR").split(",") if s.strip()]
FOREX_TICKERS  = [s.strip().upper() for s in os.getenv("FOREX_TICKERS",  "XAUUSD,SPX,US30,USDJPY,EURUSD,GBPUSD").split(",") if s.strip()]

# Risk knobs (percent of account per trade; used for position sizing text)
RISK_PCT_CRYPTO = float(os.getenv("RISK_PCT_CRYPTO", "0.02"))
RISK_PCT_STOCKS = float(os.getenv("RISK_PCT_STOCKS", "0.01"))
RISK_PCT_FOREX  = float(os.getenv("RISK_PCT_FOREX", "0.015"))

# Scan cadence (minutes)
CRYPTO_SCAN_MIN = int(os.getenv("CRYPTO_SCAN_MIN", "15"))
STOCK_SCAN_MIN  = int(os.getenv("STOCK_SCAN_MIN", "15"))
FOREX_SCAN_MIN  = int(os.getenv("FOREX_SCAN_MIN", "15"))

# Daily caps (max alerts per asset class per UTC day)
CRYPTO_DAILY_CAP = int(os.getenv("CRYPTO_DAILY_CAP", "12"))
STOCK_DAILY_CAP  = int(os.getenv("STOCK_DAILY_CAP",  "12"))
FOREX_DAILY_CAP  = int(os.getenv("FOREX_DAILY_CAP",  "12"))

# AI / TP config
AI_SCAN_LOOP   = int(os.getenv("AI_SCAN_LOOP", "1"))     # 1 = on, 0 = off
AI_TP_MODE     = os.getenv("AI_TP_MODE", "2TP_SL2BE")    # we're using TP1 then SL->BE then TP2
AI_TP2_RR      = float(os.getenv("AI_TP2_RR", "2.0"))    # TP2 at 2R by default
ALLOW_DEMO     = os.getenv("ALLOW_DEMO", "1") == "1"     # allow testsig commands

# -------------------------
# DISCORD BOOT
# -------------------------
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

def now_utc():
    return datetime.now(timezone.utc)

def fmt_pct(x: float) -> str:
    return f"{x*100:.1f}%"

def pick_rr_levels(entry: float, sl: float, side: str, tp2_rr: float = AI_TP2_RR):
    """Return (tp1, tp2, rr1, rr2). TP1 fixed at 1R, TP2 at `tp2_rr` R."""
    risk_per_unit = abs(entry - sl)
    rr1 = 1.0
    rr2 = tp2_rr
    if side.upper() == "LONG":
        tp1 = entry + rr1 * risk_per_unit
        tp2 = entry + rr2 * risk_per_unit
    else:
        tp1 = entry - rr1 * risk_per_unit
        tp2 = entry - rr2 * risk_per_unit
    return tp1, tp2, rr1, rr2

def render_signal_text(asset_class: str, sig: dict, risk_pct: float) -> str:
    """
    Text-only alert with TP1 partial/SL->BE then TP2 final.
    Fields expected in sig:
      symbol, timeframe, side, entry, sl, confidence (0-1), style ('Early'/'Confirmed'), rationale
    """
    tp1, tp2, rr1, rr2 = pick_rr_levels(sig["entry"], sig["sl"], sig["side"])
    conf = f"{sig['confidence']*100:.0f}%"
    rr_txt = f"{rr1:.1f}R / {rr2:.1f}R"
    when = now_utc().strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"**{asset_class} Setup – {sig['symbol']} ({sig['timeframe']})**",
        f"**Type:** {sig['style']}  |  **Side:** {sig['side']}  |  **Confidence:** {conf}",
        f"**Entry:** {sig['entry']:.4f}  |  **SL:** {sig['sl']:.4f}  |  **TP1/TP2:** {tp1:.4f} / {tp2:.4f}  ({rr_txt})",
        f"**Risk:** {fmt_pct(risk_pct)}  |  **Mgmt:** On TP1 hit → partial close & move SL to entry, aim TP2.",
    ]
    if sig.get("rationale"):
        lines.append(f"**Why:** {sig['rationale']}")
    lines.append(f"**Time:** {when}")
    return "\n".join(lines)

# -------------------------
# MOCK AI SCORING
# (Placeholder: returns 0–N candidate signals with confidence. We keep the top 2.)
# Replace this function later with your actual scoring sources.
# -------------------------
def ai_generate_candidates(tickers, asset_class: str):
    """
    Creates plausible-looking demo signals with random confidence.
    We keep it conservative so it doesn't spam.
    """
    out = []
    for symbol in random.sample(tickers, k=min(len(tickers), random.randint(0, 3))):
        side = random.choice(["LONG", "SHORT"])
        base = random.uniform(50, 5000) if asset_class != "FOREX" else random.uniform(0.5, 150)
        entry = round(base, 4)
        # SL distance proportional to price to keep RR sane
        sl = round(entry * (0.98 if side == "LONG" else 1.02), 4)
        confidence = random.uniform(0.60, 0.95)  # 60%–95% demo
        style = random.choice(["Early", "Confirmed"])
        tf = random.choice(["15m", "30m", "1h", "4h"])
        rationale = random.choice([
            "Trend continuation after pullback",
            "Breakout + retest confluence",
            "Volume expansion into key level",
            "Divergence resolved with momentum"
        ])
        out.append({
            "symbol": symbol,
            "timeframe": tf,
            "side": side,
            "entry": entry,
            "sl": sl,
            "confidence": confidence,
            "style": style,
            "rationale": rationale
        })
    return out

def choose_top_signals(candidates, top_k=2):
    return sorted(candidates, key=lambda s: s["confidence"], reverse=True)[:top_k]

# Daily counters to respect caps
_daily_counts = {"CRYPTO": 0, "STOCK": 0, "FOREX": 0}
_daily_stamp = now_utc().date()

def _roll_daily():
    global _daily_stamp, _daily_counts
    d = now_utc().date()
    if d != _daily_stamp:
        _daily_stamp = d
        _daily_counts = {"CRYPTO": 0, "STOCK": 0, "FOREX": 0}

async def post_signals(channel: discord.TextChannel, asset_class: str, signals: list, risk_pct: float, daily_cap: int):
    if not channel:
        return
    _roll_daily()
    remaining = max(0, daily_cap - _daily_counts[asset_class])
    if remaining <= 0 or not signals:
        return
    to_send = signals[:remaining]
    for sig in to_send:
        text = render_signal_text(asset_class, sig, risk_pct)
        await channel.send(text)
        _daily_counts[asset_class] += 1
        await asyncio.sleep(1.2)  # tiny spacing

# -------------------------
# SCAN LOOPS (per asset class)
# -------------------------
@tasks.loop(minutes=1)
async def crypto_scan_loop():
    if CRYPTO_SCAN_MIN <= 0:
        return
    if now_utc().minute % CRYPTO_SCAN_MIN != 0:
        return
    ch = bot.get_channel(CRYPTO_CHANNEL_ID)
    cands = ai_generate_candidates(CRYPTO_TICKERS, "CRYPTO")
    picks = choose_top_signals(cands, top_k=2)
    await post_signals(ch, "CRYPTO", picks, RISK_PCT_CRYPTO, CRYPTO_DAILY_CAP)

@tasks.loop(minutes=1)
async def stock_scan_loop():
    if STOCK_SCAN_MIN <= 0:
        return
    if now_utc().minute % STOCK_SCAN_MIN != 0:
        return
    ch = bot.get_channel(STOCK_CHANNEL_ID)
    cands = ai_generate_candidates(STOCK_TICKERS, "STOCK")
    picks = choose_top_signals(cands, top_k=2)
    await post_signals(ch, "STOCK", picks, RISK_PCT_STOCKS, STOCK_DAILY_CAP)

@tasks.loop(minutes=1)
async def forex_scan_loop():
    if FOREX_SCAN_MIN <= 0:
        return
    if now_utc().minute % FOREX_SCAN_MIN != 0:
        return
    ch = bot.get_channel(FOREX_CHANNEL_ID)
    cands = ai_generate_candidates(FOREX_TICKERS, "FOREX")
    picks = choose_top_signals(cands, top_k=2)
    await post_signals(ch, "FOREX", picks, RISK_PCT_FOREX, FOREX_DAILY_CAP)

# -------------------------
# COMMANDS
# -------------------------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (id: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="JCF HQ scanning"))
    if ANNOUNCE_CHANNEL_ID:
        ch = bot.get_channel(ANNOUNCE_CHANNEL_ID)
        if ch:
            await ch.send("✅ **JCFWatchBot ONLINE** — Systems initialized. Monitoring markets…")
    # Start loops if configured
    if AI_SCAN_LOOP:
        if not crypto_scan_loop.is_running():
            crypto_scan_loop.start()
        if not stock_scan_loop.is_running():
            stock_scan_loop.start()
        if not forex_scan_loop.is_running():
            forex_scan_loop.start()
        print("✅ Scan loops started.")

@bot.command()
async def ping(ctx):
    await ctx.reply("Pong 🏓")

@bot.command()
async def status(ctx):
    _roll_daily()
    msg = (
        "**JCF HQ Status**\n"
        f"• AI_SCAN_LOOP: {AI_SCAN_LOOP}\n"
        f"• Crypto: scan {CRYPTO_SCAN_MIN}m | daily { _daily_counts['CRYPTO'] } / {CRYPTO_DAILY_CAP} | tickers: {', '.join(CRYPTO_TICKERS)}\n"
        f"• Stocks: scan {STOCK_SCAN_MIN}m | daily { _daily_counts['STOCK'] } / {STOCK_DAILY_CAP} | tickers: {', '.join(STOCK_TICKERS)}\n"
        f"• Forex:  scan {FOREX_SCAN_MIN}m | daily { _daily_counts['FOREX'] } / {FOREX_DAILY_CAP} | pairs: {', '.join(FOREX_TICKERS)}\n"
        f"• TP mode: {AI_TP_MODE} | TP2 RR: {AI_TP2_RR}\n"
        f"• Risks: CRYPTO {fmt_pct(RISK_PCT_CRYPTO)}, STOCKS {fmt_pct(RISK_PCT_STOCKS)}, FOREX {fmt_pct(RISK_PCT_FOREX)}"
    )
    await ctx.reply(msg)

async def _do_testsig(ctx, asset_class: str):
    if not ALLOW_DEMO:
        await ctx.reply("Demo/test signals are currently disabled.")
        return
    mapping = {
        "CRYPTO": (CRYPTO_TICKERS, CRYPTO_CHANNEL_ID, RISK_PCT_CRYPTO),
        "STOCK":  (STOCK_TICKERS,  STOCK_CHANNEL_ID,  RISK_PCT_STOCKS),
        "FOREX":  (FOREX_TICKERS,  FOREX_CHANNEL_ID,  RISK_PCT_FOREX),
    }
    tickers, chan_id, risk_pct = mapping[asset_class]
    ch = bot.get_channel(chan_id)
    cands = ai_generate_candidates(tickers, asset_class)
    if not cands:
        await ctx.reply(f"No strong {asset_class.lower()} candidates right now.")
        return
    picks = choose_top_signals(cands, top_k=2)
    await post_signals(ch, asset_class, picks, risk_pct, daily_cap=9999)
    await ctx.reply(f"Sent {len(picks)} test {asset_class.lower()} signal(s) to the channel.")

@bot.command(name="testsig_crypto")
async def testsig_crypto(ctx):
    await _do_testsig(ctx, "CRYPTO")

@bot.command(name="testsig_stock")
async def testsig_stock(ctx):
    await _do_testsig(ctx, "STOCK")

@bot.command(name="testsig_forex")
async def testsig_forex(ctx):
    await _do_testsig(ctx, "FOREX")

@bot.command()
async def scanonce(ctx):
    """One-off manual scan that posts top candidates to each channel (respects top-2 filter)."""
    for asset_class in ["CRYPTO", "STOCK", "FOREX"]:
        mapping = {
            "CRYPTO": (CRYPTO_TICKERS, CRYPTO_CHANNEL_ID, RISK_PCT_CRYPTO, CRYPTO_DAILY_CAP),
            "STOCK":  (STOCK_TICKERS,  STOCK_CHANNEL_ID,  RISK_PCT_STOCKS,  STOCK_DAILY_CAP),
            "FOREX":  (FOREX_TICKERS,  FOREX_CHANNEL_ID,  RISK_PCT_FOREX,  FOREX_DAILY_CAP),
        }
        tickers, chan_id, risk_pct, cap = mapping[asset_class]
        ch = bot.get_channel(chan_id)
        cands = ai_generate_candidates(tickers, asset_class)
        picks = choose_top_signals(cands, top_k=2)
        if picks:
            await post_signals(ch, asset_class, picks, risk_pct, cap)
    await ctx.reply("Manual scan completed.")

# Run
if not TOKEN:
    raise SystemExit("DISCORD_TOKEN is missing.")
bot.run(TOKEN)