"""
telegram_personalities.py — Shared Telegram message wrapper for JCF HQ agents.

Wraps every outgoing Telegram message in the agent's personality voice
with Huncho's framing. Telegram-only — no changes to JSON, logs, or trading logic.

Usage:
    from telegram_personalities import wrap_message

    # Wrap any agent message before sending:
    wrapped = wrap_message('blade', raw_message)
    send_telegram(wrapped)

    # Huncho's own system messages:
    wrapped = wrap_message('huncho', "Everything's runnin' smooth tonight.")
"""

AGENT_EMOJIS = {
    'huncho':   '\U0001f451',   # 👑
    'victoria': '\U0001f9db‍♀️',  # 🧛‍♀️
    'lucy':     '\U0001f50d',   # 🔍
    'blade':    '\U0001f52a',   # 🔪
    'edge':     '\U0001f4e1',   # 📡
    'strategist': '♟️',  # legacy key — display as JARVIS
    'jarvis':   '♟️',  # ♟️ — Jarvis (the Strategist; right-hand-man)
    'jerry':    '\U0001f4ca',   # 📊
    'lens':     '\U0001f310',   # 🌐
    'norman':   '⚠️', # ⚠️
    'tao':      '☯️', # ☯️
    'crisp':    '🏎️', # 🏎️ — Chad (internal id 'crisp'; meme-coin hunter)
}

# Aliases — agent IDs that should display as a different NAME header.
AGENT_DISPLAY = {
    'strategist': 'JARVIS',     # internal id 'strategist' renders as JARVIS
    'crisp':      'Chad',       # internal id 'crisp' renders as Chad (meme-coin pivot)
}

def wrap_message(agent: str, body: str) -> str:
    """Wrap an agent message in the standard JCF HQ Telegram format.

    Format:
        {emoji} {NAME}
        {body}
        — via H        (omitted for Huncho — his messages already sign off with — H)
    """
    agent_lower = agent.lower().strip()
    emoji = AGENT_EMOJIS.get(agent_lower, '')
    name = AGENT_DISPLAY.get(agent_lower, agent_lower.upper())

    if agent_lower == 'huncho':
        return f'{emoji} HUNCHO\n{body}'

    return f'{emoji} {name}\n{body}\n— via H'
