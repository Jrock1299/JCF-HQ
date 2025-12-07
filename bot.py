import os
import discord
from discord.ext import commands, tasks
import market_intel 

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN")

# Channel IDs 
CHANNELS = {
    "risk_calc": int(os.getenv("CH_RISK", 0)),
    "crypto": int(os.getenv("CH_CRYPTO", 0)),
    "forex": int(os.getenv("CH_FOREX", 0)),
    "stocks": int(os.getenv("CH_STOCKS", 0)),
    "whale": int(os.getenv("CH_WHALE", 0)),
    "news": int(os.getenv("CH_NEWS", 0)),
    "logs": int(os.getenv("CH_LOGS", 0)),
    "status": int(os.getenv("CH_STATUS", 0)) # <--- NEW CONNECTION ADDED
}

# --- BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- TASKS (LOOPS) ---
@tasks.loop(hours=4) 
async def macro_news_loop():
    if not CHANNELS["news"]: return
    news_list = await market_intel.fetch_major_news()
    if news_list:
        channel = bot.get_channel(CHANNELS["news"])
        for news_item in news_list:
            await channel.send(news_item)

@tasks.loop(minutes=60) 
async def whale_alert_loop():
    if not CHANNELS["whale"]: return
    alerts = await market_intel.check_crypto_whales()
    if alerts:
        channel = bot.get_channel(CHANNELS["whale"])
        for alert in alerts:
            await channel.send(alert)

# --- EVENTS ---
@bot.event
async def on_ready():
    print(f"✅ JCF HQ SYSTEM ONLINE: {bot.user.name}")
    
    # Start the loops
    if not macro_news_loop.is_running():
        macro_news_loop.start()
    if not whale_alert_loop.is_running():
        whale_alert_loop.start()
        
    # --- UPDATED: Send Reboot Message to #bot-status ---
    if CHANNELS["status"]:
        channel = bot.get_channel(CHANNELS["status"])
        if channel:
            await channel.send("🟢 **SYSTEM REBOOT:** JCF Hedge Fund Engine is now Online.")

# --- COMMANDS ---
@bot.command(name="risk")
async def calculate_risk(ctx, balance: float, entry: float, stop_loss: float):
    risk_1_pct = balance * 0.01
    risk_2_pct = balance * 0.02
    stop_distance = abs(entry - stop_loss)
    
    if stop_distance == 0:
        await ctx.send("❌ Error: Entry and Stop Loss cannot be the same.")
        return

    units_1pct = risk_1_pct / stop_distance
    units_2pct = risk_2_pct / stop_distance

    embed = discord.Embed(title="🛡️ Risk Management Calculator", color=0x00d1ff)
    embed.add_field(name="Account Balance", value=f"${balance:,.2f}", inline=False)
    embed.add_field(name="Conservative (1%)", value=f"Risk: **${risk_1_pct:.2f}**\nSize: **{units_1pct:,.2f} units**", inline=True)
    embed.add_field(name="Aggressive (2%)", value=f"Risk: **${risk_2_pct:.2f}**\nSize: **{units_2pct:,.2f} units**", inline=True)
    embed.set_footer(text=f"Stop Distance: {stop_distance:.5f} | calculated by JCF AI")
    
    await ctx.send(embed=embed)

@calculate_risk.error
async def risk_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("⚠️ **Usage:** `!risk <Balance> <Entry> <StopLoss>`")

# --- LAUNCH ---
if __name__ == "__main__":
    bot.run(TOKEN)
