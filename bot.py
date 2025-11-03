import os, asyncio, time, math, logging
from typing import Dict, List, Optional, Tuple
import requests, pandas as pd

import discord
from discord.ext import commands, tasks

# ==================== ENV / CONFIG ====================

TOKEN = os.getenv("DISCORD_TOKEN", "")
CHANNEL_ID = int(os.getenv("CRYPTO_SETUPS_CHANNEL_ID", "0") or "0")

ANALYSIS_COINS = [s.strip().upper() for s in os.getenv("ANALYSIS_COINS", "ETHUSDT,SOLUSDT").split(",") if s.strip()]
TIMEFRAME = os.getenv("ANALYSIS_TIMEFRAME", "30m").strip().lower()

EMA_PERIODS = [int(x) for x in os.getenv("EMA_PERIODS", "20,50,200").split(",")]
EMA_FAST, EMA_MED, EMA_SLOW = sorted(EMA_PERIODS)[0], sorted(EMA_PERIODS)[1], sorted(EMA_PERIODS)[2]

BB_PERIOD = int(os.getenv("BB_PERIOD", "20"))
BB_STD = float(os.getenv("BB_STD", "2.0"))

OB_LENGTH = int(os.getenv("OB_LENGTH", "5"))             # Pine: Volume Pivot Length
MITIGATION_METHOD = os.getenv("MITIGATION_METHOD", "wick").strip().lower()  # 'wick' or 'close'

RISK_MODE = os.getenv("RISK_MODE", "balanced").strip().lower()
SCAN_INTERVAL_SEC = int(os.getenv("SCAN_INTERVAL_SEC", "300"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
DUPLICATE_COOLDOWN_MIN = int(os.getenv("DUPLICATE_COOLDOWN_MIN", "120"))

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
log = logging.getLogger("jcfhq-crypto")

# ==================== DISCORD ====================

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# tracked setups & duplicate suppression
open_setups: Dict[str, Dict] = {}
recent_alerts: Dict[str, float] = {}

# ==================== DATA ====================

BINANCE_BASE = "https://api.binance.com/api/v3"

def fetch_klines(symbol: str, interval: str, limit: int = 600) -> pd.DataFrame:
    url = f"{BINANCE_BASE}/klines"
    params = {"symbol": symbol, "interval": interval, "limit": min(limit, 1000)}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    cols = ["open_time","open","high","low","close","volume",
            "close_time","quote_asset_volume","number_of_trades",
            "taker_buy_base","taker_buy_quote","ignore"]
    df = pd.DataFrame(data, columns=cols)
    for c in ["open","high","low","close","volume"]:
        df[c] = df[c].astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    return df

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df[f"ema_{EMA_FAST}"] = df["close"].ewm(span=EMA_FAST, adjust=False).mean()
    df[f"ema_{EMA_MED}"]  = df["close"].ewm(span=EMA_MED,  adjust=False).mean()
    df[f"ema_{EMA_SLOW}"] = df["close"].ewm(span=EMA_SLOW, adjust=False).mean()

    rolling = df["close"].rolling(BB_PERIOD)
    ma = rolling.mean()
    std = rolling.std(ddof=0)
    df["bb_mid"] = ma
    df["bb_up"]  = ma + BB_STD * std
    df["bb_dn"]  = ma - BB_STD * std

    df["body"]  = (df["close"] - df["open"]).abs()
    df["range"] = df["high"] - df["low"]
    return df

def risk_params(mode: str) -> Dict:
    mode = mode.lower()
    if mode == "conservative":
        return {"min_rr": 1.8, "pad": 0.0005, "require_slow": True}
    if mode == "aggressive":
        return {"min_rr": 1.2, "pad": 0.0015, "require_slow": False}
    return {"min_rr": 1.5, "pad": 0.0010, "require_slow": True}

# ==================== LUX-STYLE OB DETECTOR ====================

def _pivot_high_volume_mask(vol: pd.Series, length: int) -> pd.Series:
    """
    Pine: phv = ta.pivothigh(volume, length, length)
    True when vol[idx] is the highest within a centered window of size 2*length+1.
    We emulate with rolling max and compare the central value.
    """
    win = 2*length + 1
    # centered rolling max (approx by comparing with past window shifted)
    max_back = vol.rolling(win, center=True).max()
    return (vol == max_back)

def compute_ob_fields(df: pd.DataFrame, length: int) -> pd.DataFrame:
    """
    Implements the same state used in the Pine script:
      upper = highest(length), lower = lowest(length)
      os := high[length] > upper ? 0 : low[length] < lower ? 1 : os[1]
    We approximate by shifting by 'length' to look back.
    """
    df = df.copy()

    # highest/lowest over last 'length' bars (Pine evaluates at the bar using [length] indexing)
    df["upper"] = df["high"].rolling(length).max()
    df["lower"] = df["low"].rolling(length).min()

    # shifted references like high[length], low[length], hl2[length]
    df["high_l"] = df["high"].shift(length)
    df["low_l"]  = df["low"].shift(length)
    df["hl2"]    = (df["high"] + df["low"]) / 2.0
    df["hl2_l"]  = df["hl2"].shift(length)

    # volume pivot high (centered window)
    df["phv"] = _pivot_high_volume_mask(df["volume"], length)

    # os state (0 when prior high broke above upper; 1 when prior low broke below lower; else keep previous)
    os_vals = []
    prev = 0
    for idx, row in df.iterrows():
        cond0 = (not pd.isna(row["high_l"])) and (not pd.isna(row["upper"])) and (row["high_l"] > row["upper"])
        cond1 = (not pd.isna(row["low_l"]))  and (not pd.isna(row["lower"])) and (row["low_l"]  < row["lower"])
        if cond0:
            prev = 0
        elif cond1:
            prev = 1
        os_vals.append(prev)
    df["os"] = os_vals

    # mitigation targets
    if MITIGATION_METHOD == "close":
        df["target_bull"] = df["close"].rolling(length).min()
        df["target_bear"] = df["close"].rolling(length).max()
    else:
        df["target_bull"] = df["low"].rolling(length).min()
        df["target_bear"] = df["high"].rolling(length).max()

    # Bullish OB coordinate event (on formation bar) per Pine:
    # get_coordinates(phv and os == 1, hl2[length], low[length], low[length])
    df["bull_ob_top"]   = df["hl2_l"]
    df["bull_ob_btm"]   = df["low_l"]
    df["bull_ob_value"] = df["low_l"]
    df["bull_form"]     = df["phv"] & (df["os"] == 1)

    # Bearish OB:
    # get_coordinates(phv and os == 0, high[length], hl2[length], high[length])
    df["bear_ob_top"]   = df["high_l"]
    df["bear_ob_btm"]   = df["hl2_l"]
    df["bear_ob_value"] = df["high_l"]
    df["bear_form"]     = df["phv"] & (df["os"] == 0)

    return df

def _latest_unmitigated_zone(df: pd.DataFrame, side: str) -> Optional[Tuple[float,float,pd.Timestamp]]:
    """
    Walk backward to find the most recent OB 'box' and consider it unmitigated
    until target breaches into it (per Pine's remove_mitigated logic).
    For trading, we want a signal WHEN mitigation occurs (touch), so we return the most recent OB
    and let the caller check if current bar has mitigated it.
    """
    if side == "long":
        mask = df["bull_form"].fillna(False)
        top_col, btm_col = "bull_ob_top", "bull_ob_btm"
    else:
        mask = df["bear_form"].fillna(False)
        top_col, btm_col = "bear_ob_top", "bear_ob_btm"

    idxs = df.index[mask]
    if len(idxs) == 0:
        return None
    last_idx = idxs[-1]
    top = float(df.loc[last_idx, top_col])
    btm = float(df.loc[last_idx, btm_col])
    ts  = df.loc[last_idx, "close_time"]
    if math.isnan(top) or math.isnan(btm):
        return None
    # ensure proper ordering (top >= bottom)
    hi, lo = max(top, btm), min(top, btm)
    return (hi, lo, ts)

def _is_mitigated_now(df: pd.DataFrame, side: str, hi: float, lo: float) -> bool:
    """
    True if the LATEST CLOSED candle has 'touched' the OB zone per mitigation method.
    """
    c = df.iloc[-1]
    if side == "long":
        # price revisits the bullish OB: touch between lo..hi
        if MITIGATION_METHOD == "close":
            return (lo <= c["close"] <= hi)
        else:
            return not (c["low"] > hi or c["high"] < lo)  # wick overlap with box
    else:
        if MITIGATION_METHOD == "close":
            return (lo <= c["close"] <= hi)
        else:
            return not (c["low"] > hi or c["high"] < lo)

# ==================== STRATEGY WRAPPER ====================

def _trend_ok(df: pd.DataFrame, require_slow: bool, side: str) -> bool:
    emaf = df[f"ema_{EMA_FAST}"].iloc[-1]
    emam = df[f"ema_{EMA_MED}"].iloc[-1]
    emas = df[f"ema_{EMA_SLOW}"].iloc[-1]
    if side == "long":
        return (emaf > emam) and (emam > emas if require_slow else True)
    else:
        return (emaf < emam) and (emam < emas if require_slow else True)

def _make_tp_series(entry: float, sl: float, side: str) -> Tuple[List[float], float]:
    risk = abs(entry - sl)
    if side == "long":
        tps = [entry + risk*1.0, entry + risk*1.5, entry + risk*2.0]
        rr  = (tps[0]-entry)/risk if risk>0 else 0
    else:
        tps = [entry - risk*1.0, entry - risk*1.5, entry - risk*2.0]
        rr  = (entry-tps[0])/risk if risk>0 else 0
    return tps, rr

def find_setups(symbol: str, df: pd.DataFrame) -> List[Dict]:
    """
    Lux-style OB flow:
      1) Detect most recent OB (bull/bear) per Pine conditions.
      2) When price mitigates the OB (touch by wick/close), that is our entry trigger.
      3) Entry = BB mid (if available) or OB avg; SL beyond opposite side w/ padding; TP 1R/1.5R/2R.
      4) Gate by EMA trend and optional BB contextual sanity (optional, kept soft).
    """
    out: List[Dict] = []
    pars = risk_params(RISK_MODE)
    require_slow = pars["require_slow"]
    pad = pars["pad"]

    if len(df) < max(EMA_SLOW, BB_PERIOD) + OB_LENGTH + 5:
        return out

    df = compute_ob_fields(df, OB_LENGTH)
    df = add_indicators(df)

    now = df.iloc[-1]
    bb_mid = float(df["bb_mid"].iloc[-1]) if not math.isnan(df["bb_mid"].iloc[-1]) else None

    # ---------- Bullish OB path ----------
    bull_zone = _latest_unmitigated_zone(df, "long")
    if bull_zone and _trend_ok(df, require_slow, "long"):
        hi, lo, ts = bull_zone
        if _is_mitigated_now(df, "long", hi, lo):
            entry = bb_mid if bb_mid else (hi + lo)/2.0
            sl    = lo * (1 - pad)
            if entry > sl:
                tps, rr = _make_tp_series(entry, sl, "long")
                if rr >= pars["min_rr"]:
                    reason = f"🟢 Bullish OB mitigated ({MITIGATION_METHOD}); EMA trend up; entry on BB-mid/zone."
                    out.append({
                        "symbol": symbol, "side": "long",
                        "entry": entry, "sl": sl, "tps": tps,
                        "created_at": now["close_time"], "active": True, "reason": reason
                    })

    # ---------- Bearish OB path ----------
    bear_zone = _latest_unmitigated_zone(df, "short")
    if bear_zone and _trend_ok(df, require_slow, "short"):
        hi, lo, ts = bear_zone
        if _is_mitigated_now(df, "short", hi, lo):
            entry = bb_mid if bb_mid else (hi + lo)/2.0
            sl    = hi * (1 + pad)
            if entry < sl:
                tps, rr = _make_tp_series(entry, sl, "short")
                if rr >= pars["min_rr"]:
                    reason = f"🔴 Bearish OB mitigated ({MITIGATION_METHOD}); EMA trend down; entry on BB-mid/zone."
                    out.append({
                        "symbol": symbol, "side": "short",
                        "entry": entry, "sl": sl, "tps": tps,
                        "created_at": now["close_time"], "active": True, "reason": reason
                    })
    return out

# ==================== ALERTING / STATE ====================

def format_setup_card(setup: Dict, timeframe: str) -> str:
    side_emoji = "🟢 LONG" if setup["side"] == "long" else "🔴 SHORT"
    tps_txt = " / ".join([f"{tp:.6f}" for tp in setup["tps"]])
    # RR shown for first TP
    if setup["side"] == "long":
        rr = (setup["tps"][0] - setup["entry"]) / max(setup["entry"] - setup["sl"], 1e-12)
    else:
        rr = (setup["entry"] - setup["tps"][0]) / max(setup["sl"] - setup["entry"], 1e-12)
    return (
        f"**{side_emoji} – {setup['symbol']} ({timeframe})**\n"
        f"Entry: **{setup['entry']:.6f}**   SL: **{setup['sl']:.6f}**   TP(s): **{tps_txt}**\n"
        f"Est. RR(→TP1): **{rr:.2f}**\n"
        f"{setup['reason']}\n"
        f"📅 {setup['created_at']}"
    )

def signature_key(setup: Dict) -> str:
    return f"{setup['symbol']}:{setup['side']}:{int(pd.Timestamp(setup['created_at']).value/1e9)}"

async def post_to_channel(text: str):
    ch = bot.get_channel(CHANNEL_ID)
    if ch: await ch.send(text)
    else: log.error("Channel not found; check CRYPTO_SETUPS_CHANNEL_ID")

def latest_price(symbol: str) -> Optional[float]:
    try:
        r = requests.get(f"{BINANCE_BASE}/ticker/price", params={"symbol": symbol}, timeout=10)
        r.raise_for_status()
        return float(r.json()["price"])
    except Exception as e:
        log.error(f"price fetch error {symbol}: {e}")
        return None

def should_suppress(setup: Dict) -> bool:
    sig = signature_key(setup)
    last = recent_alerts.get(sig)
    if not last: return False
    return (time.time() - last) < (DUPLICATE_COOLDOWN_MIN * 60)

def mark_alerted(setup: Dict):
    recent_alerts[signature_key(setup)] = time.time()

def price_touches(value: float, price: float, tol_bps: float = 8.0) -> bool:
    diff = abs(price - value) / max(value, 1e-12) * 10000
    return diff <= tol_bps

def check_tp_sl_progress(symbol: str):
    if symbol not in open_setups: return
    st = open_setups[symbol]
    if not st.get("active"): return
    price = latest_price(symbol)
    if price is None: return
    if st["side"] == "long":
        if price <= st["sl"]:
            st["active"] = False; st["closed_reason"] = "Stop Loss hit"
        elif any(price >= tp or price_touches(tp, price) for tp in st["tps"]):
            st["active"] = False; st["closed_reason"] = "Take Profit reached"
    else:
        if price >= st["sl"]:
            st["active"] = False; st["closed_reason"] = "Stop Loss hit"
        elif any(price <= tp or price_touches(tp, price) for tp in st["tps"]):
            st["active"] = False; st["closed_reason"] = "Take Profit reached"

# ==================== SCANNER ====================

async def scan_once():
    found = False
    for symbol in ANALYSIS_COINS:
        try:
            df = fetch_klines(symbol, TIMEFRAME, limit=max(EMA_SLOW, BB_PERIOD) + 2*OB_LENGTH + 150)
            df = add_indicators(df)

            # close active setups
            check_tp_sl_progress(symbol)

            # find fresh setups
            setups = find_setups(symbol, df)
            for s in setups:
                # one active per symbol
                if symbol in open_setups and open_setups[symbol].get("active"):
                    continue
                if should_suppress(s):
                    continue
                msg = format_setup_card(s, TIMEFRAME)
                await post_to_channel(msg)
                open_setups[symbol] = s
                mark_alerted(s)
                found = True
        except Exception as e:
            log.exception(f"[scan] {symbol}: {e}")

    if not found:
        log.info("No notable crypto setups this scan.")

@tasks.loop(seconds=max(SCAN_INTERVAL_SEC, 60))
async def scanner():
    await scan_once()

@scanner.before_loop
async def before_scanner():
    await bot.wait_until_ready()
    log.info("Scanner started.")

# ==================== COMMANDS ====================

@bot.event
async def on_ready():
    log.info(f"✅ Logged in as {bot.user} (id: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="JCF HQ – OB/EMA/BB scanner"))
    ch = bot.get_channel(CHANNEL_ID)
    if ch:
        await ch.send(f"✅ **Crypto scanner online** — OB_LENGTH={OB_LENGTH}, mitigation={MITIGATION_METHOD}.")
    if not scanner.is_running():
        scanner.start()

@bot.command()
async def status(ctx):
    act = [k for k,v in open_setups.items() if v.get("active")]
    await ctx.reply(
        f"🛰️ TF: **{TIMEFRAME}** | Coins: **{len(ANALYSIS_COINS)}** | Risk: **{RISK_MODE}** | "
        f"OB_LENGTH: **{OB_LENGTH}** | Mitigation: **{MITIGATION_METHOD}**\n"
        f"Active setups: **{len(act)}** ({', '.join(act) if act else 'none'})"
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

# ==================== RUN ====================

if __name__ == "__main__":
    if not TOKEN or CHANNEL_ID == 0:
        raise SystemExit("Missing DISCORD_TOKEN or CRYPTO_SETUPS_CHANNEL_ID")
    bot.run(TOKEN)