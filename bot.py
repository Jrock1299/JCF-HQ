import os
os.environ["DISCORD_NO_AUDIO"] = "1"   # prevent audio import

import asyncio
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands, tasks

import pandas as pd
import yfinance as yf

# ---------- ENV ----------
TOKEN = os.getenv("DISCORD_TOKEN")
ANNOUNCE_ID = int(os.getenv("ANNOUNCE_CHANNEL_ID", "0") or 0)

CRYPTO_CH_ID = int(os.getenv("CRYPTO_SETUPS_CHANNEL_ID", "0") or 0)
STOCKS_CH_ID = int(os.getenv("STOCK_SETUPS_CHANNEL_ID", "0") or 0)
FOREX_CH_ID  = int(os.getenv("FOREX_SETUPS_CHANNEL_ID", "0") or 0)

# Watchlists (you can add envs later; these defaults are fine for testing)
DEFAULT_STOCKS = ["AAPL", "NVDA", "TSLA", "AMD", "PLTR", "MSTR", "SOFI"]
DEFAULT_CRYPTO = ["BTC-USD", "ETH-USD", "SOL-USD", "ADA-USD", "LINK-USD"]
DEFAULT_FOREX  = ["EURUSD=X", "USDJPY=X", "XAUUSD=X", "GBPUSD=X"]

stocks_list = [s.strip() for s in os.getenv("AI_STOCKS", ",".join(DEFAULT_STOCKS)).split(",") if s.strip()]
crypto_list = [s.strip() for s in os.getenv("AI_CRYPTO", ",".join(DEFAULT_CRYPTO)).split(",") if s.strip()]
forex_list  = [s.strip() for s in os.getenv("AI_FOREX",  ",".join(DEFAULT_FOREX)).split(",") if s.strip()]

# ---------- DISCORD ----------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

def pick_channel(*ids):
    for i in ids:
        if i:
            ch = bot.get_channel(i)
            if ch:
                return ch
    return None

@bot.event
async def on_ready():
    ch = pick_channel(ANNOUNCE_ID, CRYPTO_CH_ID, STOCKS_CH_ID, FOREX_CH_ID)
    if ch:
        await ch.send("✅ **JCFWatchBot ONLINE** — AI scanner loaded. Use `!scanonce` to test.")
    print(f"Logged in as {bot.user} ({bot.user.id})")

@bot.command()
async def ping(ctx):
    await ctx.reply("Pong 🏓")

@bot.command()
async def scanonce(ctx):
    """Run one quick pass and post sample setups."""
    await ctx.reply("🔎 Running a quick scan…")
    await run_scan_once()

async def run_scan_once():
    # Simple rules:
    # - Stocks/Forex: 20/50 SMA cross + RSI(14) extremes
    # - Crypto: 20/50 SMA cross + strong 24h move
    async def scan(tickers, kind):
        ideas = []
        period = "60d"
        interval = "1h" if kind != "forex" else "1h"
        for t in tickers[:12]:  # cap for speed
            try:
                df = yf.download(t, period=period, interval=interval, progress=False, auto_adjust=True)
                if df is None or df.empty or len(df) < 60:
                    continue
                df["sma20"] = df["Close"].rolling(20).mean()
                df["sma50"] = df["Close"].rolling(50).mean()
                df["rsi"] = rsi(df["Close"], 14)

                last = df.iloc[-1]
                prev = df.iloc[-2]

                cross_up = prev["sma20"] <= prev["sma50"] and last["sma20"] > last["sma50"]
                cross_dn = prev["sma20"] >= prev["sma50"] and last["sma20"] < last["sma50"]

                rsi_low = last["rsi"] <= 35
                rsi_high = last["rsi"] >= 65

                move_24h = (last["Close"] / df["Close"].iloc[-24] - 1.0) * 100 if len(df) >= 24 else 0.0

                if cross_up or (rsi_low and move_24h > 1.5 and kind == "crypto"):
                    ideas.append(("LONG", t, float(last["Close"]), float(last["sma20"]), float(last["sma50"]), float(last["rsi"]), move_24h))
                elif cross_dn or (rsi_high and move_24h < -1.5 and kind == "crypto"):
                    ideas.append(("SHORT", t, float(last["Close"]), float(last["sma20"]), float(last["sma50"]), float(last["rsi"]), move_24h))
            except Exception as e:
                print(f"scan error {t}: {e}")
        return ideas

    # run scans
    stock_ideas = await scan(stocks_list, "stocks")
    crypto_ideas = await scan(crypto_list, "crypto")
    forex_ideas  = await scan(forex_list,  "forex")

    # post results
    await post_setups(stock_ideas, STOCKS_CH_ID, "📈 **AI Stock Setups**")
    await post_setups(crypto_ideas, CRYPTO_CH_ID, "🎯 **AI Crypto Setups**")
    await post_setups(forex_ideas,  FOREX_CH_ID,  "💱 **AI Forex Setups**")

async def post_setups(ideas, channel_id, title):
    ch = pick_channel(channel_id, ANNOUNCE_ID)
    if not ch:
        print(f"No channel available for {title}")
        return
    if not ideas:
        await ch.send(f"{title}\n_No strong signals right now. I’ll keep watching._")
        return

    lines = [title]
    for side, sym, price, sma20, sma50, rsi_val, m24 in ideas[:6]:
        lines.append(
            f"• **{sym}** → **{side}**  | Px: `{price:.4g}`  | SMA20/50: `{sma20:.4g}/{sma50:.4g}`  | RSI14: `{rsi_val:.1f}`  | 24h: `{m24:.1f}%`"
        )
    await ch.send("\n".join(lines))

# --- helpers ---
def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(length).mean()
    avg_loss = loss.rolling(length).mean()
    rs = avg_gain / (avg_loss.replace(0, 1e-9))
    return 100 - (100 / (1 + rs))

# Optional: background loop (off by default). Turn on by setting AI_SCAN_LOOP=1.
@tasks.loop(minutes=15)
async def background_scan():
    await run_scan_once()

@bot.event
async def on_connect():
    if os.getenv("AI_SCAN_LOOP", "0") == "1" and not background_scan.is_running():
        background_scan.start()

bot.run(TOKEN)