import os, time, math, requests, asyncio
import numpy as np
import pandas as pd
import discord
from discord.ext import commands, tasks
from datetime import datetime, timezone

# --- ENV ---
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CRYPTO_SETUPS_CHANNEL_ID", "0"))
COINGECKO_KEY = os.getenv("COINGECKO_API_KEY")
COIN_IDS = [c.strip() for c in os.getenv("COIN_IDS","bitcoin,ethereum,solana,ripple,cardano,chainlink,polygon-ecosystem-token,dogecoin,avalanche-2,tron").split(",")]
SCAN_EVERY = int(os.getenv("SCAN_INTERVAL_MINUTES","5"))

# --- Discord bot ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

HEADERS = {"accept": "application/json", "x-cg-pro-api-key": COINGECKO_KEY}

# simple cache to avoid spam (per coin per side)
last_signal = {}  # {"coin":{"side":"long/short","ts":epoch}}

def ema(series, n):
    return series.ewm(span=n, adjust=False).mean()

def rsi(series, n=14):
    delta = series.diff()
    gain = np.where(delta>0, delta, 0.0)
    loss = np.where(delta<0, -delta, 0.0)
    gain_ema = pd.Series(gain, index=series.index).ewm(span=n, adjust=False).mean()
    loss_ema = pd.Series(loss, index=series.index).ewm(span=n, adjust=False).mean()
    rs = gain_ema / (loss_ema + 1e-9)
    return 100 - (100/(1+rs))

def atr(high, low, close, n=14):
    prev_close = close.shift(1)
    tr = pd.concat([
        (high-low).abs(),
        (high-prev_close).abs(),
        (low-prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(n).mean()

def fetch_ohlc(coin_id, days="1", interval="minute"):
    # market_chart gives minute or hourly candles depending on days
    # for intraday use days=1 -> 1-min; we’ll aggregate to 5-min
    url = f"https://pro-api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
    params = {"vs_currency":"usd", "days":days, "interval":interval}
    r = requests.get(url, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()
    # prices: [ [ts, price], ... ]
    df = pd.DataFrame(data["prices"], columns=["ts","price"])
    df["high"] = [h for _,h in data["high_24h"]] if "high_24h" in data else df["price"]
    # Build OHLC by resampling to 5-min
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df.set_index("ts", inplace=True)
    ohlc = df["price"].resample("5min").ohlc()
    vol = pd.DataFrame(data.get("total_volumes", []), columns=["ts","vol"])
    if not vol.empty:
        vol["ts"] = pd.to_datetime(vol["ts"], unit="ms", utc=True)
        vol.set_index("ts", inplace=True)
        vol5 = vol["vol"].resample("5min").last().diff().clip(lower=0)
        ohlc["volume"] = vol5
    else:
        ohlc["volume"] = 0
    return ohlc.dropna()

def balanced_signal(ohlc):
    close = ohlc["close"]
    high, low = ohlc["high"], ohlc["low"]
    vol = ohlc["volume"]

    ema50 = ema(close, 50)
    ema200 = ema(close, 200)
    r = rsi(close, 14)
    a = atr(high, low, close, 14)

    df = pd.DataFrame({
        "close": close, "ema50": ema50, "ema200": ema200,
        "rsi": r, "atr": a, "low": low, "high": high, "vol": vol
    }).dropna()

    if len(df) < 210:
        return None

    c = df.iloc[-1]
    p = df.iloc[-2]

    # trend filters
    bull = (c.ema50 > c.ema200) and (c.close > c.ema50)
    bear = (c.ema50 < c.ema200) and (c.close < c.ema50)

    # “retest” = price recently crossed ema50 and pulled back within 0.5*ATR but held
    crossed_up = (p.close < p.ema50) and (c.close > c.ema50)
    crossed_down = (p.close > p.ema50) and (c.close < c.ema50)

    retest_long = bull and (abs(c.low - c.ema50) <= 0.5*c.atr)
    retest_short = bear and (abs(c.high - c.ema50) <= 0.5*c.atr)

    # momentum confirmation: RSI tilting in trend direction and in 45-65 band (not overbought/oversold)
    rsi_up = (c.rsi > p.rsi) and (45 <= c.rsi <= 65)
    rsi_down = (c.rsi < p.rsi) and (35 <= c.rsi <= 55)

    # volume pulse: current 5m vol > 20-bar avg
    vol_ok = c.vol > df.vol.tail(20).mean()

    if (retest_long or crossed_up) and rsi_up and vol_ok:
        # build levels
        entry = round(float(c.close), 4)
        stop = round(float(c.ema50 - 0.8*c.atr), 4)
        t1 = round(float(entry + 0.8*c.atr), 4)
        t2 = round(float(entry + 1.4*c.atr), 4)
        t3 = round(float(entry + 2.0*c.atr), 4)
        return {"side":"LONG","entry":entry,"stop":stop,"targets":[t1,t2,t3],
                "trend":"Bullish retest","tf":"5m"}
    if (retest_short or crossed_down) and rsi_down and vol_ok:
        entry = round(float(c.close), 4)
        stop = round(float(c.ema50 + 0.8*c.atr), 4)
        t1 = round(float(entry - 0.8*c.atr), 4)
        t2 = round(float(entry - 1.4*c.atr), 4)
        t3 = round(float(entry - 2.0*c.atr), 4)
        return {"side":"SHORT","entry":entry,"stop":stop,"targets":[t1,t2,t3],
                "trend":"Bearish retest","tf":"5m"}
    return None

async def post_setup(channel: discord.TextChannel, coin_id, sig):
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    t1,t2,t3 = sig["targets"]
    side = "🟢 LONG" if sig["side"]=="LONG" else "🔴 SHORT"
    em = discord.Embed(
        title=f"{side} Setup — {coin_id.upper()}",
        description=f"**Trend:** {sig['trend']}  •  **TF:** {sig['tf']}\n"
                    f"**Entry:** `{sig['entry']}`  •  **Stop:** `{sig['stop']}`\n"
                    f"**Targets:** `{t1}` / `{t2}` / `{t3}`",
        timestamp=datetime.now(timezone.utc),
        color=0x00c853 if sig["side"]=="LONG" else 0xd50000
    )
    em.set_footer(text=now + " • CoinGecko data")
    await channel.send(embed=em)

@tasks.loop(minutes=1)
async def scanner():
    # throttle by SCAN_EVERY minutes
    if int(time.time()) % (SCAN_EVERY*60) > 60:  # run once per window
        return
    ch = bot.get_channel(CHANNEL_ID)
    if not ch:
        return

    for coin in COIN_IDS:
        try:
            ohlc = fetch_ohlc(coin, days="1", interval="minute")  # 5m agg inside
            sig = balanced_signal(ohlc)
            if not sig:
                continue
            # de-dup within 60 minutes per side
            k = last_signal.get(coin, {})
            if k and k.get("side")==sig["side"] and time.time()-k.get("ts",0) < 3600:
                continue
            await post_setup(ch, coin, sig)
            last_signal[coin] = {"side": sig["side"], "ts": time.time()}
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"[scan] {coin}: {e}")

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (id: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="JCF HQ — Crypto Scanner"))
    if not scanner.is_running():
        scanner.start()

@bot.command()
async def ping(ctx): await ctx.reply("Pong 🏓")

bot.run(TOKEN)