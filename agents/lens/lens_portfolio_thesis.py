#!/usr/bin/env python3
"""
lens_portfolio_thesis.py — Weekly per-holding portfolio thesis (Lens extension).

Reads the CONNECTED brokerage/wallet data, asks Claude (with web search) for a
500-1000 char thesis per holding plus a full rotation summary (trim / add), writes
dashboard/portfolio_thesis.json, and delivers via Telegram + Discord.

Runs Sunday before Monday's open. Only analyzes accounts confirmed connected
(2026-07-24: Robinhood, Kraken, Alpaca paper, TrustWallet). The Public.com /
Roth-IRA account is NOT integrated and is flagged as excluded in the output.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic

sys.path.insert(0, '/root/.openclaw/scripts')
from telegram_personalities import wrap_message  # noqa: F401 (kept for parity)
try:
    from discord_notify import notify as discord_notify
except Exception:
    discord_notify = None

DASH  = Path('/root/.openclaw/dashboard')
OUT   = DASH / 'portfolio_thesis.json'
MODEL = 'claude-sonnet-4-6'
MAX_TOKENS = 8192
TG_MAX = 4000
TELEGRAM_TOKEN   = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_ALERT_CHAT_ID') or os.getenv('TELEGRAM_CHAT_ID')

# Confirmed connected (2026-07-24). Public.com / Roth IRA = NOT wired.
MISSING_ACCOUNTS = [
    'Public.com / Roth IRA (Roth, Spending, Joint, Strategies, Custodial tabs) '
    '— never integrated into JCF HQ, so it is NOT reflected below.'
]

SYSTEM_PROMPT = """You are Lens, the macro analyst for JCF HQ. You are writing a \
WEEKLY PORTFOLIO THESIS across Jase's connected accounts. For EACH holding, use \
web_search to ground your view in current facts, then write a 500-1000 character \
thesis covering: what the company/asset does, why it is a reasonable position \
right now, and current thesis strength. Then give full ROTATION suggestions — \
what to trim and what to add — based on the real holdings and current conditions, \
not speculation. Be honest; call out weak positions.

Output ONLY valid JSON, no prose outside it:
{
  "holdings": [
    {"symbol": "...", "account": "...", "value_usd": 0, "pct_of_portfolio": 0,
     "thesis": "500-1000 chars", "strength": "strong|moderate|weak"}
  ],
  "rotation": {
    "trim": ["symbol — reason", ...],
    "add":  ["idea — reason", ...],
    "summary": "3-5 sentence rotation summary"
  }
}"""


def _load(name):
    try:
        return json.load(open(DASH / name))
    except Exception:
        return {}


def gather_holdings():
    """Return [{account, symbol, type, qty, value}] across connected sources."""
    h = []
    rh = _load('robinhood_holdings.json')
    for p in rh.get('positions', []):
        h.append({'account': 'Robinhood', 'symbol': p.get('symbol'), 'type': 'stock',
                  'qty': p.get('quantity'), 'value': p.get('equity')})
    for k in _load('kraken_data.json').get('holdings', []) or []:
        if isinstance(k, dict) and (k.get('value_usd') or 0) >= 1:
            h.append({'account': 'Kraken', 'symbol': k.get('asset'), 'type': 'crypto',
                      'qty': k.get('balance'), 'value': k.get('value_usd')})
    jp = _load('jerry_portfolio.json')
    for p in jp.get('open_positions', []):
        h.append({'account': 'Alpaca (paper)', 'symbol': p.get('symbol'), 'type': 'stock',
                  'qty': p.get('qty'), 'value': p.get('market_value')})
    tw = (_load('trustwallet_data.json').get('holdings') or {})
    for sym, v in (tw.items() if isinstance(tw, dict) else []):
        if isinstance(v, dict) and (v.get('usd_value') or 0) >= 1:
            h.append({'account': 'TrustWallet', 'symbol': sym, 'type': 'crypto',
                      'qty': v.get('balance'), 'value': v.get('usd_value')})
    return h


def _extract_json(text):
    if not text:
        return None
    for pat in (text, ):
        try:
            return json.loads(pat.strip())
        except Exception:
            pass
    m = re.search(r'```(?:json)?\s*(\{[\s\S]*\})\s*```', text) or re.search(r'(\{[\s\S]*\})', text)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            return None
    return None


def build(holdings):
    total = sum((x['value'] or 0) for x in holdings) or 1.0
    lines = [f"TOTAL across connected accounts: ${total:,.2f} | {len(holdings)} holdings\n"]
    for x in sorted(holdings, key=lambda z: -(z['value'] or 0)):
        pct = 100 * (x['value'] or 0) / total
        lines.append(f"  {x['symbol']:6} [{x['account']}, {x['type']}] "
                     f"${(x['value'] or 0):,.2f} ({pct:.1f}%) qty={x['qty']}")
    excluded = "\n".join(f"  - {m}" for m in MISSING_ACCOUNTS)
    user = (f"HOLDINGS (connected accounts only):\n" + "\n".join(lines) +
            f"\n\nEXCLUDED (not integrated — note this in the output):\n{excluded}\n\n"
            "Write the weekly portfolio thesis JSON now (500-1000 chars per holding).")

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=MODEL, max_tokens=MAX_TOKENS, system=SYSTEM_PROMPT,
        tools=[{'type': 'web_search_20250305', 'name': 'web_search'}],
        messages=[{'role': 'user', 'content': user}],
    )
    text = ''.join(b.text for b in resp.content if getattr(b, 'type', '') == 'text' and getattr(b, 'text', ''))
    result = _extract_json(text)
    if result is None:                                     # one JSON-only retry
        resp2 = client.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS, system=SYSTEM_PROMPT,
            tools=[{'type': 'web_search_20250305', 'name': 'web_search'}],
            messages=[{'role': 'user', 'content': user},
                      {'role': 'assistant', 'content': resp.content},
                      {'role': 'user', 'content': 'Output ONLY the JSON now — start with { end with }.'}],
        )
        text = ''.join(b.text for b in resp2.content if getattr(b, 'type', '') == 'text' and getattr(b, 'text', ''))
        result = _extract_json(text)
    return result or {'holdings': [], 'rotation': {'trim': [], 'add': [], 'summary': 'Thesis generation failed.'}}


def _tg_send(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print('[thesis] Telegram not configured — skipping'); return
    import requests
    for i in range(0, len(text), TG_MAX):
        try:
            requests.post(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
                          json={'chat_id': TELEGRAM_CHAT_ID, 'text': text[i:i + TG_MAX]}, timeout=15)
        except Exception as e:
            print(f'[thesis] Telegram error: {e}'); break


def render(result):
    lines = ['🌐 LENS — WEEKLY PORTFOLIO THESIS',
             datetime.now(timezone.utc).strftime('%Y-%m-%d'), '']
    for h in result.get('holdings', []):
        lines.append(f"━━ {h.get('symbol')} [{h.get('account')}] "
                     f"${h.get('value_usd', 0):,.0f} ({h.get('pct_of_portfolio', 0)}%) "
                     f"— {str(h.get('strength', '')).upper()}")
        lines.append(str(h.get('thesis', '')).strip())
        lines.append('')
    rot = result.get('rotation', {})
    lines.append('🔄 ROTATION')
    for t in rot.get('trim', []):
        lines.append(f"  ✂️ TRIM: {t}")
    for a in rot.get('add', []):
        lines.append(f"  ➕ ADD: {a}")
    lines.append('')
    lines.append(rot.get('summary', ''))
    lines.append('')
    lines.append('⚠️ NOT INCLUDED (no integration): ' + '; '.join(MISSING_ACCOUNTS))
    lines.append('— Lens')
    return '\n'.join(lines)


def main():
    holdings = gather_holdings()
    print(f'[thesis] {len(holdings)} holdings across connected accounts')
    result = build(holdings)
    result['_meta'] = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'connected_accounts': ['Robinhood', 'Kraken', 'Alpaca (paper)', 'TrustWallet'],
        'excluded_accounts': MISSING_ACCOUNTS,
        'holding_count': len(holdings),
        'model': MODEL,
    }
    OUT.write_text(json.dumps(result, indent=2))
    print(f'[thesis] wrote {OUT}')
    report = render(result)
    _tg_send(report)
    if discord_notify:
        try:
            print('[thesis] Discord:', discord_notify('lens', report, channels=['LENS']))
        except Exception as e:
            print(f'[thesis] Discord skipped: {e}')


if __name__ == '__main__':
    main()
