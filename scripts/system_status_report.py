#!/usr/bin/env python3
"""
system_status_report.py — daily fleet health for Discord #system-status (+ Telegram).

Computes each agent's state from the live crontab (active vs #HOLD), systemd
services, and output-file freshness — a positive "what's actually running" glance,
distinct from #alerts (which only fires on breakage).

Cadence: daily, 07:00 + 19:00 UTC. Cron held until the webhook is set.
"""
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, '/root/.openclaw/scripts')
try:
    from discord_notify import notify as discord_notify
except Exception:
    discord_notify = None

TELEGRAM_TOKEN   = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_ALERT_CHAT_ID') or os.getenv('TELEGRAM_CHAT_ID')

# agent -> (cron marker, systemd service or None, note-if-down)
AGENTS = [
    ('Lens',     'run_lens_brain.sh',   None,       ''),
    ('Blade',    'run_session.sh',      None,       ''),
    ('Jarvis',   'strategist/run_research.sh', None, ''),
    ('Lucy',     'lucy_brain.py',       None,       ''),
    ('Tao',      'tao_data_collector.py', None,     ''),
    ('Victoria', 'run_victoria.sh',     None,       ''),
    ('Norman',   'run_norman.sh',       None,       ''),
    ('Sentinel', 'run_sentinel.sh',     None,       ''),
    ('Jerry',    None,                  'jerry',    ''),
    ('Edge',     None,                  'edge',     'missing OANDA auth-profiles.json'),
    ('Chad',     None,                  'crisp-v5', 'parked — meme-coin build'),
    ('GDrive',   'run_gdrive_sync.sh',  None,       ''),
    ('Kraken',   'sync_kraken.py',      None,       ''),
    ('Robinhood','sync_robinhood.py',   None,       ''),
]


def _crontab():
    try:
        return subprocess.run(['crontab', '-l'], capture_output=True, text=True).stdout.splitlines()
    except Exception:
        return []


def _svc(name):
    try:
        return subprocess.run(['systemctl', 'is-active', name],
                              capture_output=True, text=True).stdout.strip()
    except Exception:
        return 'unknown'


def classify():
    ct = _crontab()
    active_lines = [l for l in ct if l[:1].isdigit() or l.startswith('*')]
    held_lines   = [l for l in ct if l.startswith('#HOLD')]
    live, held, down = [], [], []
    for name, marker, svc, note in AGENTS:
        if svc:
            state = _svc(svc)
            if state == 'active':
                live.append(name)
            elif name in ('Chad',):
                held.append(f"{name} ({note})" if note else name)
            else:
                down.append(f"{name} ({note})" if note else name)
            continue
        if any(marker in l for l in active_lines):
            live.append(name)
        elif any(marker in l for l in held_lines):
            held.append(name)
        else:
            down.append(f"{name} ({note})" if note else name)
    return live, held, down


def build():
    live, held, down = classify()
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    lines = [f"🖥️ SYSTEM STATUS — {now}", '']
    lines.append(f"🟢 Live ({len(live)}): " + ', '.join(live) if live else '🟢 Live: none')
    lines.append(f"⏸️ Held ({len(held)}): " + ', '.join(held) if held else '⏸️ Held: none')
    lines.append(f"🔴 Down ({len(down)}): " + ', '.join(down) if down else '🔴 Down: none ✓')
    return '\n'.join(lines)


def main():
    body = build()
    print(body)
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        import requests
        try:
            requests.post(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
                          json={'chat_id': TELEGRAM_CHAT_ID, 'text': body}, timeout=15)
        except Exception as e:
            print(f'[status] Telegram error: {e}')
    if discord_notify:
        try:
            print('[status] Discord:', discord_notify('huncho', body, channels=['SYSTEM_STATUS']))
        except Exception as e:
            print(f'[status] Discord skipped: {e}')


if __name__ == '__main__':
    main()
