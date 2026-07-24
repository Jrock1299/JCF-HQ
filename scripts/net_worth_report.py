#!/usr/bin/env python3
"""
net_worth_report.py — daily net-worth snapshot for Discord #net-worth (+ Telegram).

Computes REAL net worth from the live account feeds and shows PAPER (Alpaca)
separately — paper money is not net worth. Stale/unwired feeds (Plaid, Mercury)
are flagged, never silently counted. Posts via discord_notify (no-op until the
#net-worth webhook exists) and Telegram.

Cadence: daily, 11:00 UTC (before US open). Cron held until the webhook is set.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, '/root/.openclaw/scripts')
try:
    from discord_notify import notify as discord_notify
except Exception:
    discord_notify = None

DASH = Path('/root/.openclaw/dashboard')
TELEGRAM_TOKEN   = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_ALERT_CHAT_ID') or os.getenv('TELEGRAM_CHAT_ID')
STALE_DAYS = 5


def _load(name):
    try:
        return json.loads((DASH / name).read_text())
    except Exception:
        return {}


def _age_days(name):
    try:
        return (datetime.now(timezone.utc).timestamp() - (DASH / name).stat().st_mtime) / 86400
    except Exception:
        return 9999


def build():
    real = []       # (label, value, note)
    rh = _load('robinhood_data.json')
    real.append(('Robinhood', float(rh.get('total_equity', 0) or 0), ''))
    real.append(('Kraken', float(_load('kraken_data.json').get('total_usd', 0) or 0), ''))
    real.append(('TrustWallet', float(_load('trustwallet_data.json').get('total_usd', 0) or 0), ''))

    nw = _load('net_worth.json')
    for k, label in (('hysa', 'HYSA'), ('life_insurance', 'Life insurance')):
        v = float(nw.get(k, 0) or 0)
        if v:
            real.append((label, v, 'manual'))

    # Banks (Plaid) — only count if fresh
    plaid = _load('plaid_data.json')
    p_total = sum(float(a.get('balance', 0) or 0) for a in plaid.get('accounts', []) if isinstance(a, dict))
    if _age_days('plaid_data.json') <= STALE_DAYS and p_total:
        real.append(('Banks (Plaid)', p_total, ''))
    else:
        real.append(('Banks (Plaid)', 0, f'STALE/UNWIRED — last {_age_days("plaid_data.json"):.0f}d ago'))
    merc = _load('mercury_data.json')
    if float(merc.get('balance', 0) or 0) > 0:
        real.append(('Mercury', float(merc['balance']), ''))

    total_real = sum(v for _, v, _ in real)
    paper = float(_load('jerry_portfolio.json').get('balance', 0) or 0)
    goal = float(nw.get('goal', 0) or 0)

    lines = ['💰 NET WORTH — ' + datetime.now(timezone.utc).strftime('%Y-%m-%d'),
             f"Total (real): ${total_real:,.0f}", '']
    for label, v, note in real:
        tag = f"  ({note})" if note else ''
        lines.append(f"  • {label:14} ${v:,.0f}{tag}")
    lines.append('')
    lines.append(f"Paper (NOT net worth): Alpaca ${paper:,.0f}")
    lines.append(f"P&L today ${float(nw.get('pnl_today',0) or 0):,.0f} | "
                 f"MTD ${float(nw.get('pnl_month',0) or 0):,.0f} | "
                 f"YTD ${float(nw.get('pnl_ytd',0) or 0):,.0f}")
    if goal:
        lines.append(f"Goal ${goal:,.0f} — {100*total_real/goal:.1f}%")
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
            print(f'[networth] Telegram error: {e}')
    if discord_notify:
        try:
            print('[networth] Discord:', discord_notify('huncho', body, channels=['NET_WORTH']))
        except Exception as e:
            print(f'[networth] Discord skipped: {e}')


if __name__ == '__main__':
    main()
