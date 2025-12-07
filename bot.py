import os
import discord
from discord.ext import commands, tasks
import market_intel 
import signal_engine 

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN")

CHANNELS = {
    "risk_calc": int(os.getenv("CH_RISK", 0)),
    "crypto": int(os.getenv("CH_CRYPTO", 0)),
    "forex": int(os.getenv("CH_FOREX", 0)),
    "stocks": int(os.getenv("CH_STOCKS", 0)),
    "whale": int(os.getenv("CH_WHALE", 0)),
    "news": int(os.getenv("CH_NEWS", 0)),
    "logs": int(os.getenv("CH_LOGS", 0)),
    "status": int(os.getenv("CH_STATUS", 0))
}

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- FORMATTING ALERT ---
def create_alert_embed(data):
    color = 0x00ff00 if "BUY" in data['signal'] else 0xff0000
    embed = discord.Embed(title=f"{data['signal']} SIGNAL: {data['symbol']}", color=color)
    embed.add_field(name="Price", value=f"${data['price']:.4f}", inline=True)
    embed.add_field(name="Confidence", value=data['confidence'], inline=True)
    embed.add_field(name="RSI", value=f"{data['rsi']:.1f}", inline=True)
    embed.set_footer(text="JCF AI Engine • 1H Timeframe")
    return embed

# --- TASKS (LOOPS) ---
@tasks.loop(hours=1) 
async def signal_scan_loop():
    print("📡 Scanning for Trade Signals...")
    if CHANNELS["crypto"]:
        signals = await signal_engine.scan_crypto()
        channel = bot.get_channel(CHANNELS["crypto"])
        if channel:
            for sig in signals: await channel.send(embed=create_alert_embed(sig))

    if CHANNELS["stocks"]:
        signals = await signal_engine.scan_stocks()
        channel = bot.get_channel(CHANNELS["stocks"])
        if channel:
            for sig in signals: await channel.send(embed=create_alert_embed(sig))
            
    if CHANNELS["forex"]:
        signals = await signal_engine.scan_forex()
        channel = bot.get_channel(CHANNELS["forex"])
        if channel:
            for sig in signals: await channel.send(embed=create_alert_embed(sig))

@tasks.loop(hours=4) 
async def macro_news_loop():
    if not CHANNELS["news"]: return
    news_list = await market_intel.fetch_major_news()
    if news_list:
        channel = bot.get_channel(CHANNELS["news"])
        if channel:
            for news_item in news_list: await channel.send(news_item)

@tasks.loop(minutes=60) 
async def whale_alert_loop():
    if not CHANNELS["whale"]: return
    alerts = await market_intel.check_crypto_whales()
    if alerts:
        channel = bot.get_channel(CHANNELS["whale"])
        if channel:
            for alert in alerts: await channel.send(alert)

# --- EVENTS ---
@bot.event
async def on_ready():
    print(f"✅ JCF HQ SYSTEM ONLINE: {bot.user.name}")
    if not signal_scan_loop.is_running(): signal_scan_loop.start()
    if not macro_news_loop.is_running(): macro_news_loop.start()
    if not whale_alert_loop.is_running(): whale_alert_loop.start()
        
    if CHANNELS["status"]:
        channel = bot.get_channel(CHANNELS["status"])
        if channel:
            await channel.send("🟢 **SYSTEM REBOOT:** Signal Engine & Data Logger Active.")

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

@bot.command(name="status")
async def system_status(ctx):
    """Checks system health and data collection progress."""
    data_file = "/app/data/market_training_data.csv"
    row_count = 0
    file_size = "0 KB"
    
    if os.path.exists(data_file):
        try:
            with open(data_file, 'r') as f:
                row_count = sum(1 for _ in f) - 1
            size_bytes = os.path.getsize(data_file)
            file_size = f"{size_bytes / 1024:.1f} KB"
        except Exception:
            row_count = "Error reading file"
    
    embed = discord.Embed(title="🟢 SYSTEM STATUS: ONLINE", color=0x00ff00)
    embed.add_field(name="Latency", value=f"{bot.latency * 1000:.0f}ms", inline=True)
    embed.add_field(name="AI Training Data", value=f"📊 {row_count} rows collected\n💾 {file_size}", inline=False)
    
    modules = []
    if signal_scan_loop.is_running(): modules.append("✅ Signal Engine")
    else: modules.append("❌ Signal Engine (STOPPED)")
    if whale_alert_loop.is_running(): modules.append("✅ Whale Watcher")
    
    embed.add_field(name="Active Engines", value="\n".join(modules), inline=False)
    embed.set_footer(text="JCF Hedge Fund Command Center")
    await ctx.send(embed=embed)

# --- LAUNCH ---
if __name__ == "__main__":
    if not TOKEN:
        print("❌ ERROR: DISCORD_TOKEN is missing!")
    else:
        bot.run(TOKEN)
