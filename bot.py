import os
import discord
from discord.ext import commands
from aiohttp import web
import asyncio

# === Environment Variables ===
TOKEN = os.getenv("DISCORD_TOKEN")
ANNOUNCE_CHANNEL_ID = int(os.getenv("ANNOUNCE_CHANNEL_ID", 0))
CRYPTO_SETUPS_CHANNEL_ID = int(os.getenv("CRYPTO_SETUPS_CHANNEL_ID", 0))
STOCK_SETUPS_CHANNEL_ID = int(os.getenv("STOCK_SETUPS_CHANNEL_ID", 0))
FEED_SECRET = os.getenv("FEED_SECRET", "")
PORT = int(os.getenv("PORT", 8080))

# === Discord Setup ===
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# === Web Server Setup (for TradingView Webhooks) ===
app = web.Application()

async def handle_tv(request):
    try:
        data = await request.json()
    except Exception:
        return web.Response(text="Invalid JSON", status=400)

    secret = data.get("secret")
    if secret != FEED_SECRET:
        return web.Response(text="Unauthorized", status=401)

    signal_type = data.get("type", "")
    title = data.get("title", "TradingView Alert")
    color = int(data.get("color", "0x00FFFF"), 16)
    fields = data.get("fields", [])

    # Determine channel based on signal type
    channel_id = None
    if signal_type == "crypto_setup":
        channel_id = CRYPTO_SETUPS_CHANNEL_ID
    elif signal_type == "stock_setup":
        channel_id = STOCK_SETUPS_CHANNEL_ID

    if channel_id:
        channel = bot.get_channel(channel_id)
        if channel:
            embed = discord.Embed(title=title, color=color)
            for f in fields:
                embed.add_field(
                    name=f.get("name", "Info"),
                    value=f.get("value", "N/A"),
                    inline=f.get("inline", False)
                )
            await channel.send(embed=embed)
            print(f"✅ Sent alert to {channel.name}")
        else:
            print(f"⚠️ Channel not found for ID {channel_id}")
    else:
        print(f"⚠️ Unknown signal type: {signal_type}")

    return web.Response(text="ok", status=200)

app.add_routes([web.post('/tv', handle_tv)])

# === Discord Events ===
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (id: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="JCF HQ online"))
    if ANNOUNCE_CHANNEL_ID:
        ch = bot.get_channel(ANNOUNCE_CHANNEL_ID)
        if ch:
            await ch.send("✅ **JCFWatchBot ONLINE** — Systems initialized. Monitoring markets…")
    print(f"🌐 Webhook server listening on /tv (port {PORT})")

# === Commands ===
@bot.command()
async def ping(ctx):
    await ctx.reply("Pong 🏓")

# === Run both Discord bot and webhook server ===
async def main():
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    await bot.start(TOKEN)

asyncio.run(main())
