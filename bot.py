import os
os.environ["DISCORD_NO_AUDIO"] = "1"

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import discord
from discord.ext import commands

import requests
import yfinance as yf
import pandas as pd
import numpy as np

# ---------------- Discord Setup ----------------
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None  # avoid help command collision
)

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise SystemExit("Missing DISCORD_TOKEN env var.")

# Channels
def _to_int(x: Optional[str]) -> Optional[int]:
    return int(x) if x and x.isdigit() else None

ANNOUNCE_CHANNEL_ID = _to_int(os.getenv("ANNOUNCE_CHANNEL_ID"))
CHAN_CRYPTO_ID = _to_int(os.getenv("CHANNEL_CRYPTO_SETUPS_ID"))
CHAN_STOCKS_ID = _to_int(os.getenv("CHANNEL_STOCK_SETUPS_ID"))
CHAN_FOREX_ID  = _to_int(os.getenv("CHANNEL_FOREX_SETUPS_ID"))

# Autoscan & sessions
AI_SCAN_LOOP = os.getenv("AI_SCAN_LOOP", "0") == "1"
SCAN_INTERVAL_MIN = float(os.getenv("SCAN_INTERVAL_MIN", "20"))

SESSION_FILTER_STOCKS = os.getenv("SESSION_FILTER_STOCKS", "0") == "1"
SESSION_FILTER_FOREX  = os.getenv("SESSION_FILTER_FOREX", "0") == "1"
STOCKS_SESSION_UTC = os.getenv("STOCKS_SESSION_UTC", "13:30-20:00")
FOREX_SESSION_UTC  = os.getenv("FOREX_SESSION_UTC",  "07:00-16:00,13:00-21:00")

# Watchlists
WATCH_CRYPTO = [s.strip().upper() for s in os.getenv("WATCH_CRYPTO", "").split(",") if s.strip()]
WATCH_STOCKS = [s.strip().upper() for s in os.getenv("WATCH_STOCKS", "").split(",") if s.strip()]
WATCH_FOREX  = [s.strip().upper() for s in os.getenv("WATCH_FOREX", "").split(",") if s.strip()]

# Behavior tweaks
BEGINNER_MODE = os.getenv("BEGINNER_MODE", "0") == "1"
AI_SCORE_THRESHOLD = float(os.getenv("AI_SCORE_THRESHOLD", "0.77"))

# Filters & knobs
AI_SMART_FILTER = os.getenv("AI_SMART_FILTER", "1") == "1"
AI_VOL_FILTER   = os.getenv("AI_VOL_FILTER", "1") == "1"
AI_TREND_FILTER = os.getenv("AI_TREND_FILTER", "1") == "1"

MIN_ATR_PCT   = float(os.getenv("MIN_ATR_PCT", "0.35"))  # %
MAX_ATR_PCT   = float(os.getenv("MAX_ATR_PCT", "4.0"))   # %
MIN_TREND_SLOPE = float(os.getenv("MIN_TREND_SLOPE", "0.0"))

TP_MODE     = os.getenv("TP_MODE", "RR").upper()  # RR or ATR
RR_TP1      = float(os.getenv("RR_TP1", "1.0"))
RR_TP2      = float(os.getenv("RR_TP2", "2.0"))
SL_ATR_MULT = float(os.getenv("SL_ATR_MULT", "1.0"))

# Score Weights
W_TREND  = float(os.getenv("W_TREND",  "0.35"))
W_MOMO   = float(os.getenv("W_MOMO",   "0.25"))
W_VOL    = float(os.getenv("W_VOL",    "0.15"))
W_CONFL  = float(os.getenv("W_CONFL",  "0.15"))
W_LIQ    = float(os.getenv("W_LIQ",    "0.10"))
W_SUM = max(W_TREND + W_MOMO + W_VOL + W_CONFL + W_LIQ, 1e-9)

# ---------------- Symbol helpers ----------------

# Crypto: yfinance history tickers & CoinGecko live
CRYPTO_YF = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "SOL": "SOL-USD",
    "XRP": "XRP-USD",
    "LINK": "LINK-USD",
    "ADA": "ADA-USD",
}
COINGECKO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "XRP": "ripple",
    "LINK": "chainlink",
    "ADA": "cardano",
}

# Forex mapping to yfinance symbols
# e.g. EURUSD -> EURUSD=X, XAUUSD -> XAUUSD=X
def fx_to_yf(symbol: str) -> str:
    s = symbol.upper().replace("/", "")
    if not s.endswith("=X"):
        s = s + "=X"
    return s

# ---------------- Fetch live prices ----------------
def fetch_price_crypto(symbol: str) -> Optional[float]:
    cid = COINGECKO_IDS.get(symbol.upper())
    if not cid:
        return None
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": cid, "vs_currencies": "usd"},
            timeout=6,
        )
        r.raise_for_status()
        return float(r.json()[cid]["usd"])
    except Exception:
        return None

def fetch_price_stock(symbol: str) -> Optional[float]:
    try:
        t = yf.Ticker(symbol)
        p = t.fast_info.last_price or t.fast_info.regular_market_price
        return float(p) if p is not None else None
    except Exception:
        return None

def fetch_price_fx(symbol: str) -> Optional[float]:
    try:
        t = yf.Ticker(fx_to_yf(symbol))
        p = t.fast_info.last_price or t.fast_info.regular_market_price
        return float(p) if p is not None else None
    except Exception:
        return None

# ---------------- History fetch ----------------
def fetch_history(domain: str, symbol: str, period="90d", interval="1h") -> Optional[pd.DataFrame]:
    try:
        if domain == "crypto":
            yf_sym = CRYPTO_YF.get(symbol.upper())
            if not yf_sym:
                return None
            df = yf.Ticker(yf_sym).history(period=period, interval=interval, auto_adjust=False)
        elif domain == "stocks":
            df = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=False)
        else:  # forex
            df = yf.Ticker(fx_to_yf(symbol)).history(period=period, interval=interval, auto_adjust=False)
        if df is None or df.empty:
            return None
        df = df.rename(columns=str.title)
        return df.dropna()
    except Exception:
        return None

# ---------------- Indicators ----------------
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["SMA20"] = df["Close"].rolling(20).mean()
    df["SMA50"] = df["Close"].rolling(50).mean()
    tr1 = (df["High"] - df["Low"]).abs()
    tr2 = (df["High"] - df["Close"].shift(1)).abs()
    tr3 = (df["Low"]  - df["Close"].shift(1)).abs()
    df["TR"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["ATR14"] = df["TR"].rolling(14).mean()
    df["ROL_MAX20"] = df["High"].rolling(20).max()
    df["ROL_MIN20"] = df["Low"].rolling(20).min()
    return df

def pct(x: float) -> float:
    return x * 100.0

# ---------------- Sessions ----------------
def _parse_ranges(spec: str) -> List[Tuple[int,int]]:
    out = []
    for block in spec.split(","):
        block = block.strip()
        if not block: continue
        try:
            a,b = block.split("-")
            h1,m1 = [int(x) for x in a.split(":")]
            h2,m2 = [int(x) for x in b.split(":")]
            out.append((h1*60+m1, h2*60+m2))
        except Exception:
            continue
    return out

STOCKS_RANGES = _parse_ranges(STOCKS_SESSION_UTC)
FOREX_RANGES  = _parse_ranges(FOREX_SESSION_UTC)

def is_session_open(domain: str, now_utc: Optional[datetime]=None) -> bool:
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    dow = now_utc.weekday()  # 0=Mon ... 6=Sun
    minutes = now_utc.hour*60 + now_utc.minute

    if domain == "crypto":
        return True

    if domain == "stocks":
        if not SESSION_FILTER_STOCKS:
            return True
        if dow >= 5:
            return False
        for s,e in STOCKS_RANGES:
            if s <= minutes <= e:
                return True
        return False

    if domain == "forex":
        if not SESSION_FILTER_FOREX:
            return True
        if dow == 6:  # keep simple Sunday filter
            return False
        for s,e in FOREX_RANGES:
            if s <= minutes <= e:
                return True
        return False

    return True

# ---------------- Cards ----------------
def fmt_price(v: Any) -> str:
    if v is None:
        return "n/a"
    try:
        val = float(v)
        if val < 1:   return f"${val:,.6f}"
        if val < 100: return f"${val:,.4f}"
        return f"${val:,.2f}"
    except:
        return str(v)

def add_beginner_explainer(symbol: str, side: str, entry: Optional[float], sl: Optional[float], tp1: Optional[float], tp2: Optional[float]) -> str:
    if not BEGINNER_MODE:
        return ""
    expl = [
        "",
        "🧠 **Beginner Explain:**",
        f"- **{side.title()}** = we expect price to move {'up' if side.upper().startswith('L') else 'down'}.",
        f"- **Entry** is where we get in ({fmt_price(entry)}).",
        f"- **Stop (SL)** is where we exit if wrong ({fmt_price(sl)}).",
    ]
    if tp1 is not None: expl.append(f"- **TP1** = first profit target ({fmt_price(tp1)}).")
    if tp2 is not None: expl.append(f"- **TP2** = second profit target ({fmt_price(tp2)}).")
    expl.append("- Keep risk small. Long game wins.")
    return "\n".join(expl)

def format_score_breakdown(bd: Dict[str, float]) -> str:
    # show normalized 0-100 and raw
    parts = []
    for k in ("trend","momentum","volatility","confluence","liquidity"):
        if k in bd:
            parts.append(f"- {k.title()}: {bd[k]:.0f}/100")
    return "\n".join(parts)

def format_signal_card(
    symbol: str,
    side: str,
    entry: Optional[float],
    sl: Optional[float],
    tf: str,
    score: float,
    stage: str,
    reasons: List[str],
    tp1: Optional[float],
    tp2: Optional[float],
    score_bd: Dict[str,float]
) -> str:
    side = side.upper()
    header_emoji = "🟢" if side.startswith("L") else "🔴"
    stage_emoji = "🧪" if stage == "EARLY" else "✅"
    title = f"{header_emoji} **{symbol} {side}** — {stage_emoji} {stage} ({tf})"
    lines = [title]
    lines.append(f"• Entry: {fmt_price(entry)}")
    lines.append(f"• Stop:  {fmt_price(sl)}")
    if tp1 is not None: lines.append(f"• TP1:   {fmt_price(tp1)}")
    if tp2 is not None: lines.append(f"• TP2:   {fmt_price(tp2)}")
    lines.append(f"• Confidence: {score:.2f}")
    bd = format_score_breakdown(score_bd)
    if bd:
        lines.append("• Rating:")
        lines.append(bd)
    if reasons:
        lines.append("• Why:")
        lines.extend([f"   - {r}" for r in reasons[:6]])
    lines.append("—")
    lines.append("_Use risk management. Not financial advice._")
    return "\n".join(lines)

# ---------------- AI-ish Analyzer (Phase 1) ----------------
def slope(series: pd.Series, window: int = 20) -> float:
    # simple linear regression slope over last `window`
    s = series.dropna()
    if len(s) < window: return 0.0
    y = s.tail(window).values
    x = np.arange(len(y))
    # slope per bar (price units)
    denom = (x - x.mean())
    denom = np.sum(denom * denom)
    if denom == 0: return 0.0
    m = np.sum((x - x.mean()) * (y - y.mean())) / denom
    return float(m)

def compute_score_components(df: pd.DataFrame) -> Tuple[Dict[str,float], Dict[str,Any], List[str]]:
    """
    Returns:
      score_bd: per-component 0..100
      feats: dict of computed features
      reasons: text bullets
    """
    reasons = []
    if df is None or df.empty or len(df) < 60:
        return {"trend":0,"momentum":0,"volatility":0,"confluence":0,"liquidity":50}, {}, ["Not enough data"]

    close = df["Close"]
    sma20 = df["SMA20"]
    sma50 = df["SMA50"]
    atr14 = df["ATR14"]
    vol = df.get("Volume")

    # Trend: SMA20 vs SMA50 + slope of SMA20
    s20 = slope(sma20, 20)
    is_bull = bool((sma20.iloc[-1] > sma50.iloc[-1]) and (s20 >= MIN_TREND_SLOPE))
    is_bear = bool((sma20.iloc[-1] < sma50.iloc[-1]) and (s20 <= -MIN_TREND_SLOPE))
    trend_raw = max(0.0, min(1.0, abs(s20) / (abs(close.iloc[-1])*0.002 + 1e-9)))  # scaled
    trend_score = 60 + 40*trend_raw if (is_bull or is_bear) else 40*trend_raw

    if is_bull: reasons.append("Uptrend (SMA20>SMA50, rising slope)")
    if is_bear: reasons.append("Downtrend (SMA20<SMA50, falling slope)")

    # Momentum: breakout of 20 bars
    brk_up = close.iloc[-1] >= df["ROL_MAX20"].iloc[-2]
    brk_dn = close.iloc[-1] <= df["ROL_MIN20"].iloc[-2]
    momentum_score = 75 if (brk_up or brk_dn) else 45
    if brk_up: reasons.append("20-bar breakout up")
    if brk_dn: reasons.append("20-bar breakdown")

    # Volatility: ATR %
    atr = float(atr14.iloc[-1]) if not np.isnan(atr14.iloc[-1]) else 0.0
    px  = float(close.iloc[-1])
    atr_pct = pct(atr / max(px, 1e-9))
    vol_good = (atr_pct >= MIN_ATR_PCT) and (atr_pct <= MAX_ATR_PCT)
    volatility_score = 80 if vol_good else (50 if atr_pct >= MIN_ATR_PCT else 30)
    if vol_good: reasons.append(f"ATR OK ({atr_pct:.2f}% of price)")

    # Confluence: trend + momentum agree
    conf = 0
    if is_bull and brk_up: conf = 1
    if is_bear and brk_dn: conf = 1
    confluence_score = 85 if conf else 50
    if conf: reasons.append("Trend + Momentum alignment")

    # Liquidity proxy
    if vol is not None and not vol.isna().all():
        last_vol = float(vol.iloc[-1])
        avg_vol  = float(vol.tail(20).mean())
        liq_raw = min(1.0, (last_vol / (avg_vol + 1e-9)))
        liquidity_score = 40 + 60*liq_raw
        if last_vol >= avg_vol: reasons.append("Volume ≥ 20-bar avg")
    else:
        liquidity_score = 60  # neutral for crypto/FX limited volume data

    score_bd = {
        "trend": trend_score,
        "momentum": momentum_score,
        "volatility": volatility_score,
        "confluence": confluence_score,
        "liquidity": liquidity_score,
    }
    feats = {
        "is_bull": is_bull,
        "is_bear": is_bear,
        "brk_up": brk_up,
        "brk_dn": brk_dn,
        "atr": atr,
        "atr_pct": atr_pct,
        "price": px
    }
    return score_bd, feats, reasons

def combine_score(score_bd: Dict[str,float]) -> float:
    # Weighted 0..1
    s = (
        W_TREND  * (score_bd["trend"]/100.0) +
        W_MOMO   * (score_bd["momentum"]/100.0) +
        W_VOL    * (score_bd["volatility"]/100.0) +
        W_CONFL  * (score_bd["confluence"]/100.0) +
        W_LIQ    * (score_bd["liquidity"]/100.0)
    ) / W_SUM
    return float(s)

def pick_side_stage(feats: Dict[str,Any]) -> Tuple[str, str]:
    # Early vs Confirmed
    if feats.get("is_bull") and feats.get("brk_up"):
        return "LONG", "CONFIRMED"
    if feats.get("is_bear") and feats.get("brk_dn"):
        return "SHORT", "CONFIRMED"
    # Early: trend or momentum alone
    if feats.get("is_bull"):
        return "LONG", "EARLY"
    if feats.get("is_bear"):
        return "SHORT", "EARLY"
    if feats.get("brk_up"):
        return "LONG", "EARLY"
    if feats.get("brk_dn"):
        return "SHORT", "EARLY"
    return "LONG", "EARLY"

def propose_levels(px: float, feats: Dict[str,Any], df: pd.DataFrame) -> Tuple[float,float,Optional[float],Optional[float]]:
    """
    Returns entry, sl, tp1, tp2
    Entry = current price
    SL = ATR-based or swing-based simple rule
    TPs = by RR or ATR multiples
    """
    entry = px
    atr = feats.get("atr", 0.0)

    # Simple swing reference
    recent_low  = float(df["Low"].tail(10).min())
    recent_high = float(df["High"].tail(10).max())

    if TP_MODE == "ATR" and atr > 0:
        if feats.get("is_bull"):
            sl = entry - SL_ATR_MULT * atr
            tp1 = entry + RR_TP1 * atr
            tp2 = entry + RR_TP2 * atr
        else:
            sl = entry + SL_ATR_MULT * atr
            tp1 = entry - RR_TP1 * atr
            tp2 = entry - RR_TP2 * atr
    else:
        # RR mode: put SL at swing and compute TP by RR
        if feats.get("is_bull"):
            sl = min(recent_low, entry - max(atr, 1e-9))  # ensure nonzero distance
            risk = entry - sl
            tp1 = entry + RR_TP1 * risk
            tp2 = entry + RR_TP2 * risk
        else:
            sl = max(recent_high, entry + max(atr, 1e-9))
            risk = sl - entry
            tp1 = entry - RR_TP1 * risk
            tp2 = entry - RR_TP2 * risk

    return float(entry), float(sl), float(tp1), float(tp2)

# ---------------- TP/SL Tracking ----------------
OPEN_TRADES: Dict[str, Dict[str, Any]] = {}
# key = f"{domain}:{symbol}"

def register_open_trade(domain: str, symbol: str, side: str, entry: float, sl: float, tp1: Optional[float], tp2: Optional[float]):
    OPEN_TRADES[f"{domain}:{symbol.upper()}"] = {
        "side": side.upper(),
        "entry": float(entry),
        "sl": float(sl),
        "tp1": float(tp1) if tp1 is not None else None,
        "tp2": float(tp2) if tp2 is not None else None,
        "closed": False,
        "tp1_hit": False
    }

async def monitor_open_trades():
    for key, d in list(OPEN_TRADES.items()):
        if d.get("closed"):
            continue
        domain, symbol = key.split(":")

        if domain == "crypto":
            price = fetch_price_crypto(symbol)
            ch_id = CHAN_CRYPTO_ID
        elif domain == "stocks":
            price = fetch_price_stock(symbol)
            ch_id = CHAN_STOCKS_ID
        else:
            price = fetch_price_fx(symbol)
            ch_id = CHAN_FOREX_ID

        if price is None:
            continue

        side, entry, sl = d["side"], d["entry"], d["sl"]
        tp1, tp2 = d.get("tp1"), d.get("tp2")

        hit_tp1 = False
        hit_tp2 = False
        hit_sl  = False

        if side.startswith("L"):
            if tp1 is not None and price >= tp1: hit_tp1 = True
            if tp2 is not None and price >= tp2: hit_tp2 = True
            if price <= sl: hit_sl = True
        else:
            if tp1 is not None and price <= tp1: hit_tp1 = True
            if tp2 is not None and price <= tp2: hit_tp2 = True
            if price >= sl: hit_sl = True

        ch = bot.get_channel(ch_id) if ch_id else None
        if hit_tp1 and not d.get("tp1_hit") and ch:
            await ch.send(f"✅ **{symbol} TP1 hit** at {fmt_price(price)} (entry {fmt_price(entry)})")
            d["tp1_hit"] = True

        if hit_tp2 and ch:
            await ch.send(f"🏁 **{symbol} TP2 hit** at {fmt_price(price)} (entry {fmt_price(entry)})")
            d["closed"] = True

        if hit_sl and ch:
            await ch.send(f"🛑 **{symbol} SL hit** at {fmt_price(price)} (entry {fmt_price(entry)})")
            d["closed"] = True

# ---------------- Scan Pipeline ----------------
def analyze_symbol(domain: str, symbol: str) -> Optional[Dict[str,Any]]:
    # fetch multi-timeframe for confluence: 1h (main), 4h (context)
    df1 = fetch_history(domain, symbol, period="90d", interval="1h")
    df4 = fetch_history(domain, symbol, period="180d", interval="4h")
    if df1 is None or len(df1) < 60:
        return None
    df1 = add_indicators(df1)
    if df4 is not None and not df4.empty:
        df4 = add_indicators(df4)

    # Score on 1h
    bd1, feats1, reasons1 = compute_score_components(df1)

    # Optional filters
    if AI_TREND_FILTER:
        # require either bull or bear bias on 1h
        if not (feats1.get("is_bull") or feats1.get("is_bear")):
            return None
    if AI_VOL_FILTER:
        atr_pct = feats1.get("atr_pct", 0.0)
        if atr_pct < MIN_ATR_PCT or atr_pct > MAX_ATR_PCT:
            return None

    # Confluence with 4h
    conf_bonus = 0
    if df4 is not None and len(df4) >= 60:
        bd4, feats4, reasons4 = compute_score_components(df4)
        if (feats1.get("is_bull") and feats4.get("is_bull")) or (feats1.get("is_bear") and feats4.get("is_bear")):
            conf_bonus = 0.07  # small boost for TF alignment
    bd = bd1.copy()
    # combine final score
    score = combine_score(bd) + conf_bonus
    score = max(0.0, min(1.0, score))

    side, stage = pick_side_stage(feats1)

    # Live price for entry
    if domain == "crypto":
        px = fetch_price_crypto(symbol)
    elif domain == "stocks":
        px = fetch_price_stock(symbol)
    else:
        px = fetch_price_fx(symbol)

    if px is None:
        return None

    entry, sl, tp1, tp2 = propose_levels(px, feats1, df1)

    # Reasons
    reasons = reasons1
    if conf_bonus > 0:
        reasons.append("Higher timeframe agrees (4H confluence)")

    return {
        "side": side,
        "stage": stage,
        "score": score,
        "tf": "1H",
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "reasons": reasons,
        "score_bd": bd
    }

async def scan_watchlist(domain: str, channel: discord.abc.Messageable):
    if domain == "crypto":
        watch = WATCH_CRYPTO
    elif domain == "stocks":
        watch = WATCH_STOCKS
    else:
        watch = WATCH_FOREX

    if not watch:
        # Silent scan policy: only post when signal found
        return

    if not is_session_open(domain):
        return

    for sym in watch:
        try:
            res = analyze_symbol(domain, sym)
            if not res:
                continue

            score = float(res["score"])
            if score < AI_SCORE_THRESHOLD:
                continue

            # Build & post card
            side = res["side"]
            stage = res["stage"]
            tf = res["tf"]
            entry = res["entry"]
            sl = res["sl"]
            tp1 = res["tp1"]
            tp2 = res["tp2"]
            reasons = res["reasons"]
            score_bd = res.get("score_bd", {})

            card = format_signal_card(
                symbol=sym, side=side, entry=entry, sl=sl, tf=tf,
                score=score, stage=stage, reasons=reasons, tp1=tp1, tp2=tp2,
                score_bd=score_bd
            )
            expl = add_beginner_explainer(sym, side, entry, sl, tp1, tp2)
            await channel.send(card + (("\n" + expl) if expl else ""))

            # Track TP/SL
            register_open_trade(domain, sym, side, entry, sl, tp1, tp2)

        except Exception as e:
            # keep silent on errors to minimize noise, log in console
            print(f"[scan] {domain}:{sym} error: {e}")

# ---------------- Commands ----------------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (id: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="JCF HQ online"))
    if ANNOUNCE_CHANNEL_ID:
        ch = bot.get_channel(ANNOUNCE_CHANNEL_ID)
        if ch:
            await ch.send("✅ **JCFWatchBot ONLINE** — AI scans + TP/SL tracking live.")

    if AI_SCAN_LOOP and not getattr(bot, "_scan_task_started", False):
        bot._scan_task_started = True
        bot.loop.create_task(background_scan_loop())

@bot.command()
async def ping(ctx):
    await ctx.reply("Pong 🏓")

@bot.command(name="scan")
async def scan_cmd(ctx, which: str = "crypto"):
    which = which.lower().strip()
    if which not in ("crypto", "stocks", "forex"):
        return await ctx.reply("Use `!scan crypto`, `!scan stocks`, or `!scan forex`")
    await scan_watchlist(which, ctx.channel)

@bot.command(name="scanonce")
async def scanonce_cmd(ctx):
    # quick manual pulse on all
    if CHAN_CRYPTO_ID:
        await scan_watchlist("crypto", ctx.channel)
    if CHAN_STOCKS_ID:
        await scan_watchlist("stocks", ctx.channel)
    if CHAN_FOREX_ID:
        await scan_watchlist("forex", ctx.channel)

# ---------------- Background Auto-Scan ----------------
async def background_scan_loop():
    await bot.wait_until_ready()
    print("⏱️ Auto-scan loop started")

    while not bot.is_closed():
        try:
            # 1) TP/SL tracking first
            await monitor_open_trades()

            # 2) Domain scans (silent unless signal passes)
            if CHAN_CRYPTO_ID:
                ch = bot.get_channel(CHAN_CRYPTO_ID)
                if ch: await scan_watchlist("crypto", ch)

            if CHAN_STOCKS_ID:
                ch = bot.get_channel(CHAN_STOCKS_ID)
                if ch: await scan_watchlist("stocks", ch)

            if CHAN_FOREX_ID:
                ch = bot.get_channel(CHAN_FOREX_ID)
                if ch: await scan_watchlist("forex", ch)

        except Exception as e:
            print(f"[AutoScan] Error: {e}")

        await asyncio.sleep(int(SCAN_INTERVAL_MIN * 60))

# ---------------- Boot ----------------
if __name__ == "__main__":
    bot.run(TOKEN)