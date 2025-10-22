import os
os.environ["DISCORD_NO_AUDIO"] = "1"

import json
import discord
from discord.ext import commands
from datetime import datetime
from aiohttp import web

# === ENV ===
TOKEN = os.getenv("DISCORD_TOKEN")
ANNOUNCE_CHANNEL_ID = int(os.getenv("ANNOUNCE_CHANNEL_ID", "0"))
CRYPTO_SETUPS_CHANNEL_ID = int(os.getenv("CRYPTO_SETUPS_CHANNEL_ID", "0"))
STOCK_SETUPS_CHANNEL_ID  = int(os.getenv("STOCK_SETUPS_CHANNEL_ID", "0"))
FEED_SECRET = os.getenv("FEED_SECRET", "")
PORT = int(os.getenv("PORT", "8080"))

# === BOT ===
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

def build_embed(title: str, fields: list[tuple[str,str,bool]], color: int = 0x00D084) -> discord.Embed:
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

# --- Simple sanity command ---
@bot.command()
async def ping(ctx):
    await ctx.reply("Pong 🏓")

# --- Optional test posts ---
@bot.command()
async def testcrypto(ctx):
    ch = bot.get_channel(CRYPTO_SETUPS_CHANNEL_ID)
    if not ch:
        return await ctx.reply("❌ CRYPTO_SETUPS_CHANNEL_ID not accessible.")
    fields = [
        ("Asset","**BTC/USDT**",True),
        ("Signal","**BUY/LONG**",True),
        ("Entry","`{{close}}`",False),
    ]
    await ch.send(embed=build_embed("🎯 CRYPTO – Sample", fields))
    await ctx.reply("✅ Crypto test posted.")

@bot.command()
async def teststock(ctx):
    ch = bot.get_channel(STOCK_SETUPS_CHANNEL_ID)
    if not ch:
        return await ctx.reply("❌ STOCK_SETUPS_CHANNEL_ID not accessible.")
    fields = [
        ("Ticker","**MSTR**",True),
        ("Signal","**Breakout/Retest**",True),
        ("Entry","`$000.00`",False),
    ]
    await ch.send(embed=build_embed("📈 STOCK – Sample", fields, color=0x2D7DFA))
    await ctx.reply("✅ Stock test posted.")

# --- AIOHTTP webhook server (/tv) ---
async def handle_tv(request: web.Request):
    # Basic auth via secret (header or body)
    supplied = request.headers.get("X-Auth-Token")
    data = None
    if not supplied:
        try:
            data = await request.json()
            supplied = data.get("secret")
        except Exception:
            return web.Response(status=400, text="Bad JSON")

    if FEED_SECRET and supplied != FEED_SECRET:
        return web.Response(status=401, text="Unauthorized")

    if data is None:
        try:
            data = await request.json()
        except Exception:
            return web.Response(status=400, text="Bad JSON")

    feed_type = (data.get("type") or "").lower()
    title = data.get("title", "TradingView Alert")
    color = int(data.get("color", "0x00D084"), 16)
    fields_in = data.get("fields", [])

    fields = []
    for f in fields_in:
        fields.append((f.get("name","Info"), f.get("value","N/A"), bool(f.get("inline", False))))

    # Route
    channel_id = None
    if feed_type == "crypto_setup":
        channel_id = CRYPTO_SETUPS_CHANNEL_ID
    elif feed_type == "stock_setup":
        channel_id = STOCK_SETUPS_CHANNEL_ID
    else:
        return web.Response(status=400, text="Unknown type")

    ch = bot.get_channel(channel_id)
    if not ch:
        return web.Response(status=404, text="Channel not found")

    await ch.send(embed=build_embed(title, fields, color=color))
    return web.json_response({"ok": True})

async def start_web_app():
    app = web.Application()
    app.router.add_post("/tv", handle_tv)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"🌐 Webhook server listening on /tv (port {PORT})")

@bot.event
async def setup_hook():
    # Launch the web server alongside the Discord bot
    bot.loop.create_task(start_web_app())

bot.run(TOKEN)
