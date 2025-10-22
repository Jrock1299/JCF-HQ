import os
os.environ["DISCORD_NO_AUDIO"] = "1"

import discord
from discord.ext import commands
from datetime import datetime

# --- ENV ---
TOKEN = os.getenv("DISCORD_TOKEN")
ANNOUNCE_CHANNEL_ID = int(os.getenv("ANNOUNCE_CHANNEL_ID", "0"))
CRYPTO_SETUPS_CHANNEL_ID = int(os.getenv("CRYPTO_SETUPS_CHANNEL_ID", "0"))
STOCK_SETUPS_CHANNEL_ID  = int(os.getenv("STOCK_SETUPS_CHANNEL_ID", "0"))

# --- BOT ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- UTIL: embed factory ---
def setup_embed(title: str, fields: list[tuple[str, str, bool]], color: int = 0x00D084) -> discord.Embed:
    emb = discord.Embed(title=title, color=color, timestamp=datetime.utcnow())
    for name, value, inline in fields:
        emb.add_field(name=name, value=value, inline=inline)
    emb.set_footer(text="JCF HQ • Auto-generated setup")
    return emb

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (id: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="JCF HQ online"))
    if ANNOUNCE_CHANNEL_ID:
        ch = bot.get_channel(ANNOUNCE_CHANNEL_ID)
        if ch:
            await ch.send("✅ **JCFWatchBot ONLINE** — Systems initialized. Monitoring markets…")
    print("✅ Startup message sent (if channel set).")

# --- TEST COMMANDS ---

@bot.command(help="Post a sample CRYPTO setup to the configured channel.")
async def testcrypto(ctx):
    if not CRYPTO_SETUPS_CHANNEL_ID:
        return await ctx.reply("❌ CRYPTO_SETUPS_CHANNEL_ID not set in env.")
    ch = bot.get_channel(CRYPTO_SETUPS_CHANNEL_ID)
    if not ch:
        return await ctx.reply("❌ I can't access the crypto setups channel. Check my permissions.")

    title = "🎯 CRYPTO – Trend Continuation (Breakout + Retest)"
    fields = [
        ("Asset", "**SOL/USDT**", True),
        ("Bias", "**Bullish** (H1/H4 aligned)", True),
        ("Entry (Aggressive)", "`$161.20` (retest of former resistance)", False),
        ("Entry (Confirmation)", "`$163.00` (close above H1 structure)", False),
        ("Stop Loss", "`$156.80` (below swing + liquidity pocket)", True),
        ("Targets", "`$168.5 / $174.0 / $181.0`", True),
        ("R:R", "2.6R (to T2)", True),
        ("Risk", "Account risk: **2%**", True),
        ("Notes", "Impulse ↑, shallow pullback, OBV rising, funding neutral → favorable continuation.", False),
    ]
    await ch.send(embed=setup_embed(title, fields))
    await ctx.reply("✅ Posted sample **crypto** setup to the configured channel.")

@bot.command(help="Post a sample STOCK setup to the configured channel.")
async def teststock(ctx):
    if not STOCK_SETUPS_CHANNEL_ID:
        return await ctx.reply("❌ STOCK_SETUPS_CHANNEL_ID not set in env.")
    ch = bot.get_channel(STOCK_SETUPS_CHANNEL_ID)
    if not ch:
        return await ctx.reply("❌ I can't access the stock setups channel. Check my permissions.")

    title = "📈 STOCK – Breakout + Retest (Trend Continuation)"
    fields = [
        ("Ticker", "**MSTR**", True),
        ("Bias", "**Bullish** (above 20/50 EMA, RS vs SPY rising)", True),
        ("Entry (Aggressive)", "`$159.40` (retest of breakout level)", False),
        ("Entry (Confirmation)", "`$161.20` (5m close above prior high)", False),
        ("Stop Loss", "`$154.90` (below breakout base)", True),
        ("Targets", "`$166 / $172 / $179`", True),
        ("R:R", "≈2.3R (to T2)", True),
        ("Risk", "Account risk: **1–1.5%**", True),
        ("Notes", "High call flow, low supply on tape; watch NVDA/QQQ correlation for momentum.", False),
    ]
    await ch.send(embed=setup_embed(title, fields, color=0x2D7DFA))
    await ctx.reply("✅ Posted sample **stock** setup to the configured channel.")

@bot.command()
async def ping(ctx):
    await ctx.reply("Pong 🏓")

bot.run(TOKEN)
