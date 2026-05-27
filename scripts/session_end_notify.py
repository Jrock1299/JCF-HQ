#!/usr/bin/env python3
"""
session_end_notify.py — Unified session-end notification cron

Reads trade history from Blade (agent_trades.json) and Edge (trade_history.json),
builds a single consolidated Telegram message for the session.

Replaces per-agent session_notify.session_end() calls — both agents write to
their trade files; this script reads and consolidates at session close time.

Usage:
  python3 session_end_notify.py ASIA
  python3 session_end_notify.py LONDON
  python3 session_end_notify.py NY
  python3 session_end_notify.py NY_PM

Cron schedule (UTC, weekdays):
  0  6  * * 1-5  → ASIA end
  30 13 * * 1-5  → LONDON end
  30 17 * * 1-5  → NY end
  0  21 * * 1-5  → NY_PM end
"""

import sys
import json
import os
import requests
from datetime import datetime, timezone
import sys
sys.path.insert(0, "/root/.openclaw/scripts")
from telegram_personalities import wrap_message

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
CHAT_ID   = os.environ.get('TELEGRAM_CHAT_ID', '')

BLADE_TRADES = '/root/.openclaw/dashboard/agent_trades.json'
EDGE_TRADES  = '/root/.openclaw/agents/edge/data/trade_history.json'

OUTCOME_EMOJI = {
    'TP1':      '✅',
    'TP2':      '🏆',
    'TP3':      '🏆',
    'TRAIL':    '🏆',
    'BE':       '⚪',
    'SL':       '🔴',
    'NO_TRADE': '➡️',
    'no_trade': '➡️',
    'W':        '✅',
    'L':        '🔴',
}

# UTC windows used only for display/logging — filtering uses session field on each trade
SESSION_WINDOWS = {
    'ASIA':     (0,   0,   6,  0),
    'LONDON':   (6,   0,  13, 30),
    'NY_EARLY': (12,  0,  13, 30),
    'NY':       (13, 30,  17, 30),
    'NY_PM':    (17, 30,  21,  0),
}


def send_telegram(msg):
    try:
        r = requests.post(
            f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
            json={'chat_id': CHAT_ID, 'text': msg, 'parse_mode': 'HTML'},
            timeout=15,
        )
        r.raise_for_status()
    except Exception as e:
        print(f"[session_end_notify] Telegram error: {e}")


def load_blade_trades(session_name, today):
    """Return Blade trades for session_name on today (UTC date)."""
    try:
        with open(BLADE_TRADES) as f:
            data = json.load(f)
        trades = data.get('trades', [])
    except Exception as e:
        print(f"[session_end_notify] Could not read Blade trades: {e}")
        return []

    result = []
    for t in trades:
        if t.get('agent') != 'BLADE':
            continue
        if t.get('session') != session_name:
            continue
        # Match today by timestamp field first, fall back to date string
        ts_str = t.get('timestamp', '')
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                if ts.date() != today:
                    continue
            except Exception:
                if t.get('date', '') != today.isoformat():
                    continue
        else:
            if t.get('date', '') != today.isoformat():
                continue
        result.append(t)
    return result


def load_edge_trades(session_name, today):
    """Return Edge trades for session_name that closed today (UTC date)."""
    try:
        with open(EDGE_TRADES) as f:
            history = json.load(f)
    except Exception as e:
        print(f"[session_end_notify] Could not read Edge trades: {e}")
        return []

    result = []
    for t in history:
        if t.get('session') != session_name:
            continue
        exit_time_str = t.get('exit_time', '')
        try:
            exit_dt = datetime.fromisoformat(exit_time_str.replace('Z', '+00:00'))
            if exit_dt.date() != today:
                continue
        except Exception:
            continue
        result.append(t)
    return result


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 session_end_notify.py <SESSION>")
        sys.exit(1)

    session_name = sys.argv[1].upper()
    if session_name not in SESSION_WINDOWS:
        print(f"Unknown session '{session_name}'. Valid: {list(SESSION_WINDOWS.keys())}")
        sys.exit(1)

    today = datetime.now(timezone.utc).date()
    print(f"[session_end_notify] {session_name} | {today}")

    blade_trades = load_blade_trades(session_name, today)
    edge_trades  = load_edge_trades(session_name, today)

    # ── Blade stats ───────────────────────────────────────────────────────────
    blade_active = [t for t in blade_trades
                    if t.get('result') not in ('no_trade', 'Pending', 'none', None, '')]
    blade_pnl   = sum(t.get('pnl', 0) or 0 for t in blade_active)
    blade_count = len(blade_active)

    # ── Edge stats ────────────────────────────────────────────────────────────
    edge_pnl   = sum(t.get('pnl', 0) or 0 for t in edge_trades)
    edge_count = len(edge_trades)

    total_pnl = blade_pnl + edge_pnl

    # ── Build header ──────────────────────────────────────────────────────────
    lines = [f"📋 <b>{session_name} SESSION COMPLETE</b>"]

    if blade_count == 0:
        lines.append("  BLADE: no trades")
    else:
        sign = '+' if blade_pnl >= 0 else ''
        lines.append(f"  BLADE: {blade_count} trade{'s' if blade_count != 1 else ''} | {sign}${abs(blade_pnl):.2f}")

    if edge_count == 0:
        lines.append("  EDGE: no trades")
    else:
        sign = '+' if edge_pnl >= 0 else ''
        lines.append(f"  EDGE: {edge_count} trade{'s' if edge_count != 1 else ''} | {sign}${abs(edge_pnl):.2f}")

    sign_total = '+' if total_pnl >= 0 else ''
    lines.append(f"  Combined: {sign_total}${abs(total_pnl):.2f}")

    # ── Trade details ─────────────────────────────────────────────────────────
    detail_lines = []

    if blade_trades:
        detail_lines.append("\n  <b>BLADE</b>")
        for t in blade_trades:
            result  = t.get('result', '')
            instr   = (t.get('symbol') or t.get('pair') or '?')
            direc   = (t.get('direction') or '?').upper()
            pnl     = t.get('pnl', 0) or 0
            emoji   = OUTCOME_EMOJI.get(result, '➡️')
            sign    = '+' if pnl >= 0 else ''
            if result in ('no_trade', 'none', ''):
                detail_lines.append(f"    {instr} — no trade")
            else:
                detail_lines.append(
                    f"    {instr} {direc} — {result} {emoji} {sign}${abs(pnl):.2f}"
                )

    if edge_trades:
        detail_lines.append("\n  <b>EDGE</b>")
        m1_trades = [t for t in edge_trades if t.get('timeframe', 'M1') == 'M1']
        m5_trades = [t for t in edge_trades if t.get('timeframe') == 'M5']
        if m1_trades:
            parts = [
                f"SPX {t['direction'].upper()} "
                f"{'+' if t.get('pnl', 0) >= 0 else ''}${abs(t.get('pnl', 0)):.2f}"
                for t in m1_trades
            ]
            detail_lines.append(f"    M1: {' | '.join(parts)}")
        if m5_trades:
            parts = [
                f"SPX {t['direction'].upper()} "
                f"{'+' if t.get('pnl', 0) >= 0 else ''}${abs(t.get('pnl', 0)):.2f}"
                for t in m5_trades
            ]
            detail_lines.append(f"    M5: {' | '.join(parts)}")

    if detail_lines:
        lines.append('\n📎 <b>Details:</b>' + ''.join(detail_lines))

    msg = '\n'.join(lines)
    print(msg)
    send_telegram(wrap_message("huncho", msg))
    print(f"[session_end_notify] Sent.")


if __name__ == '__main__':
    main()
