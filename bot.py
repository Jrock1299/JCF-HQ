# bot.py
# JCFWatchBot — Alpha Vantage powered scanner
# Python 3.11 / discord.py 2.4.x

import os
import re
import asyncio
import logging
from typing import Optional, Tuple, Dict, List

import aiohttp
import discord
from discord.ext import commands, tasks

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)7s] %(name)s: %(message)s')
log = logging.getLogger("jcfwatch")

# ---------- ENV ----------
DISCORD_TOKEN           = os.getenv("DISCORD_TOKEN", "").strip()
ANNOUNCE_CHANNEL_ID     = int(os.getenv("ANNOUNCE_CHANNEL_ID", "0") or "0")

# Channel targets for auto posts (optional but recommended)
CHANNEL_CRYPTO_ID       = int(os.getenv("CHANNEL_CRYPTO_ID", "0") or "0")
CHANNEL_STOCKS_ID       = int(os.getenv("CHANNEL_STOCKS_ID", "0") or "0")
CHANNEL_FOREX_ID        = int(os.getenv("CHANNEL_FOREX_ID", "0") or "0")

# Watchlists: comma-separated strings (case-insensitive; dashes/spaces are OK)
AI_WATCH_CRYPTO_TICKERS = os.getenv("AI_WATCH_CRYPTO_TICKERS", "")
AI_WATCH_STOCKS_TICKERS = os.getenv("AI_WATCH_STOCKS_TICKERS", "")
AI_WATCH_FOREX_TICKERS  = os.getenv("AI_WATCH_FOREX_TICKERS", "")

# Alpha Vantage API key
AV_API_KEY              = os.getenv("ALPHAVANTAGE_API_KEY", "").strip()

# Enable background loops? "1" to enable
AI_SCAN_LOOP            = os.getenv("AI_SCAN_LOOP", "0").strip() == "1"

# ---------- Helpers ----------
def clean_symbol(symbol: str) -> str:
    """Uppercase, strip spaces, remove common separators."""
    s = symbol.upper().strip()
    s = s.replace("-", "").replace("_", "").replace("/", "")
    return s

def split_csv_symbols(raw: str) -> List[str]:
    if not raw:
        return []
    out: List[str] = []
    for part in raw.split(","):
        p = clean_symbol(part)
        if p:
            out.append(p)
    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for s in out:
        if s not in seen:
            seen.add(s)
            deduped.append(s)
    return deduped

WATCH_CRYPTO = split_csv_symbols(AI_WATCH_CRYPTO_TICKERS)  # e.g. ["XRPUSD","ETHUSD","SOLUSD"]
WATCH_STOCKS = split_csv_symbols(AI_WATCH_STOCKS_TICKERS)  # e.g. ["SOFI","AFRM"]
WATCH_FOREX  = split_csv_symbols(AI_WATCH_FOREX_TICKERS)   # e.g. ["USDJPY","EURUSD","XAUUSD"]

def looks_like_forex_pair(sym: str) -> bool:
    # 6 letters (e.g., EURUSD, USDJPY, XAUUSD, XAGUSD, USDCAD)
    return bool(re.fullmatch(r"[A-Z]{6}", sym))

def looks_like_crypto(sym: str) -> bool:
    # Heuristic: ends with USD/USDT and is not in pure 6-letter (forex) if len != 6
    return sym.endswith("USD") or sym.endswith("USDT")

# ---------- Alpha Vantage Client ----------
class AVClient:
    BASE = "https://www.alphavantage.co/query"

    def __init__(self, api_key: str, session: Optional[aiohttp.ClientSession] = None):
        self.api_key = api_key
        self.session = session or aiohttp.ClientSession()

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def _get(self, params: Dict) -> Dict:
        params = {**params, "apikey": self.api_key}
        try:
            async with self.session.get(self.BASE, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)
                # Alpha Vantage error messages
                if isinstance(data, dict):
                    if "Note" in data:
                        log.warning("AV note (throttle/usage): %s", data["Note"])
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

    async def price_fx(self, pair: str) -> Optional[float]:
        """
        6-letter pair like EURUSD, USDJPY, XAUUSD -> uses CURRENCY_EXCHANGE_RATE
        """
        p = clean_symbol(pair)
        if not looks_like_forex_pair(p):
            return None
        from_cur = p[0:3]
        to_cur   = p[3:6]
        data = await self._get({"function": "CURRENCY_EXCHANGE_RATE", "from_currency": from_cur, "to_currency": to_cur})
        q = data.get("Realtime Currency Exchange Rate", {})
        try:
            rate = float(q.get("5. Exchange Rate"))
            return rate
        except Exception:
            return None

    async def price_crypto(self, symbol: str) -> Optional[float]:
        """
        Crypto vs USD/USDT using CURRENCY_EXCHANGE_RATE (works for most majors).
        Examples: XRPUSD, ETHUSD, SOLUSD
        """
        s = clean_symbol(symbol)
        if s.endswith("USDT"):
            base, quote = s[:-4], "USDT"
        elif s.endswith("USD"):
            base, quote = s[:-3], "USD"
        else:
            # Try defaulting to USD if they passed plain base like "BTC"
            base, quote = s, "USD"

        data = await self._get({"function": "CURRENCY_EXCHANGE_RATE", "from_currency": base, "to_currency": quote})
        q = data.get("Realtime Currency Exchange Rate", {})
        try:
            rate = float(q.get("5. Exchange Rate"))
            return rate
        except Exception:
            return None

# ---------- Discord Bot ----------
intents = discord.Intents.default()
intents.message_content = True

# Disable default help to avoid CommandRegistrationError
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# Shared AV client
av: Optional[AVClient] = None

# ---------- Startup / Shutdown ----------
@bot.event
async def on_ready():
    global av
    if av is None:
        av = AVClient(AV_API_KEY) if AV_API_KEY else None

    me = bot.user
    log.info("✅ Logged in as %s (%s)", me, me.id if me else "?")

    # Announce (optional)
    if ANNOUNCE_CHANNEL_ID:
        ch = bot.get_channel(ANNOUNCE_CHANNEL_ID)
        if ch:
            try:
                await ch.send("✅ **JCFWatchBot ONLINE** — Systems initialized. Monitoring markets...")
            except Exception as e:
                log.warning("Announce failed: %s", e)

    # Start loops if enabled and key present
    if AI_SCAN_LOOP and AV_API_KEY:
        try:
            crypto_loop.start()
            stocks_loop.start()
            forex_loop.start()
            log.info("🧠 AI scan loops started.")
        except RuntimeError:
            # already running
            pass
    else:
        log.info("ℹ️ Loops disabled or AV key missing; use !scanonce/!scanall to test.")

@bot.event
async def on_close():
    if av:
        await av.close()

# ---------- Commands ----------
@bot.command(name="helpme")
async def helpme(ctx: commands.Context):
    """Show commands (custom help)."""
    txt = (
        "**Commands**\n"
        "`!ping` — pong check\n"
        "`!helpme` — this help\n"
        "`!price <symbol>` — live price (use symbols like XRPUSD, ETHUSD, SOLUSD, SOFI, AFRM, EURUSD, USDJPY, XAUUSD)\n"
        "`!scancrypto` / `!scanstocks` / `!scanforex` — scan current watchlists\n"
        "`!scanall` — scan all watchlists\n"
        "`!scanonce` — same as !scanall but compact output\n"
    )
    await ctx.reply(txt)

@bot.command()
async def ping(ctx: commands.Context):
    await ctx.reply("Pong 🏓")

@bot.command()
async def price(ctx: commands.Context, symbol: str):
    """Fetch live price via Alpha Vantage."""
    if not AV_API_KEY:
        await ctx.reply("❌ Alpha Vantage key not configured.")
        return

    sym = clean_symbol(symbol)
    out = None
    kind = "equity"

    if looks_like_forex_pair(sym):
        rate = await av.price_fx(sym)  # type: ignore
        if rate is not None:
            out = f"**{sym}** — `{rate:,.6f}`"
            kind = "forex"
    elif looks_like_crypto(sym):
        px = await av.price_crypto(sym)  # type: ignore
        if px is not None:
            out = f"**{sym}** — `${px:,.6f}`"
            kind = "crypto"
    else:
        eq = await av.price_equity(sym)  # type: ignore
        if eq is not None:
            price, chg = eq
            delta = f" ({chg:+.2f}%)" if chg is not None else ""
            out = f"**{sym}** — `${price:,.2f}`{delta}"
            kind = "equity"

    if out:
        await ctx.reply(f"📈 {out}  *({kind})*")
    else:
        await ctx.reply(f"⚠️ Could not fetch price for **{symbol}**.")

# ---------- Scan helpers ----------
async def scan_list(kind: str, symbols: List[str]) -> List[str]:
    """
    Returns a list of formatted lines for a scan section.
    For now we report price (and % change for equities).
    """
    if not AV_API_KEY:
        return [f"{kind} — Alpha Vantage key missing."]
    if not symbols:
        return [f"{kind} — *no symbols configured*"]

    lines: List[str] = []
    for s in symbols:
        if kind == "Crypto Watch":
            px = await av.price_crypto(s)  # type: ignore
            if px is None:
                lines.append(f"• **{s}** — n/a")
            else:
                lines.append(f"• **{s}** — `${px:,.6f}`")
        elif kind == "Stocks Watch":
            r = await av.price_equity(s)  # type: ignore
            if r is None:
                lines.append(f"• **{s}** — n/a")
            else:
                price, chg = r
                delta = f" ({chg:+.2f}%)" if chg is not None else ""
                lines.append(f"• **{s}** — `${price:,.2f}`{delta}")
        elif kind == "Forex Watch":
            px = await av.price_fx(s)  # type: ignore
            if px is None:
                lines.append(f"• **{s}** — n/a")
            else:
                lines.append(f"• **{s}** — `{px:,.6f}`")
    return lines

async def build_scan_embed(title: str = "Market Scan") -> discord.Embed:
    e = discord.Embed(title=title, color=0x3AA3E3)
    # Crypto
    crypto_lines = await scan_list("Crypto Watch", WATCH_CRYPTO)
    e.add_field(name="Crypto Watch", value="\n".join(crypto_lines) or "—", inline=False)
    # Stocks
    stock_lines = await scan_list("Stocks Watch", WATCH_STOCKS)
    e.add_field(name="Stocks Watch", value="\n".join(stock_lines) or "—", inline=False)
    # Forex
    fx_lines = await scan_list("Forex Watch", WATCH_FOREX)
    e.add_field(name="Forex Watch", value="\n".join(fx_lines) or "—", inline=False)
    return e

# ---------- Scan commands ----------
@bot.command()
async def scanall(ctx: commands.Context):
    """Scan all watchlists and post an embed."""
    embed = await build_scan_embed("Market Scan — All")
    await ctx.reply(embed=embed)

@bot.command()
async def scanonce(ctx: commands.Context):
    """Quick compact scan (same as scanall, just different title)."""
    embed = await build_scan_embed("Quick Scan")
    await ctx.reply(embed=embed)

@bot.command()
async def scancrypto(ctx: commands.Context):
    lines = await scan_list("Crypto Watch", WATCH_CRYPTO)
    await ctx.reply("**Crypto Watch**\n" + "\n".join(lines))

@bot.command()
async def scanstocks(ctx: commands.Context):
    lines = await scan_list("Stocks Watch", WATCH_STOCKS)
    await ctx.reply("**Stocks Watch**\n" + "\n".join(lines))

@bot.command()
async def scanforex(ctx: commands.Context):
    lines = await scan_list("Forex Watch", WATCH_FOREX)
    await ctx.reply("**Forex Watch**\n" + "\n.join(lines)")

# ---------- Background loops (optional) ----------
@tasks.loop(minutes=25)
async def crypto_loop():
    if not CHANNEL_CRYPTO_ID:
        log.info("⚠️ No CHANNEL_CRYPTO_ID set; skipping crypto scan.")
        return
    ch = bot.get_channel(CHANNEL_CRYPTO_ID)
    if not isinstance(ch, (discord.TextChannel, discord.Thread)):
        return
    embed = await build_scan_embed("Auto Scan — Crypto Focus")
    await ch.send(embed=embed)

@tasks.loop(minutes=45)
async def stocks_loop():
    if not CHANNEL_STOCKS_ID:
        log.info("⚠️ No CHANNEL_STOCKS_ID set; skipping stocks scan.")
        return
    ch = bot.get_channel(CHANNEL_STOCKS_ID)
    if not isinstance(ch, (discord.TextChannel, discord.Thread)):
        return
    embed = await build_scan_embed("Auto Scan — Stocks Focus")
    await ch.send(embed=embed)

@tasks.loop(minutes=45)
async def forex_loop():
    if not CHANNEL_FOREX_ID:
        log.info("⚠️ No CHANNEL_FOREX_ID set; skipping forex scan.")
        return
    ch = bot.get_channel(CHANNEL_FOREX_ID)
    if not isinstance(ch, (discord.TextChannel, discord.Thread)):
        return
    embed = await build_scan_embed("Auto Scan — Forex Focus")
    await ch.send(embed=embed)

@bot.command(name="debugwatch")
async def debug_watchlists(ctx):
    """Show what tickers the bot has loaded from env vars."""
    crypto_raw = os.getenv("AIWATCH_CRYPTO_TICKERS", "")
    stocks_raw = os.getenv("AIWATCH_STOCKS_TICKERS", "")
    forex_raw = os.getenv("AIWATCH_FOREX_TICKERS", "")

    crypto = [c.strip() for c in crypto_raw.split(",") if c.strip()]
    stocks = [s.strip() for s in stocks_raw.split(",") if s.strip()]
    forex = [f.strip() for f in forex_raw.split(",") if f.strip()]

    msg = "**🔍 DEBUG WATCHLISTS**\n"
    msg += f"**Crypto:** {crypto if crypto else '❌ None loaded'}\n"
    msg += f"**Stocks:** {stocks if stocks else '❌ None loaded'}\n"
    msg += f"**Forex:** {forex if forex else '❌ None loaded'}"

    await ctx.send(msg)

# ---------- Entrypoint ----------
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN is not set.")
    bot.run(DISCORD_TOKEN)