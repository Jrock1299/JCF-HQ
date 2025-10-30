import os
import asyncio
import json
import logging
from typing import Optional, Tuple, List

import aiohttp
import discord
from discord.ext import commands, tasks

# ---------- Logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)8s] %(name)s: %(message)s"
)
log = logging.getLogger("ai-bot")

# ---------- Env helpers ----------
def getenv(name: str, default: Optional[str] = None) -> str:
    v = os.getenv(name, default if default is not None else "")
    return v.strip() if isinstance(v, str) else v

def get_csv(name: str) -> List[str]:
    v = getenv(name, "")
    if not v:
        return []
    return [s.strip() for s in v.split(",") if s.strip()]

# Required tokens
DISCORD_TOKEN = getenv("DISCORD_BOT_TOKEN")
FC_API_KEY = getenv("FREECRYPTO_API_KEY")
AV_API_KEY = getenv("ALPHAVANTAGE_API_KEY")

# Lists
CRYPTO_LIST = get_csv("AI_CRYPTO_AI_TICKERS")
FOREX_LIST  = get_csv("AI_FOREX_AI_TICKERS")

# Pair formatting
SYM_STYLE = getenv("FREECRYPTO_SYMBOL_STYLE", "pair").lower()  # pair|dash|slash
PAIR_QUOTE = getenv("FREECRYPTO_QUOTE", "USD").upper()
PAIR_SEP = getenv("FREECRYPTO_PAIR_SEP", "")

# FreeCrypto endpoints (templates must contain {pair} and {apikey})
DEFAULT_FC_ENDPOINTS = [
    # Adjust or override via FREECRYPTO_ENDPOINTS env if their docs differ
    "https://freecryptoapi.com/api/v1/ticker?symbol={pair}&apikey={apikey}",
    "https://freecryptoapi.com/api/v1/price?symbol={pair}&apikey={apikey}",
    "https://freecryptoapi.com/v1/price?symbol={pair}&apikey={apikey}",
]
FC_ENDPOINTS = get_csv("FREECRYPTO_ENDPOINTS") or DEFAULT_FC_ENDPOINTS

# Loops
CRYPTO_LOOP_ON = getenv("AI_CRYPTO_LOOP", "0") in ("1", "true", "True")
FOREX_LOOP_ON  = getenv("AI_FOREX_LOOP",  "0") in ("1", "true", "True")
CRYPTO_EVERY_MIN = int(getenv("AI_CRYPTO_INTERVAL_MIN", "25"))
FOREX_EVERY_MIN  = int(getenv("AI_FOREX_INTERVAL_MIN", "45"))

# Channels
CHAN_CRYPTO = int(getenv("DISCORD_CHANNEL_CRYPTO", "0") or 0)
CHAN_FOREX  = int(getenv("DISCORD_CHANNEL_FOREX",  "0") or 0)

# Backoffs
FC_BACKOFF_BASE = 2
FC_BACKOFF_MAXS = 32
AV_BACKOFF_SEC  = 15

# ---------- Discord intents / bot ----------
intents = discord.Intents.default()
# If you enabled Message Content Intent in the Discord Developer Portal,
# this will allow reading the content for prefix commands:
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Keep one aiohttp session
_http_session: Optional[aiohttp.ClientSession] = None

@bot.event
async def on_ready():
    global _http_session
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
    log.info("✅ Logged in as %s (%s)", bot.user, bot.user.id if bot.user else "?")
    log.info("🧠 AI scan loops status:")
    log.info("    - Crypto loop: %s every %dm, symbols=%s", CRYPTO_LOOP_ON, CRYPTO_EVERY_MIN, CRYPTO_LIST)
    log.info("    - Forex loop:  %s every %dm, symbols=%s", FOREX_LOOP_ON,  FOREX_EVERY_MIN,  FOREX_LIST)

    if CRYPTO_LOOP_ON and CRYPTO_LIST:
        if not crypto_loop.is_running():
            crypto_loop.change_interval(minutes=CRYPTO_EVERY_MIN)
            crypto_loop.start()
    if FOREX_LOOP_ON and FOREX_LIST:
        if not forex_loop.is_running():
            forex_loop.change_interval(minutes=FOREX_EVERY_MIN)
            forex_loop.start()

@bot.event
async def on_close():
    global _http_session
    if _http_session and not _http_session.closed:
        await _http_session.close()

# ---------- Symbol tools ----------
def build_pair(base: str) -> str:
    base = base.upper()
    q = PAIR_QUOTE
    if SYM_STYLE == "pair":
        # e.g., XRPUSD  (PAIR_SEP typically "")
        return f"{base}{PAIR_SEP}{q}"
    if SYM_STYLE == "dash":
        # e.g., XRP-USD
        sep = PAIR_SEP or "-"
        return f"{base}{sep}{q}"
    if SYM_STYLE == "slash":
        # e.g., XRP/USD
        sep = PAIR_SEP or "/"
        return f"{base}{sep}{q}"
    # Fallback
    return f"{base}{q}"

def split_fx_pair(pair: str) -> Optional[Tuple[str, str]]:
    p = pair.upper().replace("/", "").replace("-", "")
    # Handle MT4/MT5 style XAUUSD etc.
    if len(p) == 6 or len(p) == 7:  # allow weirds like XAGUSD (6) or add 7 just in case
        return p[:3], p[3:]
    # If already separated like EUR/USD
    if "/" in pair:
        a, b = pair.upper().split("/", 1)
        return a, b
    if "-" in pair:
        a, b = pair.upper().split("-", 1)
        return a, b
    # If user typed e.g. "EURUSD=X" (Yahoo style), strip suffix
    if pair.endswith("=X"):
        p2 = pair[:-2].upper()
        if len(p2) == 6:
            return p2[:3], p2[3:]
    return None

# ---------- FreeCrypto API fetch ----------
async def fetch_freecrypto_price(symbol: str) -> Optional[float]:
    """
    Try several endpoint templates; accept varied JSON shapes.
    Requires FREECRYPTO_API_KEY and env-based pair formatting.
    """
    if not FC_API_KEY:
        return None
    global _http_session
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))

    pair = build_pair(symbol)
    # Try two pair styles if first fails: plain pair and dash
    pair_candidates = [pair]
    # Provide an automatic alternate format to maximize chance of success
    if PAIR_SEP != "-":
        pair_candidates.append(pair.replace(PAIR_SEP, "-") if PAIR_SEP else f"{symbol.upper()}-{PAIR_QUOTE}")
    if PAIR_SEP != "/":
        pair_candidates.append(pair.replace(PAIR_SEP, "/") if PAIR_SEP else f"{symbol.upper()}/{PAIR_QUOTE}")

    # Deduplicate while preserving order
    seen = set()
    pair_candidates = [p for p in pair_candidates if not (p in seen or seen.add(p))]

    # Exponential backoff on 429; small retries per endpoint/pair
    for cand in pair_candidates:
        for tmpl in FC_ENDPOINTS:
            url = tmpl.format(pair=cand, apikey=FC_API_KEY)
            backoff = FC_BACKOFF_BASE
            for attempt in range(5):
                try:
                    async with _http_session.get(url, headers={"Accept": "application/json"}) as r:
                        if r.status == 429:
                            log.error("[cg] bad status 429")
                            await asyncio.sleep(backoff)
                            backoff = min(backoff * 2, FC_BACKOFF_MAXS)
                            continue
                        if r.status >= 400:
                            text = await r.text()
                            log.error("[freecrypto] HTTP %s for %s -> %s", r.status, url, text[:240])
                            break  # try next template
                        data = await r.json(content_type=None)
                        # Try common shapes
                        price = (
                            data.get("price")
                            or data.get("last")
                            or data.get("rate")
                        )
                        if price is None and isinstance(data, dict):
                            # sometimes { "data": { "price": "..." } }
                            inner = data.get("data") or data.get("result") or data.get(cand) or {}
                            if isinstance(inner, dict):
                                price = inner.get("price") or inner.get("last") or inner.get("rate")
                            # arrays like [{symbol:..., price:...}]
                            if price is None and isinstance(data.get("data"), list) and data["data"]:
                                first = data["data"][0]
                                if isinstance(first, dict):
                                    price = first.get("price") or first.get("last") or first.get("rate")
                        if price is None:
                            # Try numeric in string
                            txt = json.dumps(data)[:240]
                            log.info("[crypto] %s -> could not locate price key in %s", cand, txt)
                            break
                        try:
                            return float(price)
                        except Exception:
                            # maybe price is nested string with commas
                            try:
                                return float(str(price).replace(",", ""))
                            except Exception:
                                log.info("[crypto] %s -> unparsable price %s", cand, price)
                                break
                except asyncio.TimeoutError:
                    log.error("[freecrypto] timeout for %s", url)
                except Exception as e:
                    log.error("[freecrypto] error: %s", e)
                # brief pause between attempts
                await asyncio.sleep(0.4)
    return None

# ---------- Alpha Vantage FX fetch ----------
async def fetch_fx_price(pair: str) -> Optional[float]:
    if not AV_API_KEY:
        return None
    parts = split_fx_pair(pair)
    if not parts:
        return None
    base, quote = parts
    url = (
        "https://www.alphavantage.co/query"
        f"?function=CURRENCY_EXCHANGE_RATE&from_currency={base}&to_currency={quote}&apikey={AV_API_KEY}"
    )
    global _http_session
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))

    try:
        async with _http_session.get(url, headers={"Accept": "application/json"}) as r:
            if r.status >= 400:
                log.error("[av] HTTP %s for %s", r.status, url)
                return None
            data = await r.json(content_type=None)
            key = "Realtime Currency Exchange Rate"
            if key in data and isinstance(data[key], dict):
                ex = data[key].get("5. Exchange Rate")
                if ex:
                    try:
                        return float(ex)
                    except Exception:
                        return float(str(ex).replace(",", ""))
            # Rate limited or bad; AV is strict (5 req/min). Wait and retry once.
            await asyncio.sleep(AV_BACKOFF_SEC)
            # one retry
            async with _http_session.get(url, headers={"Accept": "application/json"}) as r2:
                data2 = await r2.json(content_type=None)
                if key in data2 and isinstance(data2[key], dict):
                    ex2 = data2[key].get("5. Exchange Rate")
                    if ex2:
                        try:
                            return float(ex2)
                        except Exception:
                            return float(str(ex2).replace(",", ""))
    except Exception as e:
        log.error("[av] error: %s", e)
    return None

# ---------- Classification ----------
def is_forex_token(sym: str) -> bool:
    u = sym.upper()
    if u in (s.upper() for s in FOREX_LIST):
        return True
    # heuristics
    if len(u.replace("=X", "").replace("/", "").replace("-", "")) in (6, 7):
        return True
    return False

# ---------- Commands ----------
@bot.command(name="ping")
async def ping(ctx: commands.Context):
    await ctx.reply("pong")

@bot.command(name="price")
async def price(ctx: commands.Context, symbol: str):
    symbol = symbol.strip().upper()
    price_val: Optional[float] = None
    src = ""
    if is_forex_token(symbol):
        price_val = await fetch_fx_price(symbol)
        src = "AlphaVantage FX"
    else:
        price_val = await fetch_freecrypto_price(symbol)
        src = "FreeCryptoAPI"
    if price_val is None:
        await ctx.reply(f"Couldn’t fetch a price for `{symbol}`.")
    else:
        await ctx.reply(f"`{symbol}` price: **{price_val:,.6f}**  _(via {src})_")

@bot.command(name="scancrypto")
async def scancrypto(ctx: commands.Context):
    if not CRYPTO_LIST:
        await ctx.reply("No crypto symbols configured.")
        return
    lines = []
    for sym in CRYPTO_LIST:
        px = await fetch_freecrypto_price(sym)
        if px is None:
            lines.append(f"• {sym}: _no data_")
        else:
            lines.append(f"• {sym}: **{px:,.6f}**")
        await asyncio.sleep(0.15)
    msg = "__Crypto scan__\n" + "\n".join(lines)
    await ctx.reply(msg)

@bot.command(name="scanforex")
async def scanforex(ctx: commands.Context):
    if not FOREX_LIST:
        await ctx.reply("No forex symbols configured.")
        return
    lines = []
    for pair in FOREX_LIST:
        px = await fetch_fx_price(pair)
        if px is None:
            lines.append(f"• {pair}: _no data_")
        else:
            lines.append(f"• {pair}: **{px:,.6f}**")
        await asyncio.sleep(0.15)
    msg = "__Forex scan__\n" + "\n".join(lines)
    await ctx.reply(msg)

@bot.command(name="scanall")
async def scanall(ctx: commands.Context):
    # Run both; show whichever lists exist
    parts = []
    if CRYPTO_LIST:
        c_lines = []
        for sym in CRYPTO_LIST:
            px = await fetch_freecrypto_price(sym)
            c_lines.append(f"• {sym}: {'_no data_' if px is None else f'**{px:,.6f}**'}")
            await asyncio.sleep(0.15)
        parts.append("__Crypto__\n" + "\n".join(c_lines))
    if FOREX_LIST:
        f_lines = []
        for pair in FOREX_LIST:
            px = await fetch_fx_price(pair)
            f_lines.append(f"• {pair}: {'_no data_' if px is None else f'**{px:,.6f}**'}")
            await asyncio.sleep(0.15)
        parts.append("__Forex__\n" + "\n".join(f_lines))
    if not parts:
        await ctx.reply("No symbols configured.")
        return
    await ctx.reply("\n\n".join(parts))

# ---------- Auto loops ----------
async def post_to_channel(channel_id: int, content: str):
    if not channel_id:
        log.info("[post] channel not set; skipping message: %s", content[:120])
        return
    ch = bot.get_channel(channel_id)
    if ch is None:
        try:
            ch = await bot.fetch_channel(channel_id)
        except Exception as e:
            log.error("[post] cannot fetch channel %s: %s", channel_id, e)
            return
    try:
        await ch.send(content)
    except Exception as e:
        log.error("[post] send failed: %s", e)

@tasks.loop(minutes=25)
async def crypto_loop():
    if not CRYPTO_LIST:
        return
    lines = []
    for sym in CRYPTO_LIST:
        px = await fetch_freecrypto_price(sym)
        if px is None:
            lines.append(f"• {sym}: _no data_")
        else:
            lines.append(f"• {sym}: **{px:,.6f}**")
        await asyncio.sleep(0.1)
    content = "📈 __Crypto update__\n" + "\n".join(lines)
    await post_to_channel(CHAN_CRYPTO, content)

@tasks.loop(minutes=45)
async def forex_loop():
    if not FOREX_LIST:
        return
    lines = []
    for pair in FOREX_LIST:
        px = await fetch_fx_price(pair)
        if px is None:
            lines.append(f"• {pair}: _no data_")
        else:
            lines.append(f"• {pair}: **{px:,.6f}**")
        await asyncio.sleep(0.1)
    content = "💱 __Forex update__\n" + "\n".join(lines)
    await post_to_channel(CHAN_FOREX, content)

# ---------- Run ----------
if not DISCORD_TOKEN:
    log.error("Missing DISCORD_BOT_TOKEN")
else:
    bot.run(DISCORD_TOKEN)