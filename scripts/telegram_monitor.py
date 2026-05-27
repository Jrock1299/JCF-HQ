#!/root/.openclaw/venv/bin/python
import os
import re
import json
import time
import requests
from datetime import datetime, timezone
from telethon import TelegramClient, events

SESSION_PATH = "/root/.openclaw/scripts/telegram_session"
PICKS_FEED = "/root/.openclaw/agents/oracle/bot/picks_feed.json"

KEYWORDS = ["play", "lock", "fade", "bet", "units", "unit", "ml", "spread", "over", "under"]
ODDS_PATTERN = re.compile(r"(\+\d{2,4}|-\d{2,4})")


def load_env():
    try:
        with open("/etc/environment", "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                v = v.strip().strip('"')
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass


def looks_like_pick(text: str) -> bool:
    t = (text or "").lower()
    if any(k in t for k in KEYWORDS):
        return True
    if ODDS_PATTERN.search(t):
        return True
    return False


def send_alert(message: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_ALERT_CHAT_ID") or "797062420"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True}
    requests.post(url, json=payload, timeout=20)


def append_pick(entry: dict):
    os.makedirs(os.path.dirname(PICKS_FEED), exist_ok=True)
    if os.path.exists(PICKS_FEED):
        try:
            with open(PICKS_FEED, "r") as f:
                data = json.load(f)
                if not isinstance(data, list):
                    data = []
        except Exception:
            data = []
    else:
        data = []
    data.append(entry)
    with open(PICKS_FEED, "w") as f:
        json.dump(data, f, indent=2)


def format_alert(channel: str, text: str) -> str:
    snippet = text.strip()
    if len(snippet) > 1200:
        snippet = snippet[:1200] + "…"
    return f"<b>Pick Alert</b>\n<b>Source:</b> {channel}\n\n{snippet}"


def main():
    load_env()
    api_id = os.environ.get("TELEGRAM_API_ID")
    api_hash = os.environ.get("TELEGRAM_API_HASH")
    phone = os.environ.get("TELEGRAM_PHONE")

    if not api_id or not api_hash or not phone:
        raise RuntimeError("Missing TELEGRAM_API_ID / TELEGRAM_API_HASH / TELEGRAM_PHONE in /etc/environment")

    client = TelegramClient(SESSION_PATH, int(api_id), api_hash)

    @client.on(events.NewMessage)
    async def handler(event):
        if not event.message:
            return
        text = event.message.message or ""
        if not looks_like_pick(text):
            return

        chat = await event.get_chat()
        channel = getattr(chat, 'title', None) or getattr(chat, 'username', None) or str(getattr(chat, 'id', 'unknown'))

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": channel,
            "text": text,
            "message_id": event.message.id,
        }
        append_pick(entry)
        send_alert(format_alert(channel, text))

    # Login and run
    client.start(phone=phone)
    client.run_until_disconnected()


if __name__ == "__main__":
    main()
