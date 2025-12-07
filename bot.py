import os
import discord
from discord.ext import commands, tasks
import market_intel 
import signal_engine 
import portfolio # <--- NEW IMPORT

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
    
    # Helper to process signals
    async def process_signals(signals, channel_id):
        channel = bot.get_channel(channel_id)
        if not channel: return
        
        for sig in signals:
            # 1. Post to Discord
            await channel.send(embed=create_alert_embed(sig))
            
            # 2. Record to Paper Portfolio (NEW)
            try:
                portfolio.open_position(sig['symbol'], sig['price'], sig['signal'], sig['type'])
            except Exception as e:
                print(f"Portfolio Record Error: {e}")

    # 1. Crypto
    if CHANNELS["crypto"]:
        signals = await signal_engine.scan_crypto()
        await process_signals(signals, CHANNELS["crypto"])

    # 2. Stocks
    if CHANNELS["stocks"]:
        signals = await signal_engine.scan_stocks()
        await process_signals(signals, CHANNELS["stocks"])
            
    # 3. Forex
    if CHANNELS["forex"]:
        signals = await signal_engine.scan_forex()
        await process_signals(signals, CHANNELS["forex"])

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
            await channel.send("🟢 **SYSTEM REBOOT:** Paper Trader & Portfolio Tracker Active.")

# --- COMMANDS ---
@bot.command(name="portfolio")
async def show_portfolio(ctx):
    """Shows active paper trades and virtual PnL."""
    msg = await ctx.send("🔄 Fetching live prices and calculating PnL...")
    
    total_pnl, report = await portfolio.generate_portfolio_report()
    
    if total_pnl is None:
        await msg.edit(content=f"ℹ️ {report}")
        return

    # Create nice embed
    color = 0x00ff00 if total_pnl >= 0 else 0xff0000
    embed = discord.Embed(title="💼 Virtual CEO Dashboard", color=color)
    embed.description = report
    embed.add_field(name="Total Unrealized PnL", value=f"**{total_pnl:+.2f}%**", inline=False)
    embed.set_footer(text="Performance tracking of AI Signals")
    
    await msg.edit(content="", embed=embed)

@bot.command(name="risk")
async def calculate_risk(ctx, balance: float, entry: float, stop_loss: float):
    # (Keeping this brief for space, assume same Risk code as before)
    risk_1_pct = balance * 0.01
    stop_distance = abs(entry - stop_loss)
    if stop_distance == 0: return
    units = risk_1_pct / stop_distance
    await ctx.send(f"🛡️ Risk (1%): ${risk_1_pct:.2f} | Size: {units:.2f} units")

@bot.command(name="status")
async def system_status(ctx):
    # (Same status code as before)
    data_file = "/app/data/market_training_data.csv"
    row_count = 0
    if os.path.exists(data_file):
        with open(data_file, 'r') as f: row_count = sum(1 for _ in f) - 1
    await ctx.send(f"🟢 **ONLINE** | AI Data: {row_count} rows")

# --- LAUNCH ---
if __name__ == "__main__":
    if not TOKEN:
        print("❌ ERROR: DISCORD_TOKEN is missing!")
    else:
        bot.run(TOKEN)
