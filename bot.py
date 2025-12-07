import os
import discord
from discord.ext import commands, tasks
import asyncio

# --- CONFIGURATION ---
# Load secrets from Railway Variables
TOKEN = os.getenv("DISCORD_TOKEN")

# Channel IDs (We map these to your specific channels)
CHANNELS = {
    "risk_calc": int(os.getenv("CH_RISK", 0)),
    "crypto": int(os.getenv("CH_CRYPTO", 0)),
    "forex": int(os.getenv("CH_FOREX", 0)),
    "stocks": int(os.getenv("CH_STOCKS", 0)),
    "whale": int(os.getenv("CH_WHALE", 0)),
    "news": int(os.getenv("CH_NEWS", 0)),
    "logs": int(os.getenv("CH_LOGS", 0))
}

# --- BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- EVENTS ---
@bot.event
async def on_ready():
    print(f"✅ JCF HQ SYSTEM ONLINE: {bot.user.name}")
    print(f"📊 Connected to {len(bot.guilds)} servers")
    
    # Send a boot-up message to the log channel (Trade History)
    if CHANNELS["logs"]:
        channel = bot.get_channel(CHANNELS["logs"])
        if channel:
            await channel.send("🟢 **SYSTEM REBOOT:** JCF Hedge Fund Engine is now Online.")

# --- TOOL: RISK CALCULATOR ---
# Usage: !risk <AccountSize> <Entry> <StopLoss>
@bot.command(name="risk")
async def calculate_risk(ctx, balance: float, entry: float, stop_loss: float):
    """
    Calculates position size based on 1% and 2% risk.
    Usage: !risk 10000 1.0500 1.0450
    """
    # 1. Determine Risk Amounts
    risk_1_pct = balance * 0.01
    risk_2_pct = balance * 0.02
    
    # 2. Calculate Distance (Absolute value handles Longs and Shorts)
    stop_distance = abs(entry - stop_loss)
    
    if stop_distance == 0:
        await ctx.send("❌ Error: Entry and Stop Loss cannot be the same.")
        return

    # 3. Calculate Position Size (Units)
    units_1pct = risk_1_pct / stop_distance
    units_2pct = risk_2_pct / stop_distance

    # 4. Format the Output
    embed = discord.Embed(title="🛡️ Risk Management Calculator", color=0x00d1ff)
    embed.add_field(name="Account Balance", value=f"${balance:,.2f}", inline=False)
    
    # 1% Risk Column
    embed.add_field(name="Conservative (1%)", 
                    value=f"Risk: **${risk_1_pct:.2f}**\nSize: **{units_1pct:,.2f} units**", 
                    inline=True)
    
    # 2% Risk Column
    embed.add_field(name="Aggressive (2%)", 
                    value=f"Risk: **${risk_2_pct:.2f}**\nSize: **{units_2pct:,.2f} units**", 
                    inline=True)
    
    embed.set_footer(text=f"Stop Distance: {stop_distance:.5f} | calculated by JCF AI")
    
    await ctx.send(embed=embed)

# --- ERROR HANDLING ---
@calculate_risk.error
async def risk_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("⚠️ **Usage:** `!risk <Balance> <Entry> <StopLoss>`\nExample: `!risk 10000 50000 49500`")

# --- LAUNCH ---
if __name__ == "__main__":
    if not TOKEN:
        print("❌ ERROR: DISCORD_TOKEN not found in environment variables.")
    else:
        bot.run(TOKEN)
