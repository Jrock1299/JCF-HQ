import os
import asyncio
import time
import math
import logging
from typing import Dict, List, Tuple, Optional

import requests
import pandas as pd

import discord
from discord.ext import commands, tasks

# ---------- Config & Logging ----------

TOKEN = os.getenv("DISCORD_TOKEN", "")
CHANNEL_ID = int(os.getenv("CRYPTO_SETUPS_CHANNEL_ID", "0") or "0")

ANALYSIS_COINS = [s.strip().upper() for s in os.getenv("ANALYSIS_COINS", "ETHUSDT,SOLUSDT").split(",") if s.strip()]
TIMEFRAME = os.getenv("ANALYSIS_TIMEFRAME", "30m").strip().lower()

EMA_PERIODS = [int(x) for x in os.getenv("EMA_PERIODS", "20,50,200").split(",")]
EMA_FAST, EMA_MED, EMA_SLOW = sorted(EMA_PERIODS)[0], sorted(EMA_PERIODS)[1], sorted(EMA_PERIODS)[2]

BB_PERIOD = int(os.getenv("BB_PERIOD", "20"))
BB_STD = float(os.getenv("BB_STD", "2.0"))

RISK_MODE = os.getenv("RISK_MODE", "balanced").strip().lower()
SCAN_INTERVAL_SEC = int(os.getenv("SCAN_INTERVAL_SEC", "300"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
DUPLICATE_COOLDOWN_MIN = int(os.getenv("DUPLICATE_COOLDOWN_MIN", "120"))

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
log = logging.getLogger("jcfhq-crypto")

# ---------- Discord Bot ----------

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# State: open setups (per symbol) – survives while process runs
open_setups: Dict[str, Dict] = {}
# Recently alerted signatures to avoid spam on restarts
recent_alerts: Dict[str, float] = {}  # key: f"{symbol}:{side}:{t0}" -> last_ts

# ---------- Helpers ----------

BINANCE_BASE = "https://api.binance.com/api/v3"

def fetch_klines(symbol: str, interval: str, limit: int = 300) -> pd.DataFrame:
    url = f"{BINANCE_BASE}/klines"
    params = {"symbol": symbol, "interval": interval, "limit": min(limit, 1000)}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    cols = [
        "open_time","open","high","low","close","volume",
        "close_time","quote_asset_volume","number_of_trades",
        "taker_buy_base","taker_buy_quote","ignore"
    ]
    df = pd.DataFrame(data, columns=cols)
    for c in ["open","high","low","close","volume"]:
        df[c] = df[c].astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")
    return df

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    # EMAs
    df[f"ema_{EMA_FAST}"] = df["close"].ewm(span=EMA_FAST, adjust=False).mean()
    df[f"ema_{EMA_MED}"]  = df["close"].ewm(span=EMA_MED, adjust=False).mean()
    df[f"ema_{EMA_SLOW}"] = df["close"].ewm(span=EMA_SLOW, adjust=False).mean()

    # Bollinger Bands
    rolling = df["close"].rolling(BB_PERIOD)
    ma = rolling.mean()
    std = rolling.std(ddof=0)
    df["bb_mid"] = ma
    df["bb_up"] = ma + BB_STD * std
    df["bb_dn"] = ma - BB_STD * std

    # Candle body and range
    df["body"] = (df["close"] - df["open"]).abs()
    df["range"] = df["high"] - df["low"]
    return df

def risk_params(mode: str) -> Dict:
    mode = mode.lower()
    if mode == "conservative":
        return {
            "min_displacement": 1.25,  # multiple of ATR-ish proxy (range avg)
            "min_rr": 1.8,
            "require_ema_slow_alignment": True,
            "use_tighter_sl": True,
        }
    if mode == "aggressive":
        return {
            "min_displacement": 0.9,
            "min_rr": 1.2,
            "require_ema_slow_alignment": False,
            "use_tighter_sl": False,
        }
    # balanced default
    return {
        "min_displacement": 1.1,
        "min_rr": 1.5,
        "require_ema_slow_alignment": True,
        "use_tighter_sl": False,
    }

def displacement_strength(df: pd.DataFrame, idx: int, lookback: int = 20) -> float:
    """
    Rough displacement score: last candle range / avg range(lookback).
    """
    if idx < 1:
        return 0.0
    recent = df.iloc[idx]
    avg_range = df["range"].iloc[max(0, idx - lookback):idx].mean()
    if not avg_range or math.isnan(avg_range):
        return 0.0
    return float(recent["range"] / avg_range)

def last_opposing_candle(df: pd.DataFrame, idx: int, direction: str, search_back: int = 10) -> Optional[pd.Series]:
    """
    For long: last strong red candle before breakout.
    For short: last strong green candle before breakdown.
    """
    start = max(0, idx - search_back)
    window = df.iloc[start:idx]
    if direction == "long":
        # red candles: close < open; pick largest body
        reds = window[window["close"] < window["open"]].copy()
        if reds.empty: 
            return None
        reds["body_size"] = (reds["open"] - reds["close"]).abs()
        return reds.iloc[reds["body_size"].idxmax()]
    else:
        greens = window[window["close"] > window["open"]].copy()
        if greens.empty:
            return None
        greens["body_size"] = (greens["close"] - greens["open"]).abs()
        return greens.iloc[greens["body_size"].idxmax()]

def make_setup(symbol: str, side: str, entry: float, sl: float, tps: List[float], ts: pd.Timestamp, reason: str) -> Dict:
    return {
        "symbol": symbol,
        "side": side,
        "entry": entry,
        "sl": sl,
        "tps": tps,
        "created_at": ts,
        "active": True,
        "reason": reason,
    }

def format_setup_card(setup: Dict, timeframe: str) -> str:
    side_emoji = "🟢 LONG" if setup["side"] == "long" else "🔴 SHORT"
    tps_txt = " / ".join([f"{tp:.4f}" for tp in setup["tps"]])
    rr = max( (max(setup["tps"]) - setup["entry"]) / (setup["entry"] - setup["sl"]), 0.0001 ) if setup["side"]=="long" else \
         max( (setup["entry"] - min(setup["tps"])) / (setup["sl"] - setup["entry"]), 0.0001 )
    return (
        f"**{side_emoji} – {setup['symbol']} ({timeframe})**\n"
        f"Entry: **{setup['entry']:.5f}**   SL: **{setup['sl']:.5f}**   TP(s): **{tps_txt}**\n"
        f"Est. RR: **{rr:.2f}**\n"
        f"Reason: {setup['reason']}\n"
        f"⌚ {setup['created_at']}"
    )

def signature_key(symbol: str, side: str, created_at: pd.Timestamp) -> str:
    return f"{symbol}:{side}:{int(created_at.value/1e9)}"

def price_touches(value: float, price: float, tol_bps: float = 5.0) -> bool:
    """
    Considered 'touched' if within tolerance (basis points).
    """
    if value == 0: 
        return False
    diff = abs(price - value) / value * 10000  # bps
    return diff <= tol_bps

# ---------- Core Strategy (OB-flavored EMA+BB) ----------

def find_setups(symbol: str, df: pd.DataFrame) -> List[Dict]:
    """
    Detects potential long/short setups using:
      - Trend via EMAs (fast>med>(slow) for longs; inverse for shorts)
      - Displacement breakout: close beyond recent high/low with strong range
      - Order-block heuristic: last opposing candle defines retest zone
      - Entry on mid/upper/lower BB retest depending on side
      - SL just beyond OB candle extreme (tighter SL in conservative)
      - TPs at 1R / 1.5R / 2R from entry
    """
    pars = risk_params(RISK_MODE)
    setups: List[Dict] = []

    if len(df) < max(EMA_SLOW, BB_PERIOD) + 5:
        return setups

    i = len(df) - 1  # use last CLOSED candle
    c = df.iloc[i]
    prev = df.iloc[i-1]

    ema_f = df[f"ema_{EMA_FAST}"].iloc[i]
    ema_m = df[f"ema_{EMA_MED}"].iloc[i]
    ema_s = df[f"ema_{EMA_SLOW}"].iloc[i]

    disp = displacement_strength(df, i)

    # Long bias
    long_trend_ok = ema_f > ema_m and (ema_m > ema_s if pars["require_ema_slow_alignment"] else True)
    # Short bias
    short_trend_ok = ema_f < ema_m and (ema_m < ema_s if pars["require_ema_slow_alignment"] else True)

    # Recent swing window for breakout check
    look = 10
    recent_high = df["high"].iloc[i-look:i].max()
    recent_low  = df["low"].iloc[i-look:i].min()

    # --- LONG candidate: close breaks above recent high with displacement ---
    if long_trend_ok and c["close"] > recent_high and disp >= pars["min_displacement"]:
        ob = last_opposing_candle(df, i, "long", search_back=10)
        if ob is not None:
            # OB zone = body of last red candle
            ob_low = min(ob["open"], ob["close"])
            ob_high = max(ob["open"], ob["close"])
            # Entry on BB mid/upper retest: choose mid if available, else ob_high
            entry_candidate = float(df["bb_mid"].iloc[i]) if not math.isnan(df["bb_mid"].iloc[i]) else float(ob_high)
            # SL tucked below OB low; tighter in conservative
            pad = 0.0005 if pars["use_tighter_sl"] else 0.0010
            sl = float(ob_low) * (1 - pad)
            # Ensure valid
            if entry_candidate > sl:
                r1 = entry_candidate + (entry_candidate - sl) * 1.0
                r15 = entry_candidate + (entry_candidate - sl) * 1.5
                r2 = entry_candidate + (entry_candidate - sl) * 2.0
                rr = (r1 - entry_candidate) / (entry_candidate - sl)
                if rr >= pars["min_rr"]:
                    reason = f"Trend up (EMA {EMA_FAST}>{EMA_MED}{'>EMA_'+str(EMA_SLOW) if pars['require_ema_slow_alignment'] else ''}), breakout w/ displacement {disp:.2f}, OB retest."
                    setups.append(make_setup(symbol, "long", entry_candidate, sl, [r1, r15, r2], c["close_time"], reason))

    # --- SHORT candidate: close breaks below recent low with displacement ---
    if short_trend_ok and c["close"] < recent_low and disp >= pars["min_displacement"]:
        ob = last_opposing_candle(df, i, "short", search_back=10)
        if ob is not None:
            ob_low = min(ob["open"], ob["close"])
            ob_high = max(ob["open"], ob["close"])
            entry_candidate = float(df["bb_mid"].iloc[i]) if not math.isnan(df["bb_mid"].iloc[i]) else float(ob_low)
            pad = 0.0005 if pars["use_tighter_sl"] else 0.0010
            sl = float(ob_high) * (1 + pad)
            if entry_candidate < sl:
                r1 = entry_candidate - (sl - entry_candidate) * 1.0
                r15 = entry_candidate - (sl - entry_candidate) * 1.5
                r2 = entry_candidate - (sl - entry_candidate) * 2.0
                rr = (entry_candidate - r1) / (sl - entry_candidate)
                if rr >= pars["min_rr"]:
                    reason = f"Trend down (EMA {EMA_FAST}<{EMA_MED}{'<EMA_'+str(EMA_SLOW) if pars['require_ema_slow_alignment'] else ''}), breakdown w/ displacement {disp:.2f}, OB retest."
                    setups.append(make_setup(symbol, "short", entry_candidate, sl, [r1, r15, r2], c["close_time"], reason))

    return setups

async def post_to_channel(text: str):
    ch = bot.get_channel(CHANNEL_ID)
    if ch:
        await ch.send(text)
    else:
        log.error("Channel not found; check CRYPTO_SETUPS_CHANNEL_ID")

def latest_price(symbol: str) -> Optional[float]:
    url = f"{BINANCE_BASE}/ticker/price"
    try:
        r = requests.get(url, params={"symbol": symbol}, timeout=10)
        r.raise_for_status()
        return float(r.json()["price"])
    except Exception as e:
        log.error(f"price fetch error {symbol}: {e}")
        return None

def should_suppress(setup: Dict) -> bool:
    sig = signature_key(setup["symbol"], setup["side"], setup["created_at"])
    last = recent_alerts.get(sig)
    if not last:
        return False
    return (time.time() - last) < (DUPLICATE_COOLDOWN_MIN * 60)

def mark_alerted(setup: Dict):
    sig = signature_key(setup["symbol"], setup["side"], setup["created_at"])
    recent_alerts[sig] = time.time()

def check_tp_sl_progress(symbol: str):
    """Close active setups if TP/SL hit; avoids repeat alerts."""
    if symbol not in open_setups:
        return
    st = open_setups[symbol]
    if not st.get("active"):
        return
    price = latest_price(symbol)
    if price is None:
        return
    if st["side"] == "long":
        # SL first
        if price <= st["sl"]:
            st["active"] = False
            st["closed_reason"] = "Stop Loss hit"
        # TPs ascending
        elif any(price_touches(tp, price, tol_bps=8.0) or price >= tp for tp in st["tps"]):
            st["active"] = False
            st["closed_reason"] = "Take Profit reached"
    else:
        if price >= st["sl"]:
            st["active"] = False
            st["closed_reason"] = "Stop Loss hit"
        elif any(price_touches(tp, price, tol_bps=8.0) or price <= tp for tp in st["tps"]):
            st["active"] = False
            st["closed_reason"] = "Take Profit reached"

# ---------- Scanner Task ----------

async def scan_once():
    found_any = False
    for symbol in ANALYSIS_COINS:
        try:
            df = fetch_klines(symbol, TIMEFRAME, limit=max(EMA_SLOW, BB_PERIOD) + 120)
            df = add_indicators(df)

            # Close setups if TP/SL hit
            check_tp_sl_progress(symbol)

            setups = find_setups(symbol, df)
            if not setups:
                continue

            for s in setups:
                if should_suppress(s):
                    continue
                # Don’t stack setups: only one active per symbol
                if symbol in open_setups and open_setups[symbol].get("active"):
                    continue

                msg = format_setup_card(s, TIMEFRAME)
                await post_to_channel(msg)
                open_setups[symbol] = s
                mark_alerted(s)
                found_any = True
        except Exception as e:
            log.exception(f"[scan] {symbol}: {e}")
            continue

    if not found_any:
        log.info("No notable crypto setups this scan.")

@tasks.loop(seconds=max(SCAN_INTERVAL_SEC, 60))
async def scanner():
    await scan_once()

@scanner.before_loop
async def before_scanner():
    await bot.wait_until_ready()
    log.info("Scanner started.")

# ---------- Commands ----------

@bot.event
async def on_ready():
    log.info(f"✅ Logged in as {bot.user} (id: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="JCF HQ – crypto radar"))
    ch = bot.get_channel(CHANNEL_ID)
    if ch:
        await ch.send("✅ **Crypto scanner online** — EMA+BB+OB mode activated.")
    if not scanner.is_running():
        scanner.start()

@bot.command()
async def status(ctx):
    active = [k for k,v in open_setups.items() if v.get("active")]
    await ctx.reply(
        f"🛰️ Scanner: **{TIMEFRAME}**, coins: **{len(ANALYSIS_COINS)}**, risk: **{RISK_MODE}**\n"
        f"Active setups: **{len(active)}** ({', '.join(active) if active else 'none'})"
    )

@bot.command()
async def scan(ctx):
    await ctx.reply("🔎 Scanning now…")
    await scan_once()
    await ctx.reply("✅ Scan complete.")

@bot.command()
async def coins(ctx):
    await ctx.reply(f"🪙 Tracking: {', '.join(ANALYSIS_COINS)} | TF: {TIMEFRAME}")

@bot.command()
async def reset_open(ctx):
    open_setups.clear()
    await ctx.reply("♻️ Cleared tracked open setups.")

# ---------- Run ----------
if __name__ == "__main__":
    if not TOKEN or CHANNEL_ID == 0:
        raise SystemExit("Missing DISCORD_TOKEN or CRYPTO_SETUPS_CHANNEL_ID")
    bot.run(TOKEN)