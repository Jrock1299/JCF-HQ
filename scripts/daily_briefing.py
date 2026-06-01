#!/usr/bin/env python3
"""
daily_briefing.py — JCF Daily Briefing
Runs at 07:00 UTC via cron. Sends ONE consolidated Telegram message with:
  1. LENS macro bias
  2. SENTINEL insider signals

Replaces send_dashboard.py morning report.
"""

import json
import os
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
CHAT_ID   = '797062420'

MARKET_BIAS_FILE    = '/root/.openclaw/dashboard/market_bias.json'
SENTINEL_FILE       = '/root/.openclaw/dashboard/sentinel_data.json'

MAX_MSG_LEN = 4000


def _load(path: str, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def _yesterday():
    return (datetime.now(timezone.utc) - timedelta(days=1)).date()


def _today():
    return datetime.now(timezone.utc).date()


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1 — LENS MACRO BIAS
# ─────────────────────────────────────────────────────────────────────────────

def build_lens_section() -> str:
    data = _load(MARKET_BIAS_FILE)
    if not data:
        return "━━ LENS ━━\nNo bias data available."

    lines = ["━━ LENS MACRO BIAS ━━"]

    # Extract pairs — try both data['pairs'] array and direct top-level keys
    pairs = []

    # Try top-level dict entries first (non-metadata keys)
    skip_keys = {'last_updated', 'summary', 'morning_report', 'priorities', 'pairs', 'updated'}
    for key, val in data.items():
        if key in skip_keys:
            continue
        if isinstance(val, dict) and ('bias' in val or 'direction' in val):
            pairs.append((key, val))

    # Also check data['pairs'] array
    for p in data.get('pairs', []):
        sym = p.get('symbol') or p.get('pair') or p.get('instrument', '')
        if sym:
            pairs.append((sym, p))

    # Deduplicate by symbol
    seen = set()
    unique_pairs = []
    for sym, entry in pairs:
        if sym not in seen:
            seen.add(sym)
            unique_pairs.append((sym, entry))

    if not unique_pairs:
        lines.append("No pair data in market_bias.json")
    else:
        for sym, entry in unique_pairs:
            bias = (entry.get('bias') or entry.get('direction') or 'neutral').lower()
            conf = float(entry.get('confidence', entry.get('confidence_pct', 0)) or 0)
            if conf <= 1.0 and conf > 0:
                conf *= 100

            emoji = '🟢' if bias == 'bullish' else ('🔴' if bias == 'bearish' else '⚪')
            lines.append(f"  {emoji} <b>{sym}</b> — {bias.capitalize()} {conf:.0f}%")

    # Add morning_report context line (first sentence)
    morning = data.get('morning_report', '')
    if morning:
        first_sentence = morning.split('.')[0].strip()
        if len(first_sentence) > 120:
            first_sentence = first_sentence[:120] + '…'
        lines.append(f"\n  <i>{first_sentence}.</i>")

    return '\n'.join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2 — SENTINEL
# ─────────────────────────────────────────────────────────────────────────────

def build_sentinel_section() -> str:
    lines = ["━━ SENTINEL ━━"]
    data  = _load(SENTINEL_FILE)
    if not data:
        lines.append("  No sentinel data available.")
        return '\n'.join(lines)

    # Try daily_digest field first (added by Part I)
    digest = data.get('daily_digest')
    if digest:
        lines.append(f"  {digest}")
        return '\n'.join(lines)

    # Build from raw signals
    strong_buys = data.get('watchlist_buys', [])
    discoveries = data.get('top_discoveries', [])[:3]

    if strong_buys:
        top = strong_buys[:3]
        for sig in top:
            sym        = sig.get('symbol', '?')
            sig_type   = sig.get('signal_type', 'BUY')
            buy_count  = sig.get('buy_count', 0)
            total_val  = sig.get('total_buy_value', 0)
            val_str    = f"${total_val/1000:.0f}k" if total_val >= 1000 else f"${total_val:.0f}"
            cat        = sig.get('category', '')
            cat_str    = f" [{cat}]" if cat else ''
            lines.append(f"  🔍 {sym}{cat_str} — {sig_type} | {buy_count} insider(s) | {val_str}")
    elif discoveries:
        for d in discoveries:
            sym       = d.get('symbol', '?')
            buy_count = d.get('buy_count', 0)
            val       = d.get('total_value', 0)
            val_str   = f"${val/1000:.0f}k" if val >= 1000 else f"${val:.0f}"
            lines.append(f"  🔭 {sym} — {buy_count} insiders | {val_str} (discovery)")
    else:
        lines.append("  No notable insider signals")

    return '\n'.join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# ASSEMBLE AND SEND
# ─────────────────────────────────────────────────────────────────────────────

def build_briefing() -> str:
    now = datetime.now(timezone.utc)
    header = f"📊 <b>JCF DAILY BRIEFING — {now.strftime('%B %-d, %Y')}</b>"

    sections = [
        header,
        "",
        build_lens_section(),
        "",
        build_sentinel_section(),
    ]

    msg = '\n'.join(sections)

    # Trim to Telegram limit
    if len(msg) > MAX_MSG_LEN:
        msg = msg[:MAX_MSG_LEN - 3] + '…'

    return msg


def send_briefing():
    msg = build_briefing()
    print(msg)
    print(f"\n[{len(msg)} chars]")

    try:
        r = requests.post(
            f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
            json={'chat_id': CHAT_ID, 'text': msg, 'parse_mode': 'HTML',
                  'disable_web_page_preview': True},
            timeout=20,
        )
        result = r.json()
        if result.get('ok'):
            print("✓ Briefing sent successfully.")
        else:
            print(f"✗ Telegram error: {result}")
    except Exception as e:
        print(f"✗ Send failed: {e}")


if __name__ == '__main__':
    send_briefing()
