import os
import discord
from discord.ext import commands

TOKEN = os.getenv("DISCORD_TOKEN")
ANNOUNCE_CHANNEL_ID = 1426896804842311787  # JCF HQ Channel

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (id: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="JCF HQ online"))
    ch = bot.get_channel(ANNOUNCE_CHANNEL_ID)
    if ch:
        await ch.send("✅ **JCFWatchBot ONLINE** — Systems initialized. Monitoring markets…")
    print("✅ Startup message sent (if channel set).")

@bot.command()
async def ping(ctx):
    await ctx.reply("Pong 🏓")

bot.run(TOKEN)
