import requests
import os
import sys
import json
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '/root/.openclaw/scripts')
from morning_dashboard import parse_trades, get_yesterday, CRISP_LOG, BLADE_LOG

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')

def load_env():
    try:
        with open('/etc/environment') as f:
            for line in f:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass

def write_morning_report_to_hq(report_text, summary_line):
    load_env()
    payload = {
        "date": datetime.now(timezone.utc).strftime("%b %d, %Y · %I:%M %p UTC"),
        "summary": summary_line,
        "text": report_text
    }
    path = "/root/.openclaw/dashboard/morning_report.json"
    with open(path, "w") as f:
        json.dump(payload, f)
    print(f"Morning report written to {path}")

def get_chat_id():
    return 797062420

def send_message(chat_id, text):
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
    r = requests.post(url, data={'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'})
    return r.json()

def format_trading_report(trades):
    closed = [t for t in trades if t.get('status') == 'CLOSED']
    wins = [t for t in closed if t.get('result') == 'WIN']
    losses = [t for t in closed if t.get('result') == 'LOSS']
    total_pnl = sum(t['pnl'] for t in closed)
    win_rate = (len(wins) / len(closed) * 100) if closed else 0
    pnl_sign = '+' if total_pnl >= 0 else ''

    lines = [
        '⚡ *Yesterday\'s Trades — Crisp & Blade*',
        f'P&L: `{pnl_sign}${total_pnl:.2f}` | Trades: `{len(closed)}` | Win Rate: `{win_rate:.0f}%` ({len(wins)}W/{len(losses)}L)',
        '',
    ]

    if closed:
        for t in closed[-10:]:
            pnl = t.get('pnl', 0)
            pnl_str = f'+${pnl:.2f}' if pnl >= 0 else f'-${abs(pnl):.2f}'
            icon = '✅' if t.get('result') == 'WIN' else ('❌' if t.get('result') == 'LOSS' else '⏳')
            lines.append(f'{icon} `{t["agent"]}` {t["symbol"]} — `{pnl_str}`')
    else:
        lines.append('_No trades logged overnight_')

    return '\n'.join(lines)

def format_oracle_yesterday_report():
    record_path = '/root/.openclaw/agents/oracle/bot/oracle_record.json'
    bankroll_path = '/root/.openclaw/dashboard/oracle_bankroll.json'

    try:
        with open(record_path) as f:
            all_picks = json.load(f).get('picks', [])
    except Exception:
        all_picks = []

    try:
        with open(bankroll_path) as f:
            bankroll = json.load(f)
    except Exception:
        bankroll = {}

    today = datetime.now(timezone.utc).date()
    yesterday = get_yesterday()

    yesterday_picks = [p for p in all_picks if p.get('logged_at', '').startswith(str(yesterday))]
    today_upcoming = [p for p in all_picks
                      if p.get('commence', '').startswith(str(today)) and p.get('result') == 'pending']

    balance = bankroll.get('balance', bankroll.get('bankroll', 0))
    starting = bankroll.get('starting', 500)
    all_time_pnl = balance - starting
    pnl_sign = '+' if all_time_pnl >= 0 else ''

    lines = ['🔮 *Oracle — Yesterday\'s Picks*', '']
    lines.append(f'💰 Bankroll: `${balance:.2f}` ({pnl_sign}${all_time_pnl:.2f} all-time)')
    lines.append('')

    if yesterday_picks:
        wins = [p for p in yesterday_picks if p.get('result') == 'win']
        losses = [p for p in yesterday_picks if p.get('result') == 'loss']
        pending = [p for p in yesterday_picks if p.get('result') == 'pending']
        day_pnl = sum(p.get('pnl') or 0 for p in yesterday_picks)
        day_pnl_str = ('+' if day_pnl >= 0 else '') + f'${day_pnl:.2f}'
        lines.append(f'📅 *{yesterday.strftime("%b %d")}*: {len(yesterday_picks)} picks — '
                     f'{len(wins)}W / {len(losses)}L / {len(pending)} pending | `{day_pnl_str}`')
        for p in yesterday_picks[:8]:
            result = p.get('result', 'pending')
            icon = '✅' if result == 'win' else ('❌' if result == 'loss' else '⏳')
            pick = p.get('pick', 'Unknown')
            sport = p.get('sport', '')
            odds = p.get('odds_at_log', '')
            pnl_amt = p.get('pnl')
            pnl_part = f' `{("+" if pnl_amt >= 0 else "")}${pnl_amt:.2f}`' if pnl_amt is not None else ''
            lines.append(f'{icon} {pick} ({sport} {odds}){pnl_part}')
    else:
        lines.append(f'_No picks logged on {yesterday.strftime("%b %d")}_')

    if today_upcoming:
        lines.append('')
        lines.append(f'🎯 *Today\'s Upcoming ({len(today_upcoming)} picks)*')
        for p in today_upcoming[:6]:
            pick = p.get('pick', 'Unknown')
            sport = p.get('sport', '')
            odds = p.get('odds_at_log', '')
            try:
                game_dt = datetime.fromisoformat(p.get('commence', '').replace('Z', '+00:00'))
                time_str = game_dt.strftime('%H:%M UTC')
            except Exception:
                time_str = ''
            lines.append(f'⏰ {pick} ({sport} {odds}) — {time_str}')

    return '\n'.join(lines)


if __name__ == '__main__':
    chat_id = get_chat_id()
    if not chat_id:
        print("Could not get chat ID")
        sys.exit(1)

    print(f"Sending morning report to chat_id: {chat_id}")

    yesterday = get_yesterday()
    all_trades = parse_trades(CRISP_LOG, 'Crisp', yesterday) + parse_trades(BLADE_LOG, 'Blade', yesterday)

    now = datetime.now(timezone.utc).strftime('%b %d · %I:%M %p UTC')

    send_message(chat_id, f'📊 *Morning Report — {now}*')

    trading_text = format_trading_report(all_trades)
    send_message(chat_id, trading_text)

    oracle_text = format_oracle_yesterday_report()
    send_message(chat_id, oracle_text)

    send_message(chat_id, "That's the overnight brief. Lmk if you want to dig deeper. 🤝")

    full_report_text = trading_text + '\n\n' + oracle_text
    write_morning_report_to_hq(full_report_text, "Crisp · Blade · Oracle — Daily Briefing")

    print("Done!")
