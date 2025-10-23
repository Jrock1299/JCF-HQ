import os
import math
import asyncio
import discord
from discord.ext import commands

# -------------------------------------------------------------------
# Environment / Config
# -------------------------------------------------------------------
# Avoid audio dependency on Python ≥3.13 (Railway)
os.environ["DISCORD_NO_AUDIO"] = "1"

TOKEN = os.getenv("DISCORD_TOKEN")

# Optional announce channel (startup message)
ANNOUNCE_CHANNEL_ID = int(os.getenv("ANNOUNCE_CHANNEL_ID", "0") or 0)

# Channel routing (set these in Railway → Variables)
CRYPTO_CH = int(os.getenv("CRYPTO_SETUPS_CHANNEL_ID", "0") or 0)
STOCK_CH  = int(os.getenv("STOCK_SETUPS_CHANNEL_ID", "0") or 0)
FOREX_CH  = int(os.getenv("FOREX_SETUPS_CHANNEL_ID", "0") or 0)

# AI / Signal knobs (read from Railway variables)
TP_MODE   = int(os.getenv("AI_TP_MODE", "2"))            # 1 or 2 targets
TP1_RR    = float(os.getenv("AI_TP1_RR", "1.0"))         # ≈1R
TP2_RR    = float(os.getenv("AI_TP2_RR", "2.0"))         # ≈2R
TF_TAGS   = os.getenv("AI_TIMEFRAME_TAGS", "1") == "1"   # show TF tags in title
CONF_FMT  = os.getenv("AI_CONF_FORMAT", "decimal")       # 'decimal' | 'rounded'
RISK_PCT  = float(os.getenv("AI_DEFAULT_RISK_PCT", "2.0"))
AI_SIGNAL_TIMING = os.getenv("AI_SIGNAL_TIMING", "hybrid").lower()  # 'early'|'confirmed'|'hybrid'

# -------------------------------------------------------------------
# Discord Bot Setup
# -------------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (id: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="JCF HQ online"))
    if ANNOUNCE_CHANNEL_ID:
        ch = bot.get_channel(ANNOUNCE_CHANNEL_ID)
        if ch:
            await ch.send("✅ **JCFWatchBot ONLINE** — Systems initialized. Monitoring markets…")
    print("✅ Startup message sent (if channel set).")

# Optional: simple error echo so we can see command issues in chat
@bot.event
async def on_command_error(ctx, error):
    # keep it brief; useful during setup
    await ctx.send(f"⚠️ `{type(error).__name__}: {error}`")

# -------------------------------------------------------------------
# Helpers: TP math, formatting, labels
# -------------------------------------------------------------------
def compute_tps(entry: float, sl: float, side: str, rr1: float, rr2: float):
    """Derive TP1/TP2 from RR multiples."""
    side = side.lower()
    if side not in ("long", "short"):
        return None, None
    risk_per_unit = (entry - sl) if side == "long" else (sl - entry)
    if risk_per_unit == 0:
        return None, None
    if side == "long":
        tp1 = entry + rr1 * abs(risk_per_unit)
        tp2 = entry + rr2 * abs(risk_per_unit) if TP_MODE == 2 else None
    else:
        tp1 = entry - rr1 * abs(risk_per_unit)
        tp2 = entry - rr2 * abs(risk_per_unit) if TP_MODE == 2 else None
    return tp1, tp2

def _fmt_conf(conf: float) -> str:
    """confidence display (0..1 → 0..5 one decimal)"""
    score_5 = max(0.0, min(5.0, round(conf * 5.0, 1)))
    return f"{score_5}/5"

def signal_phase_label(phase: str | None) -> str:
    if phase == "early":
        return "⏳ Early Scout"
    if phase == "confirmed":
        return "✅ Confirmed"
    return "Setup"

def clamp_phase(phase: str | None) -> str:
    """
    Respects AI_SIGNAL_TIMING policy:
    - 'early' => always early
    - 'confirmed' => always confirmed
    - 'hybrid' => use provided phase; default to confirmed
    """
    p = (phase or "").lower()
    m = AI_SIGNAL_TIMING
    if m == "early":
        return "early"
    if m == "confirmed":
        return "confirmed"
    # hybrid
    return p if p in ("early", "confirmed") else "confirmed"

def format_signal_b(
    symbol: str,
    side: str,            # "LONG" | "SHORT"
    entry: float,
    sl: float,
    confidence: float,    # 0..1
    timeframe: str,       # e.g., "15M","1H","4H"
    reasons: list,        # 2–4 short bullet strings
    rr1: float = None,
    rr2: float = None,
):
    """Beginner-friendly signal card (Option B)."""
    side = side.upper()
    rr1 = rr1 if rr1 is not None else TP1_RR
    rr2 = rr2 if rr2 is not None else TP2_RR

    tp1, tp2 = compute_tps(entry, sl, side, rr1, rr2)

    tf_tag = f" — {timeframe}" if (TF_TAGS and timeframe) else ""
    phase = clamp_phase(globals().get("_CURRENT_PHASE", None))
    phase_tag = signal_phase_label(phase)

    lines = []
    lines.append(f"📈 **{symbol} – {side} {phase_tag}{tf_tag}**")
    lines.append(f"• **Buy around:** {entry:,.2f}" if side == "LONG" else f"• **Sell around:** {entry:,.2f}")
    lines.append(f"• **Stop Loss (exit if wrong):** {sl:,.2f}")
    if tp1:
        lines.append(f"• **Take Profit 1 (≈{TP1_RR:.1f}R):** {tp1:,.2f}")
    if TP_MODE == 2 and tp2:
        lines.append(f"• **Take Profit 2 (≈{TP2_RR:.1f}R):** {tp2:,.2f}")
    lines.append("")
    lines.append("**Why this trade?**")
    for r in (reasons or [])[:4]:
        lines.append(f"• {r}")
    lines.append("")
    lines.append(f"**Confidence:** {_fmt_conf(confidence)}")
    lines.append(f"**Suggested Risk:** {RISK_PCT:.1f}% of account")
    return "\n".join(lines)

async def send_signal_card(b, channel_id: int, content: str):
    ch = b.get_channel(channel_id)
    if ch:
        await ch.send(content)

# -------------------------------------------------------------------
# Commands
# -------------------------------------------------------------------
@bot.command(name="ping")
async def ping_cmd(ctx):
    await ctx.reply("Pong 🏓")

@bot.command(name="status", aliases=["cfg", "ai_status"])
async def status_cmd(ctx):
    try:
        await ctx.send(
            "🧠 **AI Config**\n"
            f"- Timeframe tags: {'ON' if TF_TAGS else 'OFF'}\n"
            f"- TP Mode: {TP_MODE} target(s)\n"
            f"- TP1 RR: {TP1_RR:.1f}\n"
            f"- TP2 RR: {TP2_RR:.1f}\n"
            f"- Confidence format: {CONF_FMT}\n"
            f"- Default risk text: {RISK_PCT:.1f}%\n"
            f"- Signal timing: {AI_SIGNAL_TIMING}\n"
            f"- Channels set ➜ Crypto={bool(CRYPTO_CH)}  Stocks={bool(STOCK_CH)}  Forex={bool(FOREX_CH)}"
        )
    except Exception as e:
        await ctx.send(f"⚠️ status error: `{type(e).__name__}: {e}`")

@bot.command(name="testsig_b")
async def testsig_b(ctx, market: str = "crypto", phase: str = "confirmed"):
    """
    Preview an Option-B card (beginner-friendly).
    Usage:
      !testsig_b
      !testsig_b stocks
      !testsig_b forex early
    """
    symbol = "BTC/USDT" if market == "crypto" else ("AAPL" if market == "stocks" else "XAUUSD")
    side = "LONG"
    entry = 67150.0
    sl    = 66720.0
    conf  = 0.86          # 0..1 → shows as ~4.3/5
    tf    = "1H"
    reasons = [
        "Trend looks bullish",
        "Momentum improving on 1H & 4H",
        "Liquidity sweep and reclaim",
    ]

    globals()["_CURRENT_PHASE"] = phase  # 'early' or 'confirmed'
    card = format_signal_b(symbol, side, entry, sl, conf, tf, reasons)
    globals().pop("_CURRENT_PHASE", None)

    target_channel = CRYPTO_CH if market == "crypto" else (STOCK_CH if market == "stocks" else FOREX_CH)
    if not target_channel:
        await ctx.send("⚠️ Target channel ID not set in Railway vars for this market.")
        return

    await send_signal_card(bot, target_channel, card)
    await ctx.send("✅ Test signal (Option B) posted.")

# -------------------------------------------------------------------
# Boot
# -------------------------------------------------------------------
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN not set in environment variables.")
bot.run(TOKEN)