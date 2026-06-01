#!/bin/bash
# session_prep_ping.sh — Send pre-session Telegram ping via Huncho,
# now augmented with an automated 4H technical read on the session's instruments.
#
# Usage:
#   bash session_prep_ping.sh ASIA
#   bash session_prep_ping.sh LONDON
#   bash session_prep_ping.sh NY_OPEN
#   bash session_prep_ping.sh NY_PM

set -a
source /etc/environment 2>/dev/null
source /root/.openclaw/.env 2>/dev/null
set +a

SESSION="${1:-UNKNOWN}"

python3 - "$SESSION" << 'PYEOF'
import sys
import os
import requests

sys.path.insert(0, '/root/.openclaw/scripts')
from telegram_personalities import wrap_message

# Map session → instruments (mirror blade_bot.SESSION_INSTRUMENTS).
SESSION_INSTRUMENTS = {
    'ASIA':    ['SPX500_USD'],
    'LONDON':  ['SPX500_USD', 'DE30_EUR', 'CHF_JPY'],
    'NY_OPEN': ['SPX500_USD'],
    'NY_PM':   ['SPX500_USD'],
}

SESSION_MESSAGES = {
    'ASIA':    "Aye. ASIA opens in 10 minutes.",
    'LONDON':  "Aye. LONDON opens in 10 minutes.",
    'NY_OPEN': "Aye. NY OPEN in 10 minutes. This one's all you — manual trades only.",
    'NY_PM':   "Aye. NY PM opens in 10 minutes.",
}

session = sys.argv[1] if len(sys.argv) > 1 else 'UNKNOWN'
instruments = SESSION_INSTRUMENTS.get(session, [])

intro = SESSION_MESSAGES.get(session, f"Aye. {session} opens in 10 minutes.")

# Generate a 4H read for each session instrument
h4_blocks = []
try:
    from h4_read import generate_h4_read
    for inst in instruments:
        try:
            r = generate_h4_read(inst)
            narrative = r.get('narrative') or r.get('error') or 'no read available'
            label = inst.split('_')[0]
            h4_blocks.append(f"━━ {label} 4H read ━━\n{narrative}")
        except Exception as e:
            print(f'[session_prep] h4_read({inst}) failed: {e}', file=sys.stderr)
except Exception as e:
    print(f'[session_prep] h4_read import failed: {e}', file=sys.stderr)

body_parts = [intro]
if h4_blocks:
    body_parts.append("")
    body_parts.append("Got my desk to pull a 4H read on the instruments:")
    body_parts.append("")
    body_parts.extend(h4_blocks)
    body_parts.append("")
body_parts.append("Send me a chart if you want my guy to look at something specific. — H")

msg = wrap_message('huncho', '\n'.join(body_parts))

token   = os.environ.get('TELEGRAM_BOT_TOKEN', '')
chat_id = os.environ.get('TELEGRAM_ALERT_CHAT_ID') or os.environ.get('TELEGRAM_CHAT_ID', '')
if not token or not chat_id:
    print(f'[session_prep] Telegram not configured — skipping {session} ping')
    sys.exit(0)

try:
    r = requests.post(
        f'https://api.telegram.org/bot{token}/sendMessage',
        json={'chat_id': chat_id, 'text': msg},
        timeout=30,
    )
    r.raise_for_status()
    print(f'[session_prep] {session} ping sent with {len(h4_blocks)} 4H read(s)')
except Exception as e:
    print(f'[session_prep] Telegram error: {e}')
PYEOF
