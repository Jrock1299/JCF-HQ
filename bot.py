import os
import discord
from discord.ext import commands, tasks
import market_intel 
import signal_engine 
import portfolio 
import meme_engine

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN")

# Mapping Railway Variables to Channel IDs
CHANNELS = {
    # Existing Channels
    "risk_calc": int(os.getenv("CH_RISK", 0)),
    "crypto": int(os.getenv("CH_CRYPTO", 0)),
    "forex": int(os.getenv("CH_FOREX", 0)),
    "stocks": int(os.getenv("CH_STOCKS", 0)),
    "whale": int(os.getenv("CH_WHALE", 0)),
    "news": int(os.getenv("CH_NEWS", 0)),
    "logs": int(os.getenv("CH_LOGS", 0)),
    "status": int(os.getenv("CH_STATUS", 0)),
    "insider": int(os.getenv("CH_INSIDER", 0)),
    "smart": int(os.getenv("CH_SMART", 0)),
    
    # NEW SCALP CHANNELS
    "crypto_scalp": int(os.getenv("CH_CRYPTO_SCALP", 0)),
    "forex_scalp": int(os.getenv("CH_FOREX_SCALP", 0))
}

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- HELPER: ALERT FORMATTING ---
def create_alert_embed(data):
    # Color: Green for Buy, Red for Sell
    color = 0x00ff00 if "BUY" in data['signal'] else 0xff0000
    
    # Add Style Tag to Title (e.g., "⚡ SCALP BUY" or "🟢 SWING BUY")
    title_text = f"{data['signal']} SIGNAL: {data['symbol']}"
    
    embed = discord.Embed(title=title_text, color=color)
    
    # Row 1: The Basics
    embed.add_field(name="Entry Price", value=f"**${data['price']:.4f}**", inline=True)
    embed.add_field(name="Confidence", value=data['confidence'], inline=True)
    embed.add_field(name="RSI", value=f"{data['rsi']:.1f}", inline=True)
    
    # Row 2: Risk Management (Stops & Targets)
    embed.add_field(name="🛑 Stop Loss", value=f"${data['stop_loss']:.4f}", inline=True)
    embed.add_field(name="🎯 Take Profit", value=f"${data['take_profit']:.4f}", inline=True)
    
    # Custom Footer based on Style
    footer_text = "JCF AI Engine • "
    if data.get('style') == "SCALP":
        footer_text += "M15 Scalp Mode ⚡"
    else:
        footer_text += "H1/H4 Trend Mode 🌊"
        
    embed.set_footer(text=footer_text)
    return embed

# --- TASKS (THE AUTOMATION LOOPS) ---

@tasks.loop(hours=1) 
async def signal_scan_loop():
    print("📡 Scanning for Swing & Scalp Signals...")
    
    # Helper to route signals to the correct channel
    async def route_signal(sig):
        target_channel = None
        
        # 1. Determine Target Channel based on Asset & Style
        if sig['type'] == "CRYPTO":
            if sig.get('style') == "SCALP":
                target_channel = bot.get_channel(CHANNELS["crypto_scalp"])
            else: # Default to Swing
                target_channel = bot.get_channel(CHANNELS["crypto"])
        
        elif sig['type'] == "FOREX":
            if sig.get('style') == "SCALP":
                target_channel = bot.get_channel(CHANNELS["forex_scalp"])
            else:
                target_channel = bot.get_channel(CHANNELS["forex"])
                
        elif sig['type'] == "STOCK":
            target_channel = bot.get_channel(CHANNELS["stocks"])

        # 2. Post & Record
        if target_channel:
            await target_channel.send(embed=create_alert_embed(sig))
            
            # Record to Paper Portfolio (Both Swings and Scalps)
            try:
                portfolio.open_position(sig['symbol'], sig['price'], sig['signal'], sig['type'])
            except Exception as e:
                print(f"Portfolio Record Error: {e}")

    # --- EXECUTE SCANS ---
    if CHANNELS["crypto"] or CHANNELS["crypto_scalp"]:
        signals = await signal_engine.scan_crypto()
        for sig in signals: await route_signal(sig)

    if CHANNELS["stocks"]:
        signals = await signal_engine.scan_stocks()
        for sig in signals: await route_signal(sig)
            
    if CHANNELS["forex"] or CHANNELS["forex_scalp"]:
        signals = await signal_engine.scan_forex()
        for sig in signals: await route_signal(sig)

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

@tasks.loop(minutes=5)
async def meme_scan_loop():
    # Silent Data Collection for Meme Sniper
    try:
        count = await meme_engine.log_meme_data()
        if count and count > 0:
            print(f"🐶 Collected data on {count} new Solana coins.")
    except Exception as e:
        print(f"Meme Loop Error: {e}")

@tasks.loop(hours=12) 
async def insider_scan_loop():
    if not CHANNELS["insider"]: return
    try:
        alerts = await market_intel.check_insider_trading()
        channel = bot.get_channel(CHANNELS["insider"])
        if channel and alerts:
            for alert in alerts[:5]: 
                await channel.send(alert)
    except AttributeError: pass

@tasks.loop(hours=24) 
async def smart_money_loop():
    if not CHANNELS["smart"]: return
    try:
        alerts = await market_intel.check_smart_money()
        channel = bot.get_channel(CHANNELS["smart"])
        if channel and alerts:
            for alert in alerts[:5]:
                await channel.send(alert)
    except AttributeError: pass

# --- EVENTS ---
@bot.event
async def on_ready():
    print(f"✅ JCF HQ SYSTEM ONLINE: {bot.user.name}")
    
    # Start all engines
    if not signal_scan_loop.is_running(): signal_scan_loop.start()
    if not macro_news_loop.is_running(): macro_news_loop.start()
    if not whale_alert_loop.is_running(): whale_alert_loop.start()
    if not meme_scan_loop.is_running(): meme_scan_loop.start()
    if not insider_scan_loop.is_running(): insider_scan_loop.start()
    if not smart_money_loop.is_running(): smart_money_loop.start()
        
    if CHANNELS["status"]:
        channel = bot.get_channel(CHANNELS["status"])
        if channel:
            await channel.send("🟢 **SYSTEM UPDATE:** Split-Brain Engine (Scalp + Swing) is Active.")

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
    embed.set_footer(text=f"Stop Distance: {stop_distance:.5f}")
    
    await ctx.send(embed=embed)

@bot.command(name="portfolio")
async def show_portfolio(ctx):
    """Shows active paper trades and virtual PnL."""
    msg = await ctx.send("🔄 Fetching live prices...")
    total_pnl, report = await portfolio.generate_portfolio_report()
    
    if total_pnl is None:
        await msg.edit(content=f"ℹ️ {report}")
        return

    color = 0x00ff00 if total_pnl >= 0 else 0xff0000
    embed = discord.Embed(title="💼 Virtual CEO Dashboard", color=color)
    embed.description = report
    embed.add_field(name="Total Unrealized PnL", value=f"**{total_pnl:+.2f}%**", inline=False)
    
    await msg.edit(content="", embed=embed)

@bot.command(name="status")
async def system_status(ctx):
    """Checks system health and data collection progress."""
    data_file = "/app/data/market_training_data.csv"
    row_count = 0
    
    if os.path.exists(data_file):
        try:
            with open(data_file, 'r') as f:
                row_count = sum(1 for _ in f) - 1
        except: pass
    
    embed = discord.Embed(title="🟢 SYSTEM STATUS: ONLINE", color=0x00ff00)
    embed.add_field(name="Latency", value=f"{bot.latency * 1000:.0f}ms", inline=True)
    embed.add_field(name="AI Data Collected", value=f"📊 {row_count} rows", inline=False)
    
    modules = []
    modules.append("✅ Signal Engine (Swing + Scalp)" if signal_scan_loop.is_running() else "❌ Signal Engine")
    modules.append("✅ Insider/Smart Money" if insider_scan_loop.is_running() else "❌ Intel Engine")
    modules.append("✅ Meme Sniper (Data Only)" if meme_scan_loop.is_running() else "❌ Meme Sniper")
    
    embed.add_field(name="Active Engines", value="\n".join(modules), inline=False)
    await ctx.send(embed=embed)

# --- LAUNCH ---
if __name__ == "__main__":
    if not TOKEN:
        print("❌ ERROR: DISCORD_TOKEN is missing!")
    else:
        bot.run(TOKEN)
