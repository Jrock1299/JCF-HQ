import os, asyncio, math, random, time, json
from typing import Dict, List, Optional, Tuple
import aiohttp
import discord
from discord.ext import commands

# ========= Config & Env =========

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
AV_KEY = os.getenv("ALPHAVANTAGE_API_KEY", "").strip()

# Channel IDs (as strings or ints are fine; we'll coerce later)
CHANNEL_CRYPTO_ID = os.getenv("CHANNEL_CRYPTO_ID", "").strip()
CHANNEL_STOCKS_ID = os.getenv("CHANNEL_STOCKS_ID", "").strip()
CHANNEL_FOREX_ID  = os.getenv("CHANNEL_FOREX_ID", "").strip()

# Legacy & new watchlist envs (we accept either, with or without _TICKERS)
def _pull_list(*names: str) -> List[str]:
    for name in names:
        v = os.getenv(name)
        if v and v.strip():
            # split by comma, strip spaces, keep order & uniques
            seen, out = set(), []
            for x in [s.strip() for s in v.split(",") if s.strip()]:
                if x.upper() not in seen:
                    seen.add(x.upper())
                    out.append(x.upper())
            return out
    return []

WATCH_CRYPTO = _pull_list("AIWATCH_CRYPTO_TICKERS","AIWATCH_CRYPTO")
WATCH_STOCKS = _pull_list("AIWATCH_STOCKS_TICKERS","AIWATCH_STOCKS")
WATCH_FOREX  = _pull_list("AIWATCH_FOREX_TICKERS","AIWATCH_FOREX")

# Optional AI candidate pools (scans prefer these first)
AI_CRYPTO_AI = _pull_list("AI_CRYPTO_AI_TICKERS")
AI_STOCKS_AI = _pull_list("AI_STOCKS_AI_TICKERS")
AI_FOREX_AI  = _pull_list("AI_FOREX_AI_TICKERS")

# Loop toggles (string '1' to enable). We also accept AI_SCAN_LOOP=1 (global) as before.
GLOBAL_LOOP_FLAG = os.getenv("AI_SCAN_LOOP", "0") == "1"
CRYPTO_LOOP_FLAG = os.getenv("AI_CRYPTO_LOOP", "0") == "1" or GLOBAL_LOOP_FLAG
STOCKS_LOOP_FLAG = os.getenv("AI_STOCKS_LOOP", "0") == "1" or GLOBAL_LOOP_FLAG
FOREX_LOOP_FLAG  = os.getenv("AI_FOREX_LOOP", "0") == "1"  or GLOBAL_LOOP_FLAG

# Randomized stagger (R+) selected
def jitter(base_minutes: int, frac: float = 0.25) -> int:
    low = max(2, int(base_minutes * (1 - frac)))
    high = int(base_minutes * (1 + frac))
    return random.randint(low, high)

BASE_MIN_CRYPTO = 25   # as agreed earlier
BASE_MIN_STOCKS = 45
BASE_MIN_FOREX  = 45

# Hybrid exits tuning
ATR_WINDOW = 14
ATR_MULT   = 1.5       # SL = ATR_MULT * ATR
TP1_PCT    = 0.8       # +0.8%
TP2_PCT    = 2.0       # +2.0%

# Per-asset fetch concurrency guard (AV free is tight)
MAX_PER_SWEEP = 3

INTENTS = discord.Intents.default()
INTENTS.message_content = True
bot = commands.Bot(command_prefix="!", intents=INTENTS)

# ========= Alpha Vantage helpers =========

AV_BASE = "https://www.alphavantage.co/query"

# Simple in-memory cache with TTL to ease rate limits
class TTLCache:
    def __init__(self, ttl_sec=120):
        self.ttl = ttl_sec
        self.data: Dict[str, Tuple[float, dict]] = {}

    def get(self, key: str) -> Optional[dict]:
        now = time.time()
        v = self.data.get(key)
        if not v: return None
        ts, payload = v
        if now - ts > self.ttl:
            self.data.pop(key, None)
            return None
        return payload

    def set(self, key: str, payload: dict):
        self.data[key] = (time.time(), payload)

cache = TTLCache(ttl_sec=90)

def _fmt_price(p: Optional[float]) -> str:
    if p is None:
        return "?"
    if p >= 1000: return f"{p:,.0f}"
    if p >= 100:  return f"{p:,.2f}"
    if p >= 1:    return f"{p:,.3f}"
    return f"{p:,.6f}"

async def av_get(session: aiohttp.ClientSession, params: Dict[str,str]) -> Optional[dict]:
    if not AV_KEY: return None
    q = dict(params)
    q["apikey"] = AV_KEY
    key = json.dumps(q, sort_keys=True)
    c = cache.get(key)
    if c: return c
    try:
        async with session.get(AV_BASE, params=q, timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status != 200: return None
            data = await r.json(content_type=None)
            # AV returns keys like "Note" when throttled
            if not isinstance(data, dict) or "Note" in data or "Error Message" in data:
                return None
            cache.set(key, data)
            return data
    except Exception:
        return None

# ---- Parsers ----

def _latest_close_from_ts(ts: dict) -> Optional[Tuple[float, List[Tuple[float,float,float]]]]:
    """
    from TIME_SERIES_DAILY_ADJUSTED or FX_DAILY: return latest close and
    OHLC list [(high, low, close)...] recent -> old for ATR calc
    """
    if not ts: return None
    # Detect which key holds the series
    key = None
    for k in ts.keys():
        if "Time Series" in k and "Daily" in k:
            key = k
            break
    if not key: return None
    series = ts.get(key)
    if not isinstance(series, dict): return None
    # sort dates desc
    dates = sorted(series.keys(), reverse=True)
    ohlc = []
    last_close = None
    for d in dates:
        row = series[d]
        # handle both FX_DAILY (4. close) and STOCKS (5. adjusted close / 4. close)
        h = float(row.get("2. high", row.get("2. High", "nan")))
        l = float(row.get("3. low", row.get("3. Low", "nan")))
        c = float(row.get("4. close", row.get("5. adjusted close", row.get("4. Close", "nan"))))
        if math.isnan(h) or math.isnan(l) or math.isnan(c):
            continue
        if last_close is None:
            last_close = c
        ohlc.append((h,l,c))
        if len(ohlc) >= ATR_WINDOW+2:
            break
    if last_close is None or len(ohlc) < 2:
        return None
    return last_close, ohlc

def _atr_from_ohlc(ohlc: List[Tuple[float,float,float]]) -> Optional[float]:
    # True Range: max( high-low, abs(high - prevClose), abs(low - prevClose) )
    trs = []
    prev_close = ohlc[0][2]
    for i in range(1, min(len(ohlc), ATR_WINDOW+1)):
        h,l,c = ohlc[i]
        tr = max(h-l, abs(h - prev_close), abs(l - prev_close))
        trs.append(tr)
        prev_close = c
    if not trs:
        return None
    return sum(trs) / len(trs)

# ---- Fetchers ----

async def fetch_stock_price(session: aiohttp.ClientSession, symbol: str) -> Optional[Tuple[float, Optional[float]]]:
    data = await av_get(session, {"function":"TIME_SERIES_DAILY_ADJUSTED","symbol":symbol})
    if not data: return None
    parsed = _latest_close_from_ts(data)
    if not parsed: return None
    last, ohlc = parsed
    atr = _atr_from_ohlc(ohlc)
    return last, atr

async def fetch_fx_price(session: aiohttp.ClientSession, pair: str) -> Optional[Tuple[float, Optional[float]]]:
    # pair like EURUSD, USDJPY, XAUUSD
    from_sym, to_sym = pair[:3], pair[3:]
    # Prefer FX_DAILY for ATR; fallback to CURRENCY_EXCHANGE_RATE (spot only, no ATR)
    data = await av_get(session, {"function":"FX_DAILY","from_symbol":from_sym,"to_symbol":to_sym,"outputsize":"compact"})
    if data:
        parsed = _latest_close_from_ts(data)
        if parsed:
            last, ohlc = parsed
            atr = _atr_from_ohlc(ohlc)
            return last, atr
    # fallback spot
    spot = await av_get(session, {"function":"CURRENCY_EXCHANGE_RATE","from_currency":from_sym,"to_currency":to_sym})
    if spot and "Realtime Currency Exchange Rate" in spot:
        rate = spot["Realtime Currency Exchange Rate"].get("5. Exchange Rate")
        if rate:
            try:
                return float(rate), None
            except:
                return None
    return None

async def fetch_crypto_price(session: aiohttp.ClientSession, symbol: str) -> Optional[Tuple[float, Optional[float]]]:
    # symbol like BTC / ETH / XRP / SOL (market USD)
    data = await av_get(session, {"function":"DIGITAL_CURRENCY_DAILY","symbol":symbol,"market":"USD"})
    if not data or "Time Series (Digital Currency Daily)" not in data:
        return None
    series = data["Time Series (Digital Currency Daily)"]
    dates = sorted(series.keys(), reverse=True)
    ohlc = []
    last_close = None
    for d in dates[:ATR_WINDOW+2]:
        row = series[d]
        h = float(row.get("2a. high (USD)", "nan"))
        l = float(row.get("3a. low (USD)", "nan"))
        c = float(row.get("4a. close (USD)", "nan"))
        if math.isnan(h) or math.isnan(l) or math.isnan(c):
            continue
        if last_close is None:
            last_close = c
        ohlc.append((h,l,c))
    if last_close is None or len(ohlc) < 2:
        return None
    atr = _atr_from_ohlc(ohlc)
    return last_close, atr

# ========= Signal logic (very simple heuristic for demo) =========

def build_hybrid_targets(entry: float, atr: Optional[float]) -> Dict[str, float]:
    # SL via ATR; if ATR missing, use 1.2% as a fallback
    sl_dist = (atr if atr and atr > 0 else entry * 0.012) * ATR_MULT
    tp1 = entry * (1 + TP1_PCT/100.0)
    tp2 = entry * (1 + TP2_PCT/100.0)
    return {"tp1": tp1, "tp2": tp2, "sl_long": entry - sl_dist, "sl_short": entry + sl_dist}

def confidence_stars(score: float) -> str:
    # 1..5 stars with half steps rounded
    n = max(1, min(5, int(round(score))))
    return "★"*n + "☆"*(5-n)

def early_vs_confirmed(score: float) -> str:
    return "Early" if score < 3.5 else "Confirmed"

def risk_badge(r: str) -> str:
    # r is "Low/Med/High"; assume Med for now
    return f"[Risk: {r}]"

async def analyze_symbol(kind: str, symbol: str, session: aiohttp.ClientSession) -> Optional[Dict]:
    """
    kind: 'crypto' | 'stock' | 'forex'
    returns dict with entry, tp1,tp2,sl,confidence,timing
    """
    if kind == "crypto":
        got = await fetch_crypto_price(session, symbol)
    elif kind == "stock":
        got = await fetch_stock_price(session, symbol)
    else:
        got = await fetch_fx_price(session, symbol)

    if not got: return None
    price, atr = got

    # toy momentum score: price relative to simple ATR band
    score = 3.0
    if atr and atr > 0:
        band = atr / max(1e-6, price)
        # lower band -> tighter -> more confident (toy)
        if band < 0.005: score = 4.2
        elif band < 0.01: score = 3.8
        elif band < 0.02: score = 3.4
        else: score = 2.8

    tg = build_hybrid_targets(price, atr)
    return {
        "symbol": symbol,
        "price": price,
        "tp1": tg["tp1"],
        "tp2": tg["tp2"],
        "sl_long": tg["sl_long"],
        "sl_short": tg["sl_short"],
        "confidence": score,
        "timing": early_vs_confirmed(score),
        "risk": "Medium"
    }

def fmt_signal_card(kind: str, s: Dict, direction: str = "LONG") -> str:
    star = confidence_stars(s["confidence"])
    return (
        f"🎯 **{s['symbol']} — {kind.upper()} — {direction}** {risk_badge(s['risk'])}\n\n"
        f"Entry: `{_fmt_price(s['price'])}`\n"
        f"TP1: `{_fmt_price(s['tp1'])}`  |  TP2: `{_fmt_price(s['tp2'])}`\n"
        f"SL: `{_fmt_price(s['sl_long'])}` (for LONG)\n"
        f"Confidence: {star} | Timing: **{s['timing']}**\n"
        f"Risk %: 2%\n"
    )

# ========= Discord utils =========

def _cid(x):
    try:
        return int(x)
    except:
        return None

async def send_to_channel(bot: commands.Bot, channel_id: str, content: str):
    cid = _cid(channel_id)
    if not cid:
        return
    ch = bot.get_channel(cid)
    if not ch:
        try:
            ch = await bot.fetch_channel(cid)
        except Exception:
            return
    try:
        await ch.send(content)
    except Exception:
        pass

# ========= Scan orchestration =========

def pick_list(primary: List[str], fallback: List[str]) -> List[str]:
    # prefer primary (AI list) if exists; else fallback
    base = primary if primary else fallback
    # sample up to MAX_PER_SWEEP with deterministic shuffle per minute slice
    if not base:
        return []
    pool = base[:]
    random.shuffle(pool)
    return pool[:MAX_PER_SWEEP]

async def run_scan(kind: str, session: aiohttp.ClientSession) -> List[str]:
    out = []
    if kind == "crypto":
        syms = pick_list(AI_CRYPTO_AI, WATCH_CRYPTO)
        chan = CHANNEL_CRYPTO_ID
    elif kind == "stock":
        syms = pick_list(AI_STOCKS_AI, WATCH_STOCKS)
        chan = CHANNEL_STOCKS_ID
    else:
        syms = pick_list(AI_FOREX_AI, WATCH_FOREX)
        chan = CHANNEL_FOREX_ID

    if not syms:
        return [f"ℹ️ [{kind}] No symbols configured."]

    for sym in syms:
        try:
            idea = await analyze_symbol(kind, sym, session)
            await asyncio.sleep(1.2)  # gentle pacing for AV
            if idea:
                card = fmt_signal_card(kind, idea, direction="LONG")
                out.append(card)
                if chan:
                    await send_to_channel(bot, chan, card)
            else:
                out.append(f"— {sym}: no data.")
        except Exception:
            out.append(f"— {sym}: error.")
    return out

# ========= Commands =========

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} ({bot.user.id})")
    # Start loops (hard-loop R+)
    if AV_KEY and any([CRYPTO_LOOP_FLAG, STOCKS_LOOP_FLAG, FOREX_LOOP_FLAG]):
        print("🧠 AI scan loops started.")
        if CRYPTO_LOOP_FLAG:
            bot.loop.create_task(loop_crypto())
        if STOCKS_LOOP_FLAG:
            bot.loop.create_task(loop_stocks())
        if FOREX_LOOP_FLAG:
            bot.loop.create_task(loop_forex())
    else:
        print("ℹ️ Loops disabled or AV key missing; use !scanonce / !scanall to test.")

@bot.command()
async def tinydebug(ctx):
    await ctx.send(
        "```json\n" + json.dumps({
            "has_av_key": bool(AV_KEY),
            "watch_crypto": WATCH_CRYPTO,
            "watch_stocks": WATCH_STOCKS,
            "watch_forex": WATCH_FOREX,
            "ai_crypto_ai": AI_CRYPTO_AI,
            "ai_stocks_ai": AI_STOCKS_AI,
            "ai_forex_ai": AI_FOREX_AI,
            "loops": {
                "crypto": CRYPTO_LOOP_FLAG,
                "stocks": STOCKS_LOOP_FLAG,
                "forex":  FOREX_LOOP_FLAG
            }
        }, indent=2) + "\n```"
    )

@bot.command()
async def price(ctx, symbol: str):
    symbol = symbol.upper().replace("-", "")  # be forgiving
    async with aiohttp.ClientSession() as session:
        # try infer by symbol
        val = None
        kind = None
        if len(symbol) in (3,4) and symbol in WATCH_CRYPTO or symbol in AI_CRYPTO_AI:
            kind = "crypto"; val = await fetch_crypto_price(session, symbol)
        if val is None and symbol in WATCH_STOCKS or symbol in AI_STOCKS_AI or symbol.isalpha():
            # stocks default if pure alpha
            try:
                val = await fetch_stock_price(session, symbol)
                if val: kind = "stock"
            except: pass
        if val is None and len(symbol) == 6:
            # possible forex like EURUSD
            try:
                val = await fetch_fx_price(session, symbol)
                if val: kind = "forex"
            except: pass
        if val is None and len(symbol) in (3,4):
            # maybe crypto
            val = await fetch_crypto_price(session, symbol)
            if val: kind = "crypto"

        if not val:
            await ctx.send(f"Couldn't fetch price for `{symbol}`.")
            return
        p, atr = val
        extra = f" | ATR≈{_fmt_price(atr)}" if atr else ""
        await ctx.send(f"**{symbol}**: `{_fmt_price(p)}`{extra}")

@bot.command()
async def scancrypto(ctx):
    async with aiohttp.ClientSession() as session:
        lines = await run_scan("crypto", session)
        await ctx.send("\n".join(lines))

@bot.command()
async def scanstocks(ctx):
    async with aiohttp.ClientSession() as session:
        lines = await run_scan("stock", session)
        await ctx.send("\n".join(lines))

@bot.command()
async def scanforex(ctx):
    async with aiohttp.ClientSession() as session:
        lines = await run_scan("forex", session)
        await ctx.send("\n".join(lines))

@bot.command()
async def scanall(ctx):
    async with aiohttp.ClientSession() as session:
        parts = []
        for k in ("crypto","stock","forex"):
            res = await run_scan(k, session)
            parts.append(f"**{k.upper()}**\n" + "\n".join(res))
        await ctx.send("\n\n".join(parts))

@bot.command()
async def aitop(ctx, kind: str = "all"):
    """
    Show top-confidence picks from last sweep attempt (on-demand compute here).
    """
    kind = kind.lower()
    kinds = ["crypto","stock","forex"] if kind == "all" else [kind]
    async with aiohttp.ClientSession() as session:
        summary = []
        for k in kinds:
            pool = pick_list(
                AI_CRYPTO_AI if k=="crypto" else AI_STOCKS_AI if k=="stock" else AI_FOREX_AI,
                WATCH_CRYPTO   if k=="crypto" else WATCH_STOCKS   if k=="stock" else WATCH_FOREX
            )
            if not pool:
                summary.append(f"**{k.upper()}**: no symbols configured.")
                continue
            scored = []
            for s in pool:
                idea = await analyze_symbol(k, s, session)
                await asyncio.sleep(1.2)
                if idea:
                    scored.append((idea["confidence"], s))
            if not scored:
                summary.append(f"**{k.upper()}**: no strong data.")
                continue
            scored.sort(reverse=True)
            top = [f"{sym} ({confidence_stars(c)})" for c, sym in scored[:5]]
            summary.append(f"**{k.upper()} TOP**: " + ", ".join(top))
        await ctx.send("\n".join(summary))

# ========= Loops (hard-loop, randomized intervals) =========

async def loop_crypto():
    # first short delay to stagger startup
    await asyncio.sleep(random.randint(5, 20))
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                await run_scan("crypto", session)
        except Exception:
            pass
        await asyncio.sleep(jitter(BASE_MIN_CRYPTO) * 60)

async def loop_stocks():
    await asyncio.sleep(random.randint(10, 35))
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                await run_scan("stock", session)
        except Exception:
            pass
        await asyncio.sleep(jitter(BASE_MIN_STOCKS) * 60)

async def loop_forex():
    await asyncio.sleep(random.randint(15, 45))
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                await run_scan("forex", session)
        except Exception:
            pass
        await asyncio.sleep(jitter(BASE_MIN_FOREX) * 60)

# ========= Startup =========

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise SystemExit("Missing DISCORD_TOKEN")
    bot.run(DISCORD_TOKEN)