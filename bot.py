import os
import asyncio
import discord
from discord.ext import commands, tasks
import market_intel 
import signal_engine 
import portfolio 
import meme_engine
import io
import sys

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
    "status": int(os.getenv("CH_STATUS", 0)),
    "insider": int(os.getenv("CH_INSIDER", 0)),
    "smart": int(os.getenv("CH_SMART", 0)),
    "crypto_scalp": int(os.getenv("CH_CRYPTO_SCALP", 0)),
    "forex_scalp": int(os.getenv("CH_FOREX_SCALP", 0)),
    "meme": int(os.getenv("CH_MEME", 0))  # New channel for meme alerts
}

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- HELPER: ALERT FORMATTING ---
def create_alert_embed(data):
    color = 0x00ff00 if "BUY" in data['signal'] else 0xff0000
    title_text = f"{data['signal']} SIGNAL: {data['symbol']}"
    embed = discord.Embed(title=title_text, color=color)
    
    embed.add_field(name="Entry Price", value=f"**${data['price']:.4f}**", inline=True)
    embed.add_field(name="Confidence", value=data['confidence'], inline=True)
    embed.add_field(name="RSI", value=f"{data['rsi']:.1f}", inline=True)
    embed.add_field(name="🛑 Stop Loss", value=f"${data['stop_loss']:.4f}", inline=True)
    embed.add_field(name="🎯 Take Profit", value=f"${data['take_profit']:.4f}", inline=True)
    
    footer_text = "JCF AI Engine • "
    footer_text += "M15 Scalp Mode ⚡" if data.get('style') == "SCALP" else "H1/H4 Trend Mode 🌊"
    embed.set_footer(text=footer_text)
    return embed

# --- TASKS (AUTOMATION LOOPS) ---

@tasks.loop(hours=1) 
async def signal_scan_loop():
    print("📡 Scanning for Swing & Scalp Signals...")
    
    async def route_signal(sig):
        # 1. CHECK: Is this trade already open?
        # If it is, we return early and do NOT send an alert.
        if portfolio.is_trade_active(sig['symbol'], sig.get('style', 'SWING')):
            return 

        target_channel = None
        if sig['type'] == "CRYPTO":
            target_channel = bot.get_channel(CHANNELS["crypto_scalp"] if sig.get('style') == "SCALP" else CHANNELS["crypto"])
        elif sig['type'] == "FOREX":
            target_channel = bot.get_channel(CHANNELS["forex_scalp"] if sig.get('style') == "SCALP" else CHANNELS["forex"])
        elif sig['type'] == "STOCK":
            target_channel = bot.get_channel(CHANNELS["stocks"])
        elif sig['type'] == "MEME":
            target_channel = bot.get_channel(CHANNELS["meme"])

        if target_channel:
            # 2. Send Alert ONLY if we are actually taking the trade
            await target_channel.send(embed=create_alert_embed(sig))
            try:
                portfolio.open_position(
                    sig['symbol'], sig['price'], sig['signal'], sig['type'], 
                    sig['stop_loss'], sig['take_profit'], sig.get('style', 'SWING')
                )
            except Exception as e:
                print(f"Portfolio Record Error: {e}")

    # Scans
    if CHANNELS["crypto"]:
        signals = await signal_engine.scan_crypto()
        for sig in signals: await route_signal(sig)
    if CHANNELS["stocks"]:
        signals = await signal_engine.scan_stocks()
        for sig in signals: await route_signal(sig) 
    if CHANNELS["forex"]:
        signals = await signal_engine.scan_forex()
        for sig in signals: await route_signal(sig)
    if CHANNELS["meme"]:
        signals = await signal_engine.scan_memes()
        for sig in signals: await route_signal(sig)

@tasks.loop(minutes=5)
async def portfolio_manager_loop():
    try:
        closed_alerts = await portfolio.update_positions()
        if closed_alerts and CHANNELS["logs"]:
            channel = bot.get_channel(CHANNELS["logs"])
            if channel:
                for alert in closed_alerts:
                    await channel.send(f"🔔 **TRADE CLOSED:**\n{alert}")
    except Exception as e:
        print(f"Portfolio Manager Error: {e}")

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
    try:
        count = await meme_engine.log_meme_data()
        if count and count > 0: print(f"🐶 Collected data on {count} new Solana coins.")
    except: pass

@tasks.loop(minutes=1)
async def meme_snipe_loop():
    try:
        await meme_engine.meme_snipe_loop()
    except: pass

@tasks.loop(hours=12) 
async def insider_scan_loop():
    if not CHANNELS["insider"]: return
    try:
        alerts = await market_intel.check_insider_trading()
        channel = bot.get_channel(CHANNELS["insider"])
        if channel and alerts:
            for alert in alerts[:5]: await channel.send(alert)
    except: pass

@tasks.loop(hours=24) 
async def smart_money_loop():
    if not CHANNELS["smart"]: return
    try:
        alerts = await market_intel.check_smart_money()
        channel = bot.get_channel(CHANNELS["smart"])
        if channel and alerts:
            for alert in alerts[:5]: await channel.send(alert)
    except: pass

# --- EVENTS ---
@bot.event
async def on_ready():
    print(f"✅ JCF HQ SYSTEM ONLINE: {bot.user.name}")
    if not signal_scan_loop.is_running(): signal_scan_loop.start()
    if not macro_news_loop.is_running(): macro_news_loop.start()
    if not whale_alert_loop.is_running(): whale_alert_loop.start()
    if not meme_scan_loop.is_running(): meme_scan_loop.start()
    if not insider_scan_loop.is_running(): insider_scan_loop.start()
    if not smart_money_loop.is_running(): smart_money_loop.start()
    if not portfolio_manager_loop.is_running(): portfolio_manager_loop.start()
    if not meme_snipe_loop.is_running(): meme_snipe_loop.start()
        
    if CHANNELS["status"]:
        channel = bot.get_channel(CHANNELS["status"])
        if channel:
            await channel.send("🟢 **SYSTEM ONLINE:** Neural Engine Ready.")

# --- COMMANDS ---

@bot.command(name="portfolio")
async def show_portfolio(ctx):
    """Shows active paper trades and virtual PnL."""
    msg = await ctx.send("🔄 Checking active trades...")
    total_pnl, report = await portfolio.generate_portfolio_report()
    
    color = 0x00ff00 if total_pnl >= 0 else 0xff0000
    embed = discord.Embed(title="💼 CEO Dashboard & Performance", color=color)
    embed.description = report
    if "No active positions" not in report:
        embed.add_field(name="Open PnL", value=f"**{total_pnl:+.2f}%**", inline=False)
    await msg.edit(content="", embed=embed)

@bot.command(name="status")
async def system_status(ctx):
    """Checks system health and data collection progress."""
    data_file = "/app/data/market_training_data.csv"
    row_count = 0
    if os.path.exists(data_file):
        try:
            with open(data_file, 'r') as f: row_count = sum(1 for _ in f) - 1
        except: pass
    
    embed = discord.Embed(title="🟢 SYSTEM STATUS: ONLINE", color=0x00ff00)
    embed.add_field(name="Latency", value=f"{bot.latency * 1000:.0f}ms", inline=True)
    embed.add_field(name="AI Data Collected", value=f"📊 {row_count} rows", inline=False)
    embed.set_footer(text=f"Engines: Swing, Scalp, Auto-Exit")
    await ctx.send(embed=embed)

@bot.command(name="risk")
async def calculate_risk(ctx, balance: float, entry: float, stop_loss: float):
    risk_1_pct = balance * 0.01
    risk_2_pct = balance * 0.02
    stop_distance = abs(entry - stop_loss)
    if stop_distance == 0: return
    units_1pct = risk_1_pct / stop_distance
    units_2pct = risk_2_pct / stop_distance
    embed = discord.Embed(title="🛡️ Risk Calculator", color=0x00d1ff)
    embed.add_field(name="Account", value=f"${balance:,.2f}", inline=False)
    embed.add_field(name="1% Risk", value=f"${risk_1_pct:.2f}\nUnits: {units_1pct:.2f}", inline=True)
    embed.add_field(name="2% Risk", value=f"${risk_2_pct:.2f}\nUnits: {units_2pct:.2f}", inline=True)
    await ctx.send(embed=embed)

# --- AI TRAINING COMMAND ---
@bot.command(name="train")
async def train_ai(ctx):
    """Forces the AI to retrain and reports the score."""
    await ctx.send("🧠 **Initiating AI Training Sequence...**\nThis may take a moment.")
    
    try:
        import ai_brain
        
        # Create a trap to catch the print() output
        capture_output = io.StringIO()
        sys.stdout = capture_output
        
        # Run the training
        await asyncio.to_thread(ai_brain.train_brain)
        
        # Reset stdout so logs go back to normal
        sys.stdout = sys.__stdout__
        
        # Get the text that was printed
        result_log = capture_output.getvalue()
        
        # Filter for the "Report Card" part
        if "EXAM RESULTS" in result_log:
            # Extract just the score part
            report_card = result_log.split("--- 🎓 EXAM RESULTS ---")[1]
            await ctx.send(f"✅ **Training Complete!**\n\n**🎓 REPORT CARD:**{report_card}")
        else:
            # Fallback if it can't find the score
            await ctx.send(f"✅ **Training Complete!** (Check logs for details)\n\nRaw Output:\n{result_log[-500:]}")

    except Exception as e:
        # Reset stdout just in case it crashed
        sys.stdout = sys.__stdout__
        await ctx.send(f"❌ **Training Failed:** {str(e)}")

# --- LAUNCH ---
if __name__ == "__main__":
    if not TOKEN:
        print("❌ ERROR: DISCORD_TOKEN is missing!")
    else:
        bot.run(TOKEN)