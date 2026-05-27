#!/usr/bin/env python3
"""
session_notify.py — JCF Consolidated Session Notifications

Coordinates session start/end Telegram alerts across Blade, Crisp, and Edge.
Multiple agents registering within the same window (60s start / 120s end)
are consolidated into one message. Atomic file-lock election prevents duplicates.

Usage:
  from session_notify import session_start, session_end

  # At session open (blocks 60s while waiting to consolidate):
  session_start('BLADE', ['XAU', 'SPX500', 'DE30'], 'NY')

  # At session close (blocks 120s):
  session_end('BLADE', trades=3, pnl=28.40, trade_details=[...], session_name='NY')

trade_details format:
  [{'agent': 'BLADE', 'instrument': 'XAU', 'direction': 'LONG',
    'outcome': 'TRAIL',  # TP1 / TP2 / TRAIL / BE / SL / NO_TRADE
    'pnl': 22.40, 'timeframe': 'M1'}]  # timeframe optional (Edge only)
"""

import json
import os
import time
import threading
import requests
from datetime import datetime, timezone

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
CHAT_ID   = '797062420'

ACTIVE_FILE  = '/tmp/jcf_session_active.json'
RESULTS_FILE = '/tmp/jcf_session_results.json'

OUTCOME_EMOJI = {
    'TP1':      '✅',
    'TP2':      '🏆',
    'TP3':      '🏆',
    'TRAIL':    '🏆',
    'BE':       '⚪',
    'SL':       '🔴',
    'NO_TRADE': '➡️',
    'W':        '✅',
    'L':        '🔴',
}


# ─────────────────────────────────────────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────────────────────────────────────────

def _send(msg: str):
    try:
        requests.post(
            f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
            json={'chat_id': CHAT_ID, 'text': msg, 'parse_mode': 'HTML'},
            timeout=15,
        )
    except Exception as e:
        print(f"[session_notify] Telegram error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# ATOMIC SENDER ELECTION
# Returns True if this caller wins the right to send (creates flag atomically).
# ─────────────────────────────────────────────────────────────────────────────

def _claim_sender(flag_path: str) -> bool:
    try:
        fd = os.open(flag_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        return True
    except FileExistsError:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# SESSION START
# ─────────────────────────────────────────────────────────────────────────────

def _do_session_start(agent_name: str, instruments: list, session_name: str):
    now_ts = time.time()

    # --- Register this agent ---
    try:
        try:
            with open(ACTIVE_FILE) as f:
                data = json.load(f)
        except Exception:
            data = {'session': session_name, 'registered_at': now_ts, 'agents': {}}

        # Reset file if it's stale (> 10 minutes old)
        if now_ts - data.get('registered_at', 0) > 600:
            data = {'session': session_name, 'registered_at': now_ts, 'agents': {}}

        data['agents'][agent_name] = {
            'instruments': instruments,
            'ts': now_ts,
        }
        with open(ACTIVE_FILE, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        print(f"[session_notify] session_start write error: {e}")
        return

    # --- Wait for consolidation window ---
    time.sleep(60)

    # --- Atomically claim sender role ---
    flag = ACTIVE_FILE + '.sent'
    if not _claim_sender(flag):
        return   # Another agent already sent

    # --- Build and send consolidated start message ---
    try:
        with open(ACTIVE_FILE) as f:
            data = json.load(f)
    except Exception:
        data = {'session': session_name, 'agents': {agent_name: {'instruments': instruments}}}

    sess = data.get('session', session_name)
    agents = data.get('agents', {})

    lines = [f"⚡ <b>{sess} SESSION ACTIVE</b>"]
    for agent, info in sorted(agents.items()):
        instrs = info.get('instruments', [])
        instr_str = ', '.join(str(i) for i in instrs) if instrs else '—'
        lines.append(f"  {agent} 🟢 — {instr_str}")

    _send('\n'.join(lines))


def session_start(agent_name: str, instruments: list, session_name: str, blocking: bool = True):
    """
    Register this agent for the session start notification.
    blocking=True: runs in calling thread (fine for cron scripts).
    blocking=False: spawns background thread (use for always-on daemons).
    """
    if blocking:
        _do_session_start(agent_name, instruments, session_name)
    else:
        t = threading.Thread(
            target=_do_session_start,
            args=(agent_name, instruments, session_name),
            daemon=True,
        )
        t.start()


# ─────────────────────────────────────────────────────────────────────────────
# SESSION END
# ─────────────────────────────────────────────────────────────────────────────

def _do_session_end(agent_name: str, trades_count: int, pnl: float,
                    trade_details: list, session_name: str):
    now_ts = time.time()

    # --- Register this agent's results ---
    try:
        try:
            with open(RESULTS_FILE) as f:
                data = json.load(f)
        except Exception:
            data = {'session': session_name, 'registered_at': now_ts, 'agents': {}}

        if now_ts - data.get('registered_at', 0) > 600:
            data = {'session': session_name, 'registered_at': now_ts, 'agents': {}}

        data['agents'][agent_name] = {
            'trades': trades_count,
            'pnl':    round(pnl, 2),
            'details': trade_details or [],
            'ts':     now_ts,
        }
        with open(RESULTS_FILE, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        print(f"[session_notify] session_end write error: {e}")
        return

    # --- Wait for all agents to finish ---
    time.sleep(120)

    # --- Atomically claim sender role ---
    flag = RESULTS_FILE + '.sent'
    if not _claim_sender(flag):
        return

    # --- Build consolidated end message ---
    try:
        with open(RESULTS_FILE) as f:
            data = json.load(f)
    except Exception:
        data = {'session': session_name, 'agents': {
            agent_name: {'trades': trades_count, 'pnl': pnl, 'details': trade_details}
        }}

    sess    = data.get('session', session_name)
    agents  = data.get('agents', {})
    total_pnl = sum(a.get('pnl', 0) for a in agents.values())
    sign_total = '+' if total_pnl >= 0 else ''

    lines = [f"📋 <b>{sess} SESSION COMPLETE</b>"]

    for agent, info in sorted(agents.items()):
        t = info.get('trades', 0)
        p = info.get('pnl', 0)
        sign = '+' if p >= 0 else ''
        if t == 0:
            lines.append(f"  {agent}: no trades")
        else:
            lines.append(f"  {agent}: {t} trade{'s' if t != 1 else ''} | {sign}${abs(p):.2f}")

    lines.append(f"  Combined: {sign_total}${abs(total_pnl):.2f}")

    # --- Per-agent trade details ---
    detail_lines = []
    for agent, info in sorted(agents.items()):
        dets = info.get('details', [])
        if not dets:
            continue
        detail_lines.append(f"\n  <b>{agent}</b>")

        # Group edge by timeframe
        m1_trades = [d for d in dets if d.get('timeframe', 'M1') == 'M1']
        m5_trades = [d for d in dets if d.get('timeframe') == 'M5']

        if m5_trades or any(d.get('timeframe') for d in dets):
            # Edge format
            if m1_trades:
                m1_str = ' | '.join(
                    f"{d.get('instrument','')} {d.get('direction','')} "
                    f"{'+' if d.get('pnl',0)>=0 else ''}${abs(d.get('pnl',0)):.2f}"
                    for d in m1_trades if d.get('outcome') != 'NO_TRADE'
                )
                if m1_str:
                    detail_lines.append(f"    M1: {m1_str}")
            if m5_trades:
                m5_str = ' | '.join(
                    f"{d.get('instrument','')} {d.get('direction','')} "
                    f"{'+' if d.get('pnl',0)>=0 else ''}${abs(d.get('pnl',0)):.2f}"
                    for d in m5_trades if d.get('outcome') != 'NO_TRADE'
                )
                if m5_str:
                    detail_lines.append(f"    M5: {m5_str}")
        else:
            # Blade/Crisp format
            for d in dets:
                outcome = d.get('outcome', '')
                instr   = d.get('instrument', '')
                direc   = d.get('direction', '')
                p       = d.get('pnl', 0)
                emoji   = OUTCOME_EMOJI.get(outcome, '➡️')
                sign    = '+' if p >= 0 else ''

                if outcome == 'NO_TRADE':
                    detail_lines.append(f"    {instr} — no trade")
                else:
                    detail_lines.append(
                        f"    {instr} {direc} — {outcome} {emoji} {sign}${abs(p):.2f}"
                    )

    if detail_lines:
        lines.append('\n📎 <b>Details:</b>' + ''.join(detail_lines))

    _send('\n'.join(lines))

    # Clean up sent flags after a delay so the next session can use the files
    try:
        time.sleep(300)
        for f in (ACTIVE_FILE, RESULTS_FILE, ACTIVE_FILE + '.sent', RESULTS_FILE + '.sent'):
            try:
                os.remove(f)
            except FileNotFoundError:
                pass
    except Exception:
        pass


def session_end(agent_name: str, trades_count: int, pnl: float,
                trade_details: list, session_name: str, blocking: bool = True):
    """
    Register this agent's session results and (if first after 120s) send consolidated end message.
    blocking=True: runs in calling thread.
    blocking=False: spawns background thread.
    """
    if blocking:
        _do_session_end(agent_name, trades_count, pnl, trade_details, session_name)
    else:
        t = threading.Thread(
            target=_do_session_end,
            args=(agent_name, trades_count, pnl, trade_details, session_name),
            daemon=True,
        )
        t.start()
