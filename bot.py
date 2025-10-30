import os
import re
import json
import math
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import aiohttp
import discord
from discord.ext import commands, tasks

# -------------------------
# Logging
# -------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)7s] %(name)s: %(message)s"
)
log = logging.getLogger("ai-bot")

# -------------------------
# Env & helpers
# -------------------------
TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
FREECRYPTO_KEY = os.getenv("FREECRYPTO_API_KEY", "").strip()
ALPHAVANTAGE_KEY = os.getenv("ALPHAVANTAGE_API_KEY", "").strip()

CRYPTO_LOOP_ENABLED = os.getenv("AI_CRYPTO_LOOP", "1").strip() == "1"
FOREX_LOOP_ENABLED  = os.getenv("AI_FOREX_LOOP", "1").strip() == "1"

CRYPTO_LOOP_MIN = int(os.getenv("CRYPTO_LOOP_MIN", "25"))
FOREX_LOOP_MIN  = int(os.getenv("FOREX_LOOP_MIN", "45"))

CHANNEL_CRYPTO = os.getenv("DISCORD_CHANNEL_CRYPTO", "").strip()
CHANNEL_FOREX  = os.getenv("DISCORD_CHANNEL_FOREX", "").strip()

def _parse_symbols(env_name: str, default: str = "") -> List[str]:
    raw = os.getenv(env_name, default).strip()
    if not raw:
        return []
    parts = [p.strip().upper() for p in re.split(r"[,\s]+", raw) if p.strip()]
    # de-dup preserve order
    seen, out = set(), []
    for p in parts:
        if p not in seen:
            seen.add(p); out.append(p)
    return out

CRYPTO_LIST = _parse_symbols("AI_CRYPTO_AI_TICKERS", "")
FOREX_LIST  = _parse_symbols("AI_FOREX_AI_TICKERS", "")

if not TOKEN:
    log.error("Missing DISCORD_BOT_TOKEN")

# -------------------------
# Discord intents & bot
# -------------------------
intents = discord.Intents.default()
intents.message_content = True  # needed for command text
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# Single shared aiohttp session
_session: Optional[aiohttp.ClientSession] = None

async def get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12))
    return _session

# -------------------------
# Providers
# -------------------------
class CryptoProvider:
    """Fetch crypto prices (USD) from FreeCryptoAPI."""
    BASES = [
        # Common patterns people try; we’ll attempt in order
        "https://api.freecryptoapi.com/v1/price?symbol={base}&convert=USD",
        "https://api.freecryptoapi.com/v1/quotes?symbols={base}&convert=USD",
        # fallback path-like
        "https://api.freecryptoapi.com/v1/price/{base}-USD",
    ]

    @staticmethod
    def normalize(symbol: str) -> str:
        s = symbol.upper().replace("-", "").replace("/", "")
        # If it already ends with USD, keep base = before USD
        if s.endswith("USD"):
            base = s[:-3]
        else:
            base = s
        return base

    @staticmethod
    async def get_price(symbol: str) -> Optional[float]:
        if not FREECRYPTO_KEY:
            log.error("[crypto] FREECRYPTO_API_KEY missing")
            return None
        base = CryptoProvider.normalize(symbol)
        sess = await get_session()
        headers = {
            "X-API-KEY": FREECRYPTO_KEY,
            "Accept": "application/json",
            "User-Agent": "hunxho-bot/1.0"
        }

        # Try a couple of likely endpoints
        for url_tpl in CryptoProvider.BASES:
            url = url_tpl.format(base=base)
            try:
                async with sess.get(url, headers=headers) as resp:
                    if resp.status == 429:
                        log.warning("[crypto] 429 rate limit from FreeCryptoAPI; backing off")
                        await asyncio.sleep(2.5)
                        continue
                    if resp.status >= 400:
                        txt = await resp.text()
                        log.error("[crypto] bad status %s url=%s body=%s", resp.status, url, txt[:300])
                        continue
                    data = await resp.json(content_type=None)

                    # Try to locate a price in a few likely shapes:
                    # 1) {"symbol":"XRP","price_usd":0.55}
                    if isinstance(data, dict):
                        for k in ("price", "price_usd", "usd", "PRICE_USD", "PRICE"):
                            if k in data and isinstance(data[k], (int, float, str)):
                                try:
                                    return float(data[k])
                                except:
                                    pass

                        # 2) {"data":{"XRP":{"USD":0.55}}}
                        d = data.get("data") if "data" in data else data
                        if isinstance(d, dict):
                            # Try nested dicts
                            for key in (base, base+"USD", f"{base}-USD"):
                                if key in d and isinstance(d[key], dict):
                                    inner = d[key]
                                    for k in ("USD", "usd", "price", "price_usd"):
                                        if k in inner:
                                            try:
                                                return float(inner[k])
                                            except:
                                                pass

                            # Or "quotes": {"XRP":{"USD": {... "price": 0.55}}}
                            quotes = d.get("quotes") if "quotes" in d else None
                            if isinstance(quotes, dict):
                                q = quotes.get(base)
                                if isinstance(q, dict):
                                    usd = q.get("USD")
                                    if isinstance(usd, dict) and "price" in usd:
                                        try:
                                            return float(usd["price"])
                                        except:
                                            pass

                    # 3) array of quotes
                    if isinstance(data, list) and data:
                        # look for first number-ish field
                        item = data[0]
                        if isinstance(item, dict):
                            for k in ("price", "price_usd", "USD", "usd"):
                                if k in item:
                                    try:
                                        return float(item[k])
                                    except:
                                        pass

            except asyncio.TimeoutError:
                log.error("[crypto] timeout for %s", url)
            except Exception as e:
                log.error("[crypto] exception %r for %s", e, url)

        log.info("[crypto] %s -> no data", base)
        return None


class ForexProvider:
    """Fetch FX/XAU with AlphaVantage CURRENCY_EXCHANGE_RATE."""
    @staticmethod
    def split_pair(pair: str) -> Optional[Tuple[str, str]]:
        s = pair.upper().replace("-", "").replace("/", "")
        if len(s) < 6:
            return None
        # treat XAUUSD, USDJPY, EURUSD, etc.
        if s.startswith("XAU") or s.startswith("XAG"):
            return s[:3], s[3:]
        # default 3+3
        return s[:3], s[3:]

    @staticmethod
    async def get_price(pair: str) -> Optional[float]:
        if not ALPHAVANTAGE_KEY:
            log.error("[forex] ALPHAVANTAGE_API_KEY missing")
            return None

        parts = ForexProvider.split_pair(pair)
        if not parts:
            return None
        base, quote = parts
        url = "https://www.alphavantage.co/query"
        params = {
            "function": "CURRENCY_EXCHANGE_RATE",
            "from_currency": base,
            "to_currency": quote,
            "apikey": ALPHAVANTAGE_KEY
        }
        sess = await get_session()
        try:
            async with sess.get(url, params=params) as resp:
                txt = await resp.text()
                if resp.status >= 400:
                    log.error("[forex] bad status %s body=%s", resp.status, txt[:300])
                    return None
                # AV returns a JSON with "Realtime Currency Exchange Rate"
                try:
                    data = json.loads(txt)
                except Exception:
                    log.error("[forex] non-json: %s", txt[:200])
                    return None

                if "Note" in data or "Information" in data:
                    # rate limited
                    log.warning("[forex] AV throttled: %s", (data.get("Note") or data.get("Information"))[:200])
                    await asyncio.sleep(15)
                    return None

                r = data.get("Realtime Currency Exchange Rate") or data.get("Realtime Currency Exchange Rate".lower())
                if isinstance(r, dict):
                    for k in ("5. Exchange Rate", "Exchange Rate", "EXCHANGE_RATE", "exchange_rate"):
                        if k in r:
                            try:
                                return float(r[k])
                            except:
                                pass
        except asyncio.TimeoutError:
            log.error("[forex] timeout")
        except Exception as e:
            log.error("[forex] exception %r", e)
        return None

# -------------------------
# Utility: pretty formatters
# -------------------------
def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

def fmt_price(p: float) -> str:
    if p >= 100:
        return f"{p:,.2f}"
    if p >= 1:
        return f"{p:,.4f}"
    return f"{p:.8f}"

# -------------------------
# Commands
# -------------------------
@bot.event
async def on_ready():
    log.info("✅ Logged in as %s (%s)", bot.user, bot.user.id if bot.user else "?")
    log.info("🧠 AI scan loops status:")
    log.info("    - Crypto loop: %s every %sm, symbols=%s", CRYPTO_LOOP_ENABLED, CRYPTO_LOOP_MIN, CRYPTO_LIST)
    log.info("    - Forex loop:  %s every %sm, symbols=%s", FOREX_LOOP_ENABLED, FOREX_LOOP_MIN, FOREX_LIST)

    # Start loops only once
    if CRYPTO_LOOP_ENABLED and not crypto_loop.is_running():
        crypto_loop.change_interval(minutes=CRYPTO_LOOP_MIN)
        crypto_loop.start()
    if FOREX_LOOP_ENABLED and not forex_loop.is_running():
        forex_loop.change_interval(minutes=FOREX_LOOP_MIN)
        forex_loop.start()

@bot.command(name="help")
async def help_cmd(ctx: commands.Context):
    msg = (
        "**Hunxho Bot — Commands**\n"
        "`!ping` — quick health check\n"
        "`!price <symbol>` — crypto (XRP/ETH/SOL/… or XRPUSD/XRP-USD) or forex (USDJPY/EURUSD/XAUUSD)\n"
        "`!scancrypto` — scan configured crypto list\n"
        "`!scanforex` — scan configured forex list\n"
        "`!scanall` — scan both\n"
        "\n"
        f"**Crypto list:** {', '.join(CRYPTO_LIST) if CRYPTO_LIST else '—'}\n"
        f"**Forex list:**  {', '.join(FOREX_LIST) if FOREX_LIST else '—'}"
    )
    await ctx.reply(msg)

@bot.command(name="ping")
async def ping_cmd(ctx: commands.Context):
    await ctx.reply(f"pong — {now_utc_iso()}")

@bot.command(name="price")
async def price_cmd(ctx: commands.Context, symbol: Optional[str] = None):
    if not symbol:
        await ctx.reply("Usage: `!price <symbol>` e.g. `!price XRP` or `!price USDJPY`")
        return

    s = symbol.strip().upper()
    price = None
    source = ""

    # Decide if it's forex or crypto by pattern
    is_forex = False
    s_clean = s.replace("-", "").replace("/", "")
    if len(s_clean) >= 6 and s_clean[:3].isalpha() and s_clean[3:6].isalpha():
        is_forex = True

    if is_forex:
        price = await ForexProvider.get_price(s)
        source = "AlphaVantage FX"
    else:
        price = await CryptoProvider.get_price(s)
        source = "FreeCryptoAPI"

    if price is None:
        await ctx.reply(f"Could not fetch a price for `{s}`.")
        return
    await ctx.reply(f"**{s}** = **{fmt_price(price)}**  *(via {source})*")

@bot.command(name="scancrypto")
async def scan_crypto_cmd(ctx: commands.Context):
    if not CRYPTO_LIST:
        await ctx.reply("No crypto symbols configured. Set `AI_CRYPTO_AI_TICKERS` in Railway.")
        return
    msgs = await scan_group("crypto", CRYPTO_LIST)
    if not msgs:
        await ctx.reply("No crypto data found (rate limit or provider down).")
        return
    await send_batched(ctx, msgs)

@bot.command(name="scanforex")
async def scan_forex_cmd(ctx: commands.Context):
    if not FOREX_LIST:
        await ctx.reply("No forex symbols configured. Set `AI_FOREX_AI_TICKERS` in Railway.")
        return
    msgs = await scan_group("forex", FOREX_LIST)
    if not msgs:
        await ctx.reply("No forex data found (rate limit or provider down).")
        return
    await send_batched(ctx, msgs)

@bot.command(name="scanall")
async def scan_all_cmd(ctx: commands.Context):
    msgs: List[str] = []
    if CRYPTO_LIST:
        msgs += await scan_group("crypto", CRYPTO_LIST)
    if FOREX_LIST:
        msgs += await scan_group("forex", FOREX_LIST)

    if not msgs:
        await ctx.reply("No data found (rate limit or providers down).")
        return
    await send_batched(ctx, msgs)

async def send_batched(ctx_or_channel, lines: List[str], batch: int = 12):
    for i in range(0, len(lines), batch):
        chunk = lines[i:i+batch]
        text = "\n".join(chunk)
        if isinstance(ctx_or_channel, commands.Context):
            await ctx_or_channel.reply(text)
        else:
            await ctx_or_channel.send(text)
        await asyncio.sleep(0.6)

# -------------------------
# Scanning logic (lightweight)
# -------------------------
async def scan_group(kind: str, symbols: List[str]) -> List[str]:
    msgs: List[str] = []
    # Simple per-provider pacing to avoid burst 429s
    for s in symbols:
        if kind == "crypto":
            p = await CryptoProvider.get_price(s)
            src = "CG"  # label short (we swapped, but keep short tag)
            if p is not None:
                msgs.append(f"🟢 **{s}** = **{fmt_price(p)}**  *(crypto)*")
            else:
                msgs.append(f"⚪ **{s}** — no data *(crypto)*")
            await asyncio.sleep(0.3)  # small pause between calls

        elif kind == "forex":
            p = await ForexProvider.get_price(s)
            if p is not None:
                msgs.append(f"🔵 **{s}** = **{fmt_price(p)}**  *(forex)*")
            else:
                msgs.append(f"⚪ **{s}** — no data *(forex)*")
            await asyncio.sleep(1.5)  # AV is stricter; go slower
    return msgs

# -------------------------
# Loops (post to fixed channels if provided, else do nothing until commands used)
# -------------------------
@tasks.loop(minutes=CRYPTO_LOOP_MIN)
async def crypto_loop():
    if not CRYPTO_LIST or not CRYPTO_LOOP_ENABLED:
        return
    channel = None
    if CHANNEL_CRYPTO:
        try:
            channel = await bot.fetch_channel(int(CHANNEL_CRYPTO))
        except Exception:
            log.warning("crypto_loop: could not fetch channel %s", CHANNEL_CRYPTO)
    if not channel:
        # No fixed channel; skip auto-posting
        return

    msgs = await scan_group("crypto", CRYPTO_LIST)
    if msgs:
        await send_batched(channel, [f"**📡 Crypto scan — {now_utc_iso()}**"] + msgs)

@tasks.loop(minutes=FOREX_LOOP_MIN)
async def forex_loop():
    if not FOREX_LIST or not FOREX_LOOP_ENABLED:
        return
    channel = None
    if CHANNEL_FOREX:
        try:
            channel = await bot.fetch_channel(int(CHANNEL_FOREX))
        except Exception:
            log.warning("forex_loop: could not fetch channel %s", CHANNEL_FOREX)
    if not channel:
        return

    msgs = await scan_group("forex", FOREX_LIST)
    if msgs:
        await send_batched(channel, [f"**📡 Forex scan — {now_utc_iso()}**"] + msgs)

# -------------------------
# Graceful shutdown
# -------------------------
async def _close_session():
    global _session
    try:
        if _session and not _session.closed:
            await _session.close()
    except Exception:
        pass

def main():
    if not TOKEN:
        log.error("Missing DISCORD_BOT_TOKEN")
        return
    try:
        bot.run(TOKEN)
    finally:
        try:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(_close_session())
        except Exception:
            pass

if __name__ == "__main__":
    log.info("🚀 Starting bot...")
    main()