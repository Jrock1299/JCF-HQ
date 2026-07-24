"""
bot.py — JCF HQ two-way Discord bot ("Hunxho Bot").

Listens ONLY on #ask-the-team and #risk-calculator (scoped by channel id) and
replies as the relevant JCF HQ agents:

  #ask-the-team    -> fanout.answer(): each relevant agent replies in its own
                      voice, posted under that agent's name+avatar.
  #risk-calculator -> risk_calc.norman_reply(): Norman grades the risk, tone
                      varying by the framing (quick-money vs disciplined).

Identity: the bot's own login is used ONLY for listening. Every visible reply
goes out through a channel webhook with a per-message username+avatar override
(reusing scripts/discord_notify.py's _DISPLAY/_avatar_url), so replies appear
to come from Norman, Lens, Victoria, Blade, Jarvis, etc. — never the bot's
generic identity.

Webhooks are channel-bound, so the bot creates (once) or reuses a webhook named
WEBHOOK_NAME in each of the two interaction channels. Requires the Manage
Webhooks permission and the privileged Message Content intent (see setup docs).

Run:  bash agents/discord_bot/run_bot.sh   (sources .env, uses the openclaw venv)
"""
import asyncio
import os
import sys
import traceback

sys.path.insert(0, '/root/.openclaw/scripts')
sys.path.insert(0, os.path.dirname(__file__))

import discord

import discord_notify
from discord_notify import _DISPLAY, _avatar_url, post_webhook
import fanout
import risk_calc

TOKEN = os.getenv('DISCORD_BOT_TOKEN', '').strip()
ASK_TEAM_ID = int(os.getenv('DISCORD_ASK_TEAM_CHANNEL_ID', '0') or 0)
RISK_CALC_ID = int(os.getenv('DISCORD_RISK_CALC_CHANNEL_ID', '0') or 0)
RISK_USE_LLM = os.getenv('DISCORD_RISK_USE_LLM', '0') == '1'
WEBHOOK_NAME = 'JCF HQ Agents'

WATCHED = {ASK_TEAM_ID, RISK_CALC_ID} - {0}

intents = discord.Intents.default()
intents.message_content = True          # privileged — must be enabled in portal
client = discord.Client(intents=intents)

# channel id -> webhook url (populated on_ready)
_WEBHOOKS = {}


# Explicit webhook URLs (Path B): if set, the bot posts to these directly and
# needs NO Manage Webhooks permission. Overrides auto-create for that channel.
_EXPLICIT_WEBHOOK = {
    ASK_TEAM_ID: os.getenv('DISCORD_ASK_TEAM_WEBHOOK', '').strip(),
    RISK_CALC_ID: os.getenv('DISCORD_RISK_CALC_WEBHOOK', '').strip(),
}


async def ensure_webhook(channel):
    """Return a webhook URL for `channel`.

    Path B: an explicit DISCORD_*_WEBHOOK env var (no permission needed).
    Path A: auto-create/reuse a webhook in the channel (needs Manage Webhooks).
    """
    explicit = _EXPLICIT_WEBHOOK.get(channel.id)
    if explicit:
        print(f'[bot] using explicit webhook for #{channel} ({channel.id})')
        return explicit
    try:
        hooks = await channel.webhooks()
        for h in hooks:
            if h.name == WEBHOOK_NAME and h.token:
                return h.url
        hook = await channel.create_webhook(name=WEBHOOK_NAME,
                                            reason='JCF HQ agent replies')
        return hook.url
    except discord.Forbidden:
        print(f'[bot] MISSING Manage Webhooks in #{channel} ({channel.id}) — '
              f'cannot post agent-identity replies there.')
        return None
    except Exception as e:
        print(f'[bot] webhook setup error in {channel.id}: {e}')
        return None


@client.event
async def on_ready():
    print(f'[bot] logged in as {client.user} (id {client.user.id})')
    if not WATCHED:
        print('[bot] WARNING: no channel ids configured — set '
              'DISCORD_ASK_TEAM_CHANNEL_ID / DISCORD_RISK_CALC_CHANNEL_ID.')
    for cid in WATCHED:
        ch = client.get_channel(cid)
        if ch is None:
            print(f'[bot] WARNING: channel {cid} not visible — is the bot '
                  f'invited to the server with View Channel there?')
            continue
        url = await ensure_webhook(ch)
        if url:
            _WEBHOOKS[cid] = url
            print(f'[bot] ready on #{ch} ({cid})')
    print(f'[bot] watching {len(_WEBHOOKS)}/{len(WATCHED)} channels.')


def _post_as(cid, agent, text):
    """Blocking: post `text` to the channel webhook as `agent` (name+avatar)."""
    url = _WEBHOOKS.get(cid)
    if not url:
        print(f'[bot] no webhook for channel {cid}; dropping reply from {agent}')
        return
    post_webhook(url, text,
                 username=_DISPLAY.get(agent, agent.upper()),
                 avatar_url=_avatar_url(agent))


def _handle_ask_team(cid, question):
    replies = fanout.answer(question)
    if not replies:
        _post_as(cid, 'huncho', "Nobody's got a read on that one right now. — H")
        return
    for agent, text in replies:
        _post_as(cid, agent, text)


def _handle_risk_calc(cid, message_text):
    reply = risk_calc.norman_reply(message_text, use_llm=RISK_USE_LLM)
    _post_as(cid, 'norman', reply)


@client.event
async def on_message(msg):
    # Ignore the bot itself, other bots, and webhook posts (prevents loops).
    if msg.author.bot or msg.webhook_id is not None:
        return
    if msg.channel.id not in _WEBHOOKS:
        return
    content = (msg.content or '').strip()
    if not content:
        # Almost always means Message Content intent is off.
        print('[bot] empty message content — is the Message Content intent on?')
        return

    loop = asyncio.get_running_loop()
    try:
        async with msg.channel.typing():
            if msg.channel.id == ASK_TEAM_ID:
                await loop.run_in_executor(None, _handle_ask_team,
                                           msg.channel.id, content)
            elif msg.channel.id == RISK_CALC_ID:
                await loop.run_in_executor(None, _handle_risk_calc,
                                           msg.channel.id, content)
    except Exception:
        print('[bot] handler error:\n' + traceback.format_exc())


def main():
    if not TOKEN:
        sys.exit('[bot] DISCORD_BOT_TOKEN not set — source .env first.')
    client.run(TOKEN, log_handler=None)


if __name__ == '__main__':
    main()
