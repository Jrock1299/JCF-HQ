#!/usr/bin/env python3
"""
daily_briefing.py — JCF Daily Briefing
Runs at 07:00 UTC via cron. Sends ONE consolidated Telegram message with:
  1. LENS macro bias
  2. ORACLE (yesterday's results + today's picks)
  3. KALSHI yesterday's stats
  4. SENTINEL insider signals

Replaces send_dashboard.py morning report.
"""

import json
import os
import requests
import csv
from datetime import datetime, timezone, timedelta
from pathlib import Path

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
CHAT_ID   = '797062420'

MARKET_BIAS_FILE    = '/root/.openclaw/dashboard/market_bias.json'
ORACLE_PICKS_FILE   = '/root/.openclaw/dashboard/oracle_picks.json'
ORACLE_RESOLVED_FILE = '/root/.openclaw/dashboard/oracle_resolved.json'
KALSHI_DAILY_FILE   = '/tmp/jcf_kalshi_daily.json'
SENTINEL_FILE       = '/root/.openclaw/dashboard/sentinel_data.json'
KALSHI_CSV          = '/root/kalshi-bot/trades_log.csv'

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
# SECTION 2 — ORACLE
# ─────────────────────────────────────────────────────────────────────────────

def build_oracle_section() -> str:
    lines = ["━━ ORACLE ━━"]
    yest  = str(_yesterday())
    today = str(_today())

    # --- Yesterday's results from oracle_resolved.json ---
    resolved = _load(ORACLE_RESOLVED_FILE, {})
    all_picks_res = resolved.get('picks', []) if isinstance(resolved, dict) else resolved

    # Also check oracle_picks.json for resolved picks
    picks_data = _load(ORACLE_PICKS_FILE, {})
    balance    = picks_data.get('balance', 0) if isinstance(picks_data, dict) else 0
    bankroll   = picks_data.get('bankroll', 500) if isinstance(picks_data, dict) else 500
    all_picks_main = (picks_data.get('picks', []) if isinstance(picks_data, dict) else
                      picks_data if isinstance(picks_data, list) else [])

    # Yesterday's resolved picks — try both sources
    yest_picks = [p for p in all_picks_res
                  if (p.get('date','') or p.get('resolved_at','')).startswith(yest)
                  and p.get('result','').lower() in ('win','loss','w','l')]

    if not yest_picks:
        yest_picks = [p for p in all_picks_main
                      if (p.get('date','') or p.get('resolved_at','')).startswith(yest)
                      and p.get('result','').lower() in ('win','loss','w','l')]

    if yest_picks:
        wins     = sum(1 for p in yest_picks if p.get('result','').lower() in ('win','w'))
        losses   = sum(1 for p in yest_picks if p.get('result','').lower() in ('loss','l'))
        day_pnl  = sum(float(p.get('pnl') or 0) for p in yest_picks)
        sign     = '+' if day_pnl >= 0 else ''
        lines.append(f"  Yesterday: {wins}W-{losses}L | {sign}${day_pnl:.2f}")
        for p in yest_picks[:6]:
            r     = p.get('result','').lower()
            emoji = '✅' if r in ('win','w') else '🔴'
            pick  = p.get('pick', p.get('name','?'))
            odds  = p.get('odds', p.get('odds_at_log',''))
            pnl   = float(p.get('pnl') or 0)
            sign2 = '+' if pnl >= 0 else ''
            lines.append(f"    {emoji} {pick} ({odds}) {sign2}${abs(pnl):.2f}")
    else:
        lines.append(f"  Yesterday: No resolved picks")

    # Balance
    if balance:
        all_time = balance - bankroll
        sign_at  = '+' if all_time >= 0 else ''
        lines.append(f"  Bankroll: ${balance:.2f} ({sign_at}${all_time:.2f} all-time)")

    # --- Today's picks ---
    today_picks = [p for p in all_picks_main
                   if (p.get('date','') or p.get('commence','')).startswith(today)
                   and p.get('result','pending').lower() == 'pending']

    if not today_picks:
        # Also check resolved file for today's pending
        today_picks = [p for p in all_picks_res
                       if (p.get('date','') or '').startswith(today)
                       and p.get('result','pending').lower() == 'pending']

    if today_picks:
        lines.append(f"\n  Today ({len(today_picks)} picks):")
        for p in today_picks[:6]:
            pick  = p.get('pick', p.get('name','?'))
            odds  = p.get('odds', p.get('odds_at_log',''))
            league = p.get('league', p.get('sport',''))
            ev    = p.get('oracle_ev', p.get('ev'))
            stake = float(p.get('stake') or 0)
            ev_str = f" EV:{'+' if float(ev or 0)>=0 else ''}{float(ev or 0):.1f}%" if ev is not None else ''
            stake_str = f" ${stake:.0f}" if stake else ''
            lines.append(f"    🎯 {pick} ({odds}){ev_str}{stake_str}")
    else:
        lines.append("  Today: No picks yet (oracle runs at 06:30 UTC)")

    return '\n'.join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3 — KALSHI
# ─────────────────────────────────────────────────────────────────────────────

def build_kalshi_section() -> str:
    lines = ["━━ KALSHI ━━"]

    # Try the pre-computed daily summary first
    daily = _load(KALSHI_DAILY_FILE)
    if daily:
        trades = daily.get('trades', 0)
        wins   = daily.get('wins', 0)
        losses = daily.get('losses', 0)
        pnl    = daily.get('pnl', 0)
        br     = daily.get('bankroll', 0)
        sign   = '+' if pnl >= 0 else ''
        lines.append(
            f"  Yesterday: {trades} trades | {wins}W-{losses}L | {sign}${pnl:.2f}"
        )
        if br:
            lines.append(f"  Bankroll: ${br:.2f}")
        return '\n'.join(lines)

    # Fall back to computing from CSV directly
    if not Path(KALSHI_CSV).exists():
        lines.append("  No trade data available.")
        return '\n'.join(lines)

    yest     = str(_yesterday())
    trades   = 0
    wins     = 0
    losses   = 0
    pnl      = 0.0
    bankroll = 0.0

    try:
        with open(KALSHI_CSV, newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts = row.get('timestamp', '')
                if not ts.startswith(yest):
                    continue
                status = row.get('status', '')
                if status in ('error', 'cancelled') or status.startswith('error'):
                    continue
                trades += 1
                # Approximate P&L: YES win = contracts * (1 - entry/100), YES loss = -contracts * entry/100
                try:
                    contracts   = int(row.get('contracts', 0) or 0)
                    entry_cents = int(row.get('entry_price', 50) or 50)
                    size        = float(row.get('size', 0) or 0)
                    # Can't determine win/loss from CSV alone without settlement
                except Exception:
                    pass

        if trades > 0:
            lines.append(f"  Yesterday: {trades} trades (settlement data in Kalshi account)")
        else:
            lines.append("  Yesterday: No trades logged")
    except Exception as e:
        lines.append(f"  CSV read error: {e}")

    return '\n'.join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4 — SENTINEL
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
        build_oracle_section(),
        "",
        build_kalshi_section(),
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
