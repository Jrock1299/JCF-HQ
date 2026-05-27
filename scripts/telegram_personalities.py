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
    'oracle':   '\U0001f52e',   # 🔮
    'jerry':    '\U0001f4ca',   # 📊
    'lens':     '\U0001f310',   # 🌐
    'norman':   '⚠️', # ⚠️
    'tao':      '☯️', # ☯️
}

SEP = '━' * 22  # ━━━━━━━━━━━━━━━━━━━━━━


def wrap_message(agent: str, body: str) -> str:
    """Wrap an agent message in the standard JCF HQ Telegram format.

    Args:
        agent: Agent name (lowercase). Use 'huncho' for system messages.
        body:  The message content (already written in the agent's voice).

    Returns:
        Formatted string ready to send via Telegram.
    """
    agent_lower = agent.lower().strip()
    emoji = AGENT_EMOJIS.get(agent_lower, '')
    name = agent_lower.upper()

    if agent_lower == 'huncho':
        return f'{SEP}\n{emoji} HUNCHO\n{SEP}\n{body}\n{SEP}'

    header = f'{SEP}\n{emoji} {name}\n{SEP}'
    footer = f'\n— reported to H\n{SEP}'
    return f'{header}\n{body}{footer}'
