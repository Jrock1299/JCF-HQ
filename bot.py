import os
import asyncio
import math
from datetime import datetime, timezone
import json
import re

# Force Discord.py to not load voice / audio stack
os.environ["DISCORD_NO_AUDIO"] = "1"

import aiohttp
import discord
from discord.ext import commands, tasks

# ---------------------------
# Config & defaults
# ---------------------------
TOKEN = os.getenv("DISCORD_TOKEN", "")
AV_KEY = os.getenv("ALPHAVANTAGE_API_KEY", "")

CHANNEL_CRYPTO_ID = int(os.getenv("CHANNEL_CRYPTO_ID", "0") or 0)
CHANNEL_STOCKS_ID = int(os.getenv("CHANNEL_STOCKS_ID", "0") or 0)
CHANNEL_FOREX_ID  = int(os.getenv("CHANNEL_FOREX_ID",  "0") or 0)

WATCH_CRYPTO = [s.strip().upper() for s in os.getenv("AI_WATCH_CRYPTO", "ETHUSD,XRPUSD,SOLUSD").split(",") if s.strip()]
WATCH_STOCKS = [s.strip().upper() for s in os.getenv("AI_WATCH_STOCKS", "SOFI,AFRM").split(",") if s.strip()]
WATCH_FOREX  = [s.strip().upper() for s in os.getenv("AI_WATCH_FOREX",  "XAUUSD,EURUSD,USDJPY").split(",") if s.strip()]

SCAN_LOOPS = os.getenv("AI_SCAN_LOOP", "0") == "1"

CRYPTO_LOOP_MIN = int(os.getenv("CRYPTO_LOOP_MIN", "25"))
STOCKS_LOOP_MIN = int(os.getenv("STOCKS_LOOP_MIN", "45"))
FOREX_LOOP_MIN  = int(os.getenv("FOREX_LOOP_MIN",  "45"))

# Discord intents
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command("help")  # avoid collision with default help

# ---------------------------
# Helpers: symbol parsing
# ---------------------------

def split_fx_pair(pair: str):
    """EURUSD -> EUR, USD (also handles XAUUSD, etc.)"""
    pair = pair.upper().replace("=", "")
    if len(pair) == 6:
        return pair[:3], pair[3:]
    # fallback: try regex (e.g., 'USDJPY')
    m = re.fullmatch(r"([A-Z]{3})([A-Z]{3})", pair)
    if m:
        return m.group(1), m.group(2)
    # As last resort, assume XXXUSD
    return pair[:3], "USD"

def split_crypto_pair(symbol: str):
    """ETHUSD -> (ETH, USD)"""
    symbol = symbol.upper().replace("-", "")
    if symbol.endswith("USDT"):
        return symbol[:-4], "USDT"
    if symbol.endswith("USD"):
        return symbol[:-3], "USD"
    # default USD
    return symbol, "USD"

# ---------------------------
# Alpha Vantage fetchers (rate-limit friendly)
# ---------------------------

class AlphaClient:
    BASE = "https://www.alphavantage.co/query"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def _get(self, session: aiohttp.ClientSession, params: dict):
        params["apikey"] = self.api_key
        for attempt in range(3):
            try:
                async with session.get(self.BASE, params=params, timeout=30) as r:
                    text = await r.text()
                    # Handle empty or non-JSON
                    if not text or text.strip() == "":
                        await asyncio.sleep(2 * (attempt + 1))
                        continue
                    data = json.loads(text)
                    # AV throttle message
                    if "Note" in data or "Information" in data:
                        await asyncio.sleep(12)  # back off
                        continue
                    return data
            except Exception:
                await asyncio.sleep(2 * (attempt + 1))
        return None

    async def daily_stock(self, session, symbol: str):
        # TIME_SERIES_DAILY_ADJUSTED gives us OHLC + adjusted close
        params = {"function": "TIME_SERIES_DAILY_ADJUSTED", "symbol": symbol}
        return await self._get(session, params)

    async def fx_daily(self, session, from_sym: str, to_sym: str):
        params = {"function": "FX_DAILY", "from_symbol": from_sym, "to_symbol": to_sym, "outputsize": "compact"}
        return await self._get(session, params)

    async def fx_rate(self, session, from_sym: str, to_sym: str):
        params = {"function": "CURRENCY_EXCHANGE_RATE", "from_currency": from_sym, "to_currency": to_sym}
        return await self._get(session, params)

    async def crypto_daily(self, session, base: str, quote: str):
        # DIGITAL_CURRENCY_DAILY requires symbol (e.g., ETH) and market (e.g., USD/USDT)
        params = {"function": "DIGITAL_CURRENCY_DAILY", "symbol": base, "market": quote}
        return await self._get(session, params)

av = AlphaClient(AV_KEY) if AV_KEY else None

# ---------------------------
# Light TA utilities (SMA, RSI)
# ---------------------------

def sma(values, n):
    if len(values) < n: return None
    return sum(values[-n:]) / n

def rsi(values, n=14):
    # Classic Wilder's RSI
    if len(values) <= n: return None
    gains, losses = [], []
    for i in range(1, len(values)):
        ch = values[i] - values[i-1]
        gains.append(max(ch, 0.0))
        losses.append(abs(min(ch, 0.0)))
    avg_gain = sum(gains[:n]) / n
    avg_loss = sum(losses[:n]) / n
    if avg_loss == 0: return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1 + rs))

def pct(a, b):
    if b == 0: return 0.0
    return (a - b) / b * 100.0

# ---------------------------
# Parsing AV payloads to close series
# ---------------------------

def parse_daily_closes(data: dict, kind: str, quote: str = "USD"):
    """
    kind: 'stock', 'fx', 'crypto'
    returns (dates_sorted, closes_sorted_recent_first_list)
    """
    if not data or not isinstance(data, dict):
        return [], []

    if kind == "stock":
        key = "Time Series (Daily)"
        if key not in data: return [], []
        series = data[key]
        items = sorted(series.items())  # ascending by date
        dates = [datetime.fromisoformat(d) for d, _ in items]
        closes = [float(v.get("4. close") or v.get("5. adjusted close") or v.get("4. close", 0.0)) for _, v in items]
        return dates, closes

    if kind == "fx":
        key = "Time Series FX (Daily)"
        if key not in data: return [], []
        series = data[key]
        items = sorted(series.items())
        dates = [datetime.fromisoformat(d) for d, _ in items]
        closes = [float(v.get("4. close", 0.0)) for _, v in items]
        return dates, closes

    if kind == "crypto":
        # DIGITAL_CURRENCY_DAILY uses keys like '4a. close (USD)' and '4b. close (USD)'
        # We'll try '4a. close (QUOTE)'
        # Fallback to any close if needed.
        key = "Time Series (Digital Currency Daily)"
        if key not in data: return [], []
        series = data[key]
        items = sorted(series.items())
        dates = [datetime.fromisoformat(d) for d, _ in items]
        close_key = f"4a. close ({quote})"
        closes = []
        for _, v in items:
            if close_key in v:
                closes.append(float(v[close_key]))
            else:
                # try to find any close key
                ck = next((vv for kk, vv in v.items() if kk.startswith("4a. close")), None)
                closes.append(float(ck) if ck else 0.0)
        return dates, closes

    return [], []

# ---------------------------
# Signal logic (simple + clear)
# ---------------------------

def build_signal(symbol: str, closes: list):
    """
    Returns dict with basic signal info or None if not actionable.
    Rules:
      - Need at least 50 candles
      - Compute SMA20, SMA50, RSI14
      - Actionable if:
          * Bullish: SMA20 > SMA50 and RSI between 45-70
          * Bearish: SMA20 < SMA50 and RSI between 30-55
      - Confidence A/B/C based on slope & distance of SMAs
      - Early vs Confirmed: if cross happened in last 3 bars -> Early else Confirmed
    """
    if len(closes) < 50:
        return None

    sma20 = sma(closes, 20)
    sma50 = sma(closes, 50)
    rsi14 = rsi(closes, 14)

    if sma20 is None or sma50 is None or rsi14 is None:
        return None

    bias = "NEUTRAL"
    if sma20 > sma50 and 45 <= rsi14 <= 70:
        bias = "BULLISH"
    elif sma20 < sma50 and 30 <= rsi14 <= 55:
        bias = "BEARISH"
    else:
        return None

    # Cross check: did 20/50 cross recently?
    recent_sma20 = sma(closes[:-1], 20)
    recent_sma50 = sma(closes[:-1], 50)
    crossed_recently = False
    if recent_sma20 and recent_sma50:
        # crude: if sign changed between (sma20 - sma50) from previous to now
        prev_diff = (recent_sma20 - recent_sma50)
        now_diff = (sma20 - sma50)
        if (prev_diff <= 0 < now_diff) or (prev_diff >= 0 > now_diff):
            crossed_recently = True

    timing = "Early" if crossed_recently else "Confirmed"

    # Confidence
    dist = abs((sma20 - sma50) / sma50) * 100.0 if sma50 else 0.0
    if dist >= 1.0:
        conf = "A"
    elif dist >= 0.4:
        conf = "B"
    else:
        conf = "C"

    # Pct changes as context
    last = closes[-1]
    prev = closes[-2] if len(closes) > 1 else last
    pct1d = pct(last, prev)
    pct5d = pct(last, closes[-6]) if len(closes) > 6 else 0.0

    return {
        "symbol": symbol,
        "bias": bias,
        "timing": timing,
        "confidence": conf,
        "sma20": sma20,
        "sma50": sma50,
        "rsi14": rsi14,
        "last": last,
        "pct1d": pct1d,
        "pct5d": pct5d,
    }

def format_signal_embed(kind: str, info: dict) -> discord.Embed:
    title = f"{kind.upper()} setup · {info['symbol']}"
    color = 0x2ecc71 if info["bias"] == "BULLISH" else 0xe74c3c
    e = discord.Embed(title=title, color=color, timestamp=datetime.now(timezone.utc))
    e.add_field(name="Bias", value=f"{info['bias']} ({info['timing']})", inline=True)
    e.add_field(name="Confidence", value=info["confidence"], inline=True)
    e.add_field(name="RSI(14)", value=f"{info['rsi14']:.1f}", inline=True)
    e.add_field(name="Last", value=f"{info['last']:.4f}", inline=True)
    e.add_field(name="SMA20", value=f"{info['sma20']:.4f}", inline=True)
    e.add_field(name="SMA50", value=f"{info['sma50']:.4f}", inline=True)
    e.add_field(name="Change", value=f"1d {info['pct1d']:.2f}% · 5d {info['pct5d']:.2f}%", inline=False)
    e.set_footer(text="JCFWatchBot · AI Scan")
    return e

# ---------------------------
# Scanners
# ---------------------------

async def scan_crypto(session, channel: discord.TextChannel):
    results = []
    for sym in WATCH_CRYPTO:
        base, quote = split_crypto_pair(sym)
        data = await av.crypto_daily(session, base, quote) if av else None
        dates, closes = parse_daily_closes(data, "crypto", quote=quote)
        if not closes:
            print(f"[scan:crypto] {sym} -> no data (AV empty).")
            continue
        sig = build_signal(f"{base}{quote}", closes)
        if sig: results.append(sig)

    if not results:
        await channel.send("🧪 **Crypto scan:** no strong signals.")
        return

    for sig in results:
        await channel.send(embed=format_signal_embed("crypto", sig))

async def scan_stocks(session, channel: discord.TextChannel):
    results = []
    for sym in WATCH_STOCKS:
        data = await av.daily_stock(session, sym) if av else None
        dates, closes = parse_daily_closes(data, "stock")
        if not closes:
            print(f"[scan:stocks] {sym} -> no data (AV empty).")
            continue
        sig = build_signal(sym, closes)
        if sig: results.append(sig)

    if not results:
        await channel.send("🧪 **Stocks scan:** no strong signals.")
        return

    for sig in results:
        await channel.send(embed=format_signal_embed("stocks", sig))

async def scan_forex(session, channel: discord.TextChannel):
    results = []
    for pair in WATCH_FOREX:
        base, quote = split_fx_pair(pair)
        data = await av.fx_daily(session, base, quote) if av else None
        # If no history (e.g., metals sometimes), try just a spot rate
        dates, closes = parse_daily_closes(data, "fx")
        if not closes:
            rate = await av.fx_rate(session, base, quote) if av else None
            try:
                r = float(rate["Realtime Currency Exchange Rate"]["5. Exchange Rate"])
                closes = [r] * 60  # fake sequence for TA (flat)
            except Exception:
                print(f"[scan:forex] {pair} -> no data (AV empty).")
                continue

        sig = build_signal(f"{base}{quote}", closes)
        if sig: results.append(sig)

    if not results:
        await channel.send("🧪 **Forex scan:** no strong signals.")
        return

    for sig in results:
        await channel.send(embed=format_signal_embed("forex", sig))

# ---------------------------
# Commands
# ---------------------------

@bot.command()
async def help(ctx):
    await ctx.reply(
        "**Commands**\n"
        "`!ping` — check bot\n"
        "`!price <ticker>` — quick price via Alpha Vantage (e.g., !price SOFI, !price ETHUSD, !price EURUSD)\n"
        "`!scanonce [crypto|stocks|forex|all]` — run a one-off AI scan\n"
    )

@bot.command()
async def ping(ctx):
    await ctx.reply("Pong 🏓")

@bot.command()
async def price(ctx, ticker: str):
    """Get a quick latest price using AV."""
    if not AV_KEY:
        await ctx.reply("Alpha Vantage key not configured.")
        return

    t = ticker.strip().upper()
    async with aiohttp.ClientSession() as session:
        price_value = None
        label = t

        # Guess asset class
        if re.fullmatch(r"[A-Z]{3}[A-Z]{3}", t):  # FX like EURUSD, XAUUSD
            f, to = split_fx_pair(t)
            data = await av.fx_rate(session, f, to)
            try:
                price_value = float(data["Realtime Currency Exchange Rate"]["5. Exchange Rate"])
            except Exception:
                price_value = None

        elif re.fullmatch(r"[A-Z]{2,5}", t):  # Likely stock
            d = await av.daily_stock(session, t)
            dates, closes = parse_daily_closes(d, "stock")
            if closes: price_value = closes[-1]

        else:  # try crypto (ETHUSD etc.)
            base, quote = split_crypto_pair(t)
            d = await av.crypto_daily(session, base, quote)
            dates, closes = parse_daily_closes(d, "crypto", quote=quote)
            if closes:
                price_value = closes[-1]
                label = f"{base}{quote}"

        if price_value is None:
            await ctx.reply(f"Couldn't fetch price for `{ticker}`.")
        else:
            await ctx.reply(f"`{label}` → **{price_value:.6f}**")

@bot.command()
async def scanonce(ctx, which: str = "all"):
    """Run a one-off scan."""
    which = which.lower()
    if not AV_KEY:
        await ctx.reply("Alpha Vantage key not configured.")
        return

    async with aiohttp.ClientSession() as session:
        if which in ("crypto", "all"):
            ch = ctx.channel if CHANNEL_CRYPTO_ID == 0 else bot.get_channel(CHANNEL_CRYPTO_ID)
            if ch:
                await scan_crypto(session, ch)
        if which in ("stocks", "equities", "all"):
            ch = ctx.channel if CHANNEL_STOCKS_ID == 0 else bot.get_channel(CHANNEL_STOCKS_ID)
            if ch:
                await scan_stocks(session, ch)
        if which in ("forex", "fx", "all"):
            ch = ctx.channel if CHANNEL_FOREX_ID == 0 else bot.get_channel(CHANNEL_FOREX_ID)
            if ch:
                await scan_forex(session, ch)

# ---------------------------
# Background loops
# ---------------------------

@tasks.loop(minutes=CRYPTO_LOOP_MIN)
async def crypto_loop():
    if not SCAN_LOOPS or not AV_KEY or CHANNEL_CRYPTO_ID == 0:
        return
    ch = bot.get_channel(CHANNEL_CRYPTO_ID)
    if not ch:
        return
    async with aiohttp.ClientSession() as session:
        await scan_crypto(session, ch)

@tasks.loop(minutes=STOCKS_LOOP_MIN)
async def stocks_loop():
    if not SCAN_LOOPS or not AV_KEY or CHANNEL_STOCKS_ID == 0:
        return
    ch = bot.get_channel(CHANNEL_STOCKS_ID)
    if not ch:
        return
    async with aiohttp.ClientSession() as session:
        await scan_stocks(session, ch)

@tasks.loop(minutes=FOREX_LOOP_MIN)
async def forex_loop():
    if not SCAN_LOOPS or not AV_KEY or CHANNEL_FOREX_ID == 0:
        return
    ch = bot.get_channel(CHANNEL_FOREX_ID)
    if not ch:
        return
    async with aiohttp.ClientSession() as session:
        await scan_forex(session, ch)

# ---------------------------
# Events
# ---------------------------

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} ({bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="JCFWatchBot · AI scans"))
    # Start loops if enabled
    if SCAN_LOOPS and AV_KEY:
        crypto_loop.change_interval(minutes=CRYPTO_LOOP_MIN)
        stocks_loop.change_interval(minutes=STOCKS_LOOP_MIN)
        forex_loop.change_interval(minutes=FOREX_LOOP_MIN)
        crypto_loop.start()
        stocks_loop.start()
        forex_loop.start()
        print("🧠 AI scan loops started.")
        if CHANNEL_CRYPTO_ID == 0:
            print("⚠️ No CHANNEL_CRYPTO_ID set; crypto loop will skip.")
        if CHANNEL_STOCKS_ID == 0:
            print("⚠️ No CHANNEL_STOCKS_ID set; stocks loop will skip.")
        if CHANNEL_FOREX_ID == 0:
            print("⚠️ No CHANNEL_FOREX_ID set; forex loop will skip.")
    else:
        print("ℹ️ Loops disabled or AV key missing; use !scanonce to test.")

# ---------------------------
# Boot
# ---------------------------

if not TOKEN:
    raise SystemExit("DISCORD_TOKEN is not set.")
bot.run(TOKEN)