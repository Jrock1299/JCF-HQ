import os
import asyncio
import time
import json
import logging
from typing import Dict, List, Optional, Tuple

# --- keep Discord from trying to load voice/audio pieces on hosts without audioop ---
os.environ["DISCORD_NO_AUDIO"] = "1"

import discord
from discord.ext import commands, tasks
import aiohttp

# ----------------------
# Logging
# ----------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)8s] %(name)s: %(message)s")
log = logging.getLogger("jcf-bot")

# ----------------------
# Environment / Config
# ----------------------
TOKEN = os.getenv("DISCORD_TOKEN", "").strip()

# Channel IDs (strings or ints are fine)
CHANNEL_CRYPTO_ID = os.getenv("CHANNEL_CRYPTO_ID", "").strip()
CHANNEL_STOCKS_ID = os.getenv("CHANNEL_STOCKS_ID", "").strip()
CHANNEL_FOREX_ID  = os.getenv("CHANNEL_FOREX_ID", "").strip()

# Alpha Vantage
AV_KEY = os.getenv("ALPHAVANTAGE_API_KEY", "").strip()

# Watchlists (CSV; spaces allowed)
def _split_csv(s: str) -> List[str]:
    if not s:
        return []
    return [x.strip().upper() for x in s.replace(";", ",").split(",") if x.strip()]

AI_WATCH_CRYPTO_TICKERS = _split_csv(os.getenv("AI_WATCH_CRYPTO_TICKERS", os.getenv("AI_WATCH_CRYPTO", "")))
AI_WATCH_STOCKS_TICKERS = _split_csv(os.getenv("AI_WATCH_STOCKS_TICKERS", os.getenv("AI_WATCH_STOCKS", "")))
AI_WATCH_FOREX_TICKERS  = _split_csv(os.getenv("AI_WATCH_FOREX_TICKERS",  os.getenv("AI_WATCH_FOREX", "")))

# Loop toggle
AI_SCAN_LOOP = os.getenv("AI_SCAN_LOOP", "0").strip() in ("1", "true", "TRUE", "yes", "YES")

# Loop cadences (minutes)
CRYPTO_LOOP_MIN = int(os.getenv("AI_CRYPTO_LOOP_MIN", "25"))
STOCKS_LOOP_MIN = int(os.getenv("AI_STOCKS_LOOP_MIN", "45"))
FOREX_LOOP_MIN  = int(os.getenv("AI_FOREX_LOOP_MIN",  "45"))

# ----------------------
# Discord setup
# ----------------------
intents = discord.Intents.default()
intents.message_content = True

# If you ever add a custom help command, leave help_command=None
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# ----------------------
# Small utils
# ----------------------
def clean_symbol(sym: str) -> str:
    """
    Normalize user-entered symbols:
    - uppercase
    - remove hyphens, slashes, spaces
    """
    return sym.upper().replace("-", "").replace("/", "").replace(" ", "")

def is_forex_pair(sym: str) -> bool:
    s = clean_symbol(sym)
    return len(s) == 6 and s.isalpha()

def forex_split(sym: str) -> Tuple[str, str]:
    s = clean_symbol(sym)
    return s[:3], s[3:]

def is_crypto_sym(sym: str) -> bool:
    # We'll treat these as crypto if they are in the configured crypto list
    s = clean_symbol(sym)
    return s in [clean_symbol(x) for x in AI_WATCH_CRYPTO_TICKERS]

# ----------------------
# Alpha Vantage helpers
# ----------------------
class AVClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session: Optional[aiohttp.ClientSession] = None
        self.lock = asyncio.Lock()
        self.last_call_ts = 0.0

    async def _ensure(self):
        if self.session is None:
            self.session = aiohttp.ClientSession()

    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None

    async def _rate_limit(self):
        # Free AV keys are very limited (5 calls/min). Space requests a bit.
        # Adjust if you have premium.
        elapsed = time.time() - self.last_call_ts
        if elapsed < 13:  # ~4-5 calls/min
            await asyncio.sleep(13 - elapsed)

    async def _get(self, params: Dict[str, str]) -> Dict:
        if not self.api_key:
            return {}
        await self._ensure()
        async with self.lock:
            await self._rate_limit()
            url = "https://www.alphavantage.co/query"
            params = dict(params)
            params["apikey"] = self.api_key
            try:
                async with self.session.get(url, params=params, timeout=30) as r:
                    self.last_call_ts = time.time()
                    txt = await r.text()
                    try:
                        data = json.loads(txt)
                    except Exception:
                        log.error("AV JSON parse failed: %s", txt[:200])
                        return {}
                    if "Note" in data:
                        log.warning("AV throttle note: %s", data["Note"])
                    if "Information" in data:
                        log.warning("AV info: %s", data["Information"])
                    return data
            except Exception as e:
                log.error("AV GET error: %s", e)
                return {}

    async def price_equity(self, symbol: str) -> Optional[Tuple[float, Optional[float]]]:
        """
        Use GLOBAL_QUOTE for equities.
        Returns (price, change_percent)
        """
        sym = clean_symbol(symbol)
        data = await self._get({"function": "GLOBAL_QUOTE", "symbol": sym})
        q = data.get("Global Quote", {})
        try:
            price = float(q.get("05. price"))
            chg_pct = q.get("10. change percent")
            chg_pct_f = float(chg_pct.replace("%", "")) if chg_pct and "%" in chg_pct else None
            return price, chg_pct_f
        except Exception:
            return None

    async def price_forex(self, pair: str) -> Optional[Tuple[float, Optional[float]]]:
        """
        Use CURRENCY_EXCHANGE_RATE for quick price.
        For % change, fallback to FX_DAILY (yesterday close vs latest).
        Returns (price, change_percent)
        """
        base, quote = forex_split(pair)
        data = await self._get({
            "function": "CURRENCY_EXCHANGE_RATE",
            "from_currency": base,
            "to_currency": quote
        })
        r = data.get("Realtime Currency Exchange Rate", {})
        try:
            price = float(r.get("5. Exchange Rate"))
        except Exception:
            return None

        # Try to get a simple pct change from FX_DAILY
        daily = await self._get({
            "function": "FX_DAILY",
            "from_symbol": base,
            "to_symbol": quote,
            "outputsize": "compact"
        })
        ts = daily.get("Time Series FX (Daily)", {})
        if not ts or len(ts) < 2:
            return (price, None)
        dates = sorted(ts.keys(), reverse=True)
        latest = float(ts[dates[0]]["4. close"])
        prev = float(ts[dates[1]]["4. close"])
        chg_pct = ((latest - prev) / prev) * 100 if prev else None
        return (price, chg_pct)

    async def price_crypto(self, symbol: str) -> Optional[Tuple[float, Optional[float]]]:
        """
        DIGITAL_CURRENCY_DAILY with market=USD
        Returns (latest_close_usd, change_percent_vs_prev_day)
        """
        sym = clean_symbol(symbol)
        data = await self._get({
            "function": "DIGITAL_CURRENCY_DAILY",
            "symbol": sym,
            "market": "USD"
        })
        ts = data.get("Time Series (Digital Currency Daily)", {})
        if not ts or len(ts) < 2:
            return None
        dates = sorted(ts.keys(), reverse=True)
        d0, d1 = dates[0], dates[1]
        try:
            p0 = float(ts[d0]["4a. close (USD)"])
            p1 = float(ts[d1]["4a. close (USD)"])
            chg_pct = ((p0 - p1) / p1) * 100 if p1 else None
            return (p0, chg_pct)
        except Exception:
            return None


av = AVClient(AV_KEY)

# ----------------------
# Discord helpers
# ----------------------
async def get_channel(ch_id: str) -> Optional[discord.TextChannel]:
    if not ch_id:
        return None
    try:
        ch = bot.get_channel(int(ch_id))
        if ch:
            return ch  # cached
        # fetch if not cached
        return await bot.fetch_channel(int(ch_id))
    except Exception as e:
        log.error("Failed to fetch channel %s: %s", ch_id, e)
        return None

def fmt_price_line(symbol: str, price: Optional[float], chg_pct: Optional[float]) -> str:
    if price is None:
        return f"• **{symbol}** — _no data_"
    if chg_pct is None:
        return f"• **{symbol}** — **{price:.4f}**"
    arrow = "🟢" if chg_pct >= 0 else "🔻"
    return f"• **{symbol}** — **{price:.4f}**  {arrow} {chg_pct:+.2f}%"

async def fetch_price_auto(sym: str) -> Tuple[str, Optional[float], Optional[float]]:
    """
    Decide which AV endpoint to use based on symbol & configured watchlists.
    Returns (normalized_symbol, price, chg_pct)
    """
    s = clean_symbol(sym)

    # If explicitly listed in crypto watchlist, treat as crypto
    if s in [clean_symbol(x) for x in AI_WATCH_CRYPTO_TICKERS]:
        data = await av.price_crypto(s)
        return (s, None, None) if not data else (s, data[0], data[1])

    # Forex if 6 letters and alpha
    if is_forex_pair(s):
        data = await av.price_forex(s)
        return (s, None, None) if not data else (s, data[0], data[1])

    # Otherwise assume equity
    data = await av.price_equity(s)
    return (s, None, None) if not data else (s, data[0], data[1])

async def scan_group(title: str, symbols: List[str]) -> str:
    """
    Fetch a short multi-line summary for a group of tickers.
    """
    if not symbols:
        return f"**{title}** — _no symbols configured_"

    lines = [f"**{title}**"]
    for sym in symbols:
        s, p, c = await fetch_price_auto(sym)
        lines.append(fmt_price_line(s, p, c))
    return "\n".join(lines)

# ----------------------
# Commands
# ----------------------
@bot.event
async def on_ready():
    log.info("✅ Logged in as %s (%s)", bot.user, bot.user.id)
    if AI_SCAN_LOOP and AV_KEY:
        log.info("🧠 AI scan loops started.")
        if AI_WATCH_CRYPTO_TICKERS and CHANNEL_CRYPTO_ID:
            crypto_loop.change_interval(minutes=CRYPTO_LOOP_MIN)
            crypto_loop.start()
            log.info("♻️ Crypto loop every %sm enabled.", CRYPTO_LOOP_MIN)
        if AI_WATCH_STOCKS_TICKERS and CHANNEL_STOCKS_ID:
            stocks_loop.change_interval(minutes=STOCKS_LOOP_MIN)
            stocks_loop.start()
            log.info("♻️ Stocks loop every %sm enabled.", STOCKS_LOOP_MIN)
        if AI_WATCH_FOREX_TICKERS and CHANNEL_FOREX_ID:
            forex_loop.change_interval(minutes=FOREX_LOOP_MIN)
            forex_loop.start()
            log.info("♻️ Forex loop every %sm enabled.", FOREX_LOOP_MIN)
    else:
        log.info("ℹ️ Loops disabled or AV key missing; use !scanonce / !price to test.")

@bot.command()
async def ping(ctx):
    await ctx.reply("Pong 🏓")

@bot.command()
async def help(ctx):
    msg = (
        "**Commands**\n"
        "• `!ping` — test the bot\n"
        "• `!price <symbol>` — get price (e.g., `!price sofi`, `!price xrp`, `!price eurusd`)\n"
        "• `!scancrypto` — summarize your crypto watchlist\n"
        "• `!scanstocks` — summarize your stocks watchlist\n"
        "• `!scanforex` — summarize your forex watchlist\n"
        "• `!scanall` — summarize all three groups\n"
        "\n"
        "_Tip: Symbols are case-insensitive. For crypto, use base coin only (e.g., `XRP`, `ETH`, `SOL`). For forex, use pairs like `EURUSD`, `USDJPY`, `XAUUSD`._"
    )
    await ctx.reply(msg)

@bot.command()
async def price(ctx, *, which: str):
    sym = clean_symbol(which)
    s, p, c = await fetch_price_auto(sym)
    await ctx.reply(fmt_price_line(s, p, c))

@bot.command()
async def scancrypto(ctx):
    text = await scan_group("Crypto Watch", AI_WATCH_CRYPTO_TICKERS)
    await ctx.reply(text)

@bot.command()
async def scanstocks(ctx):
    text = await scan_group("Stocks Watch", AI_WATCH_STOCKS_TICKERS)
    await ctx.reply(text)

@bot.command()
async def scanforex(ctx):
    text = await scan_group("Forex Watch", AI_WATCH_FOREX_TICKERS)
    await ctx.reply(text)

@bot.command()
async def scanall(ctx):
    parts = []
    parts.append(await scan_group("Crypto Watch", AI_WATCH_CRYPTO_TICKERS))
    parts.append(await scan_group("Stocks Watch", AI_WATCH_STOCKS_TICKERS))
    parts.append(await scan_group("Forex Watch", AI_WATCH_FOREX_TICKERS))
    await ctx.reply("\n\n".join(parts))

# ----------------------
# Background loops (optional)
# ----------------------
@tasks.loop(minutes=25.0)
async def crypto_loop():
    ch = await get_channel(CHANNEL_CRYPTO_ID)
    if not ch:
        return
    text = await scan_group("Crypto Watch", AI_WATCH_CRYPTO_TICKERS)
    try:
        await ch.send(text)
    except Exception as e:
        log.error("crypto_loop send failed: %s", e)

@tasks.loop(minutes=45.0)
async def stocks_loop():
    ch = await get_channel(CHANNEL_STOCKS_ID)
    if not ch:
        return
    text = await scan_group("Stocks Watch", AI_WATCH_STOCKS_TICKERS)
    try:
        await ch.send(text)
    except Exception as e:
        log.error("stocks_loop send failed: %s", e)

@tasks.loop(minutes=45.0)
async def forex_loop():
    ch = await get_channel(CHANNEL_FOREX_ID)
    if not ch:
        return
    text = await scan_group("Forex Watch", AI_WATCH_FOREX_TICKERS)
    try:
        await ch.send(text)
    except Exception as e:
        log.error("forex_loop send failed: %s", e)

# ----------------------
# Startup
# ----------------------
async def _shutdown():
    try:
        await av.close()
    except Exception:
        pass

def _validate_envs():
    if not TOKEN:
        log.error("Missing DISCORD_TOKEN")
    if not AV_KEY:
        log.warning("ALPHAVANTAGE_API_KEY is empty — price/scan commands will return 'no data'.")

try:
    _validate_envs()
    bot.run(TOKEN)
finally:
    # ensure AV session closes if bot stops
    try:
        asyncio.get_event_loop().run_until_complete(_shutdown())
    except Exception:
        pass