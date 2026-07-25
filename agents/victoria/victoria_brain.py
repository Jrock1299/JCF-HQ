#!/usr/bin/env python3
"""
victoria_brain.py — CFO and Chief of Staff for JCF HQ.

Reads all operation data, calls Claude to produce a daily financial
summary + operations briefing, sends Telegram report, and saves results.

Usage:
    python3 victoria_brain.py
"""

import csv
import json
import os
import re
import subprocess
import sys
import requests
from datetime import datetime, timezone
from glob import glob
from pathlib import Path

sys.path.insert(0, '/root/.openclaw/scripts')
from telegram_personalities import wrap_message

# ─── Paths ─────────────────────────────────────────────────────────────────────

DASHBOARD     = Path('/root/.openclaw/dashboard')
LOGS          = Path('/root/.openclaw/logs')
REPORT_PATH   = DASHBOARD / 'victoria_report.json'
HISTORY_PATH  = LOGS / 'victoria_history.json'
COST_LOG_PATH = LOGS / 'victoria_api_costs.json'
VICTORIA_LOG  = LOGS / 'victoria.log'
NORMAN_PATH   = DASHBOARD / 'norman_report.json'

# Migrated 2026-07-24 off the Anthropic SDK to Codex via the openclaw gateway
# (Lucy's subprocess pattern). Tier: GPT-5.6 Terra (balanced everyday tier,
# cheaper than the Sol flagship — and Sol is NOT available on this Codex OAuth
# backend, it 400s). Was openai/gpt-5.5.
# NOTE: the override must be a plain tier id ('openai/gpt-5.6-terra') AND be
# whitelisted in `agents.defaults.models` (openclaw.json). The '-codex' suffixed
# ids are runtime-bound and rejected as --model overrides by `openclaw agent`.
MODEL      = 'openai/gpt-5.6-terra'
MAX_TOKENS = 8192

TELEGRAM_TOKEN   = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_ALERT_CHAT_ID') or os.getenv('TELEGRAM_CHAT_ID')


def _run_codex(system_prompt: str, user_message: str, timeout: int = 300) -> str | None:
    """Route a prompt through the openclaw gateway agent (Codex).

    Mirrors Lucy's `_run_agent` subprocess pattern. The gateway agent has no
    separate `system` slot, so the persona/system prompt is prepended into the
    message. The (potentially large) payload is passed via --message-file to
    avoid the ~128KB single CLI-arg limit. Returns response text, or None.
    """
    import tempfile
    combined = f"{system_prompt}\n\n=== TASK ===\n\n{user_message}"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            'w', suffix='.txt', prefix='victoria_codex_',
            dir='/tmp', delete=False, encoding='utf-8',
        ) as fh:
            fh.write(combined)
            tmp_path = fh.name
        cmd = [
            'openclaw', 'agent',
            '--agent', 'main',
            '--model', MODEL,
            '--message-file', tmp_path,
            '--json',
            '--timeout', str(timeout),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 60)
        if proc.returncode != 0:
            print(f'[victoria] Codex call failed: {proc.stderr[:300]}')
            return None
        data = json.loads(proc.stdout)
        payloads = data.get('result', {}).get('payloads', [])
        return payloads[0].get('text', '') if payloads else None
    except subprocess.TimeoutExpired:
        print('[victoria] Codex call timed out')
        return None
    except Exception as e:
        print(f'[victoria] Codex call error: {e}')
        return None
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


# ─── JSON helpers ───────────────────────────────────────────────────────────────

def _load_json(path, label=''):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        print(f'[victoria] Warning: could not load {label or path}: {e}')
        return None


def _extract_json(text: str) -> dict | None:
    if not text or not text.strip():
        return None
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    code_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
    if code_match:
        try:
            return json.loads(code_match.group(1))
        except json.JSONDecodeError:
            pass
    brace_depth = 0
    json_start  = -1
    last_complete = None
    for i, ch in enumerate(text):
        if ch == '{':
            if brace_depth == 0:
                json_start = i
            brace_depth += 1
        elif ch == '}':
            brace_depth -= 1
            if brace_depth == 0 and json_start != -1:
                candidate = text[json_start:i + 1]
                try:
                    last_complete = json.loads(candidate)
                except json.JSONDecodeError:
                    pass
    return last_complete


# ─── API cost aggregator ────────────────────────────────────────────────────────

def aggregate_api_costs() -> dict:
    """
    Reads all *_api_costs.json files in /root/.openclaw/logs/.
    Returns:
      - total_today: sum of all costs from today's date
      - total_mtd:   sum of all costs this month
      - per_agent:   dict of agent_name -> {today, mtd}
    """
    today   = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    month   = today[:7]  # YYYY-MM
    result  = {'total_today': 0.0, 'total_mtd': 0.0, 'per_agent': {}}

    cost_files = glob(str(LOGS / '*_api_costs.json'))
    for fpath in sorted(cost_files):
        agent_name = Path(fpath).stem.replace('_api_costs', '')
        entries    = _load_json(fpath, agent_name)
        if not isinstance(entries, list):
            continue
        agent_today = 0.0
        agent_mtd   = 0.0
        for entry in entries:
            cost = entry.get('cost_usd', 0.0) or 0.0
            date = entry.get('date', '')
            if date == today:
                agent_today += cost
            if date.startswith(month):
                agent_mtd += cost
        result['total_today'] += agent_today
        result['total_mtd']   += agent_mtd
        result['per_agent'][agent_name] = {
            'today': round(agent_today, 6),
            'mtd':   round(agent_mtd, 6),
        }

    result['total_today'] = round(result['total_today'], 6)
    result['total_mtd']   = round(result['total_mtd'], 6)
    return result


# ─── Cost tracking ──────────────────────────────────────────────────────────────

def _load_costs() -> list:
    try:
        with open(COST_LOG_PATH) as f:
            return json.load(f)
    except Exception:
        return []


def _save_cost(input_tokens: int, output_tokens: int) -> float:
    cost_usd = round(
        (input_tokens  * 3  / 1_000_000) +
        (output_tokens * 15 / 1_000_000),
        6,
    )
    entry = {
        'date':          datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'timestamp':     datetime.now(timezone.utc).isoformat(),
        'input_tokens':  input_tokens,
        'output_tokens': output_tokens,
        'cost_usd':      cost_usd,
    }
    costs = _load_costs()
    costs.append(entry)
    LOGS.mkdir(parents=True, exist_ok=True)
    try:
        with open(COST_LOG_PATH, 'w') as f:
            json.dump(costs, f, indent=2)
    except Exception as e:
        print(f'[victoria] cost log write error: {e}')
    return cost_usd


# ─── Service status ─────────────────────────────────────────────────────────────

def check_service_statuses() -> dict:
    services = ['edge', 'crisp-v5', 'jcf-hq', 'hq-storage']
    statuses = {}
    for svc in services:
        try:
            result = subprocess.run(
                ['systemctl', 'is-active', svc],
                capture_output=True, text=True, timeout=5
            )
            statuses[svc] = result.stdout.strip()
        except Exception as e:
            statuses[svc] = f'unknown ({e})'
    return statuses


# ─── Data loaders ───────────────────────────────────────────────────────────────

def _f(val, default=0.0) -> float:
    """Safe float conversion."""
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def _format_tradelocker(data: dict) -> str:
    if not data:
        return 'TradeLocker: no data'
    trades = data.get('trades', [])
    today  = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    today_trades = [
        t for t in trades
        if str(t.get('date', t.get('timestamp', ''))).startswith(today)
    ]
    today_pnl = sum(
        _f(t.get('pnl', t.get('profit', 0)))
        for t in today_trades
    )
    lines = [
        f"TradeLocker Manual Trading:",
        f"  Balance: ${_f(data.get('balance')):.2f}",
        f"  Total P&L (all time): ${_f(data.get('pnl')):.2f}",
        f"  Wins/Losses: {data.get('wins', 0)}W / {data.get('losses', 0)}L",
        f"  Win Rate: {_f(data.get('win_rate')):.1f}%",
        f"  Today's trades: {len(today_trades)} | Today P&L: ${today_pnl:.2f}",
    ]
    return '\n'.join(lines)


def _format_edge(data: dict) -> str:
    if not data:
        return 'Edge: no data'
    return (
        f"Edge Trading Bot:\n"
        f"  Balance: ${_f(data.get('balance')):.2f}\n"
        f"  Total P&L: ${_f(data.get('total_pnl')):.2f}\n"
        f"  Daily P&L: ${_f(data.get('daily_pnl')):.2f}\n"
        f"  Trades: {data.get('trades', 0)} | Win Rate: {_f(data.get('win_rate')):.1f}%"
    )


def _format_tao(data: dict) -> str:
    if not data:
        return 'Tao: no data'
    return (
        f"Tao Staking:\n"
        f"  Staked: {_f(data.get('root_staked_tao')):.4f} TAO "
        f"@ ${_f(data.get('tao_price_usd')):.2f}\n"
        f"  Total Invested: ${_f(data.get('total_invested_usd')):.2f}\n"
        f"  DCA Entries: {data.get('dca_entries_used', 0)} used / "
        f"{data.get('dca_entries_remaining', 0)} remaining"
    )


def _format_agent_pnl(data: dict) -> str:
    if not data:
        return 'Agent P&L: no data'
    lines = ['Blade & Crisp:']
    for agent in ('blade', 'crisp'):
        a = data.get(agent, {})
        lines.append(
            f"  {agent.capitalize()}: P&L ${_f(a.get('pnl')):.2f} | "
            f"{a.get('trades', 0)} trades | WR {_f(a.get('wr')):.1f}% | "
            f"Sessions: {a.get('sessions', 0)}"
        )
    return '\n'.join(lines)


def _format_accounts(plaid: dict, robinhood: dict, kraken: dict,
                     trustwallet: dict, net_worth: dict) -> str:
    lines = ['Account Balances:']
    if plaid:
        for acct in plaid.get('accounts', []):
            lines.append(f"  {acct.get('name','?')}: ${_f(acct.get('balance')):.2f}")
    if robinhood:
        lines.append(f"  Robinhood: ${_f(robinhood.get('total_equity')):.2f}")
    if kraken:
        lines.append(f"  Kraken Crypto: ${_f(kraken.get('total_usd')):.2f}")
        for h in (kraken.get('holdings') or [])[:4]:
            lines.append(f"    {h.get('asset')}: {_f(h.get('balance')):.4f} = ${_f(h.get('value_usd')):.2f}")
    if trustwallet:
        lines.append(f"  TrustWallet: ${_f(trustwallet.get('total_usd')):.2f}")
    if net_worth:
        nw = net_worth.get('networth_override')
        if nw:
            lines.append(f"  Net Worth Override: ${_f(nw):,.2f}")
        pnl_t = net_worth.get('pnl_today', 0)
        pnl_m = net_worth.get('pnl_month', 0)
        lines.append(f"  Net Worth P&L — Today: ${_f(pnl_t):.2f} | MTD: ${_f(pnl_m):.2f}")
    return '\n'.join(lines)


def _format_lens_bias(data: dict) -> str:
    if not data:
        return 'Lens: no data'
    lines = [f"Lens Macro Bias ({data.get('last_updated','?')[:10]}):"]
    lines.append(f"  Summary: {data.get('summary','')[:200]}")
    for p in data.get('pairs', []):
        lines.append(
            f"  {p.get('symbol')}: {p.get('bias','?').upper()} "
            f"{p.get('confidence','?')}%"
        )
    return '\n'.join(lines)


def _format_sentinel(data: dict) -> str:
    if not data:
        return 'Sentinel: no data'
    lines = ['Sentinel Signals:']
    ws = data.get('watchlist_signals', [])
    if ws:
        lines.append(f"  Watchlist signals: {len(ws)} tickers")
        for s in ws[:4]:
            lines.append(
                f"    {s.get('symbol')}: {s.get('signal_type','?')} | "
                f"{s.get('buy_count',0)} buys"
            )
    td = data.get('top_discoveries', [])
    if td:
        lines.append(f"  Top discoveries: {len(td)}")
        for d in td[:3]:
            lines.append(f"    {d.get('symbol')}: {d.get('signal_type','?')} score:{d.get('score',0)}")
    return '\n'.join(lines)


def _format_norman(data: dict) -> str:
    if not data:
        return 'Norman Report: not available'
    lines = [f"Norman Statistical Analysis ({data.get('date', '?')}):"]
    for agent, report in data.get('agent_reports', {}).items():
        verdict = report.get('verdict', '?')
        lines.append(
            f"  {agent.capitalize()}: verdict={verdict} | "
            f"WR={report.get('win_rate', 0):.1f}% | "
            f"PF={report.get('profit_factor', 0):.3f} | "
            f"Sharpe={report.get('sharpe', 0):.3f} | "
            f"MaxDD={report.get('max_drawdown_pct', 0):.1f}% | "
            f"Trades={report.get('total_trades', 0)} | "
            f"Expectancy=${report.get('expectancy', 0):.2f}"
        )
        rec = report.get('recommendation', '')
        if rec:
            lines.append(f"    Norman says: {rec[:300]}")
    alerts = data.get('alerts', [])
    if alerts:
        lines.append('  Norman Alerts:')
        for a in alerts:
            lines.append(f'    ⚠ {a}')
    recs = data.get('recommendations', [])
    if recs:
        lines.append('  Norman Recommendations:')
        for r in recs[:4]:
            lines.append(f'    • {r[:200]}')
    return '\n'.join(lines)


# ─── Telegram ───────────────────────────────────────────────────────────────────

STATUS_ICONS = {
    'active':   '🟢',
    'running':  '🟢',
    'inactive': '🔴',
    'failed':   '🔴',
    'unknown':  '⚫',
}


def _svc_icon(status: str) -> str:
    for k, icon in STATUS_ICONS.items():
        if k in status.lower():
            return icon
    return '⚫'


def _build_telegram_report(result: dict, svc_statuses: dict) -> str:
    today = result.get('date', datetime.now(timezone.utc).strftime('%Y-%m-%d'))
    fs    = result.get('financial_summary', {})
    bdown = fs.get('breakdown', {})
    ops   = result.get('operations_briefing', '')
    ag    = result.get('agent_status', {})
    recs  = result.get('recommendations', [])
    alerts = result.get('alerts', [])

    def fmt(val):
        try:
            f = float(val)
            return f'+${f:.2f}' if f >= 0 else f'-${abs(f):.2f}'
        except Exception:
            return str(val)

    total_pnl = fs.get('total_pnl_today', 0)
    nw = fs.get('net_worth', 0)

    lines = [
        f'DAILY BRIEFING | {today}',
        '',
    ]

    try:
        pnl_f = float(total_pnl)
        if pnl_f < -50:
            lines.append(f'The coffers have bled {fmt(total_pnl)} this eve. I am... displeased.')
        elif pnl_f < 0:
            lines.append(f'A minor wound today. {fmt(total_pnl)} lost. It shall be noted.')
        elif pnl_f == 0:
            lines.append('The coffers neither grew nor shrank. A stagnant eve.')
        else:
            lines.append(f'A productive eve. {fmt(total_pnl)} claimed for the operation.')
    except Exception:
        lines.append(f'Total P&L Today: {fmt(total_pnl)}')

    lines += [
        '',
        '\u2620\ufe0f THE LEDGER',
        f'  Manual:  {fmt(bdown.get("manual_trading", 0))}',
        f'  Blade:   {fmt(bdown.get("blade", 0))}',
        f'  Crisp:   {fmt(bdown.get("crisp", 0))}',
        f'  Edge:    {fmt(bdown.get("edge", 0))}',
        f'  Tao:     {fmt(bdown.get("tao", 0))}',
        '',
        f'MTD P&L: {fmt(fs.get("mtd_pnl", 0))}',
        f'API Costs Today: ${fs.get("api_costs_today", 0):.4f} | MTD: ${fs.get("api_costs_mtd", 0):.4f}',
    ]

    try:
        nw_f = float(nw)
        verdict = 'acceptable. For now.' if nw_f > 40000 else 'concerning.'
        lines.append(f'Your net worth stands at ${nw_f:,.2f}. It is... {verdict}')
    except Exception:
        lines.append(f'Net Worth: ${nw:,.2f}')

    lines += [
        '',
        '\U0001fa78 OPERATIONS',
        ops,
        '',
        '\u2694\ufe0f AGENT STATUS',
    ]

    for svc, status in svc_statuses.items():
        icon = _svc_icon(status)
        lines.append(f'  {svc}: {icon} {status}')

    for agent, note in ag.items():
        lines.append(f'  {agent}: {note}')

    if recs:
        lines.append('')
        lines.append('\U0001f4dc MY COUNSEL')
        for r in recs:
            lines.append(f'  \u2022 {r}')

    lines.append('')
    if alerts:
        lines.append('I have identified wounds in our operation:')
        for a in alerts:
            lines.append(f'  \u26a1 {a}')
        lines.append('They shall be addressed, or heads shall roll.')
    else:
        lines.append('No wounds detected. The operation endures.')

    fix_prompts = result.get('fix_prompts', [])
    if fix_prompts:
        lines.append('')
        lines.append('\U0001f5e1\ufe0f REMEDIES PRESCRIBED')
        SEV_ICONS = {'critical': '\u26a1', 'warning': '\u26a0\ufe0f', 'info': '\u2139\ufe0f'}
        for fp in fix_prompts:
            sev  = (fp.get('severity') or 'info').lower()
            icon = SEV_ICONS.get(sev, '\u2139\ufe0f')
            prob = fp.get('problem', '?')[:80]
            lines.append(f'  {icon} {sev.upper()}: {prob}')
            lines.append(f'     \u2192 Fix prompt saved to victoria_report.json')

    lines.append('')
    lines.append('\u2014 Victoria')

    body = '\n'.join(lines)
    return wrap_message('victoria', body)


TG_MAX = 4000  # Telegram's limit is 4096; keep headroom


def _tg_send_chunk(text: str) -> bool:
    """Send a single chunk. Returns True on success."""
    try:
        resp = requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={'chat_id': TELEGRAM_CHAT_ID, 'text': text},
            timeout=15,
        )
        if not resp.ok:
            print(f'[victoria] Telegram error {resp.status_code}: {resp.text[:200]}')
            return False
        return True
    except Exception as e:
        print(f'[victoria] Telegram exception: {e}')
        return False


def _send_telegram(text: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print('[victoria] Telegram not configured — skipping')
        return
    if len(text) <= TG_MAX:
        if _tg_send_chunk(text):
            print('[victoria] Telegram report sent')
        return
    # Split at newlines to stay under limit
    chunks = []
    current = ''
    for line in text.split('\n'):
        candidate = current + ('\n' if current else '') + line
        if len(candidate) > TG_MAX:
            if current:
                chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    for i, chunk in enumerate(chunks, 1):
        ok = _tg_send_chunk(chunk)
        print(f'[victoria] Telegram chunk {i}/{len(chunks)} {"sent" if ok else "FAILED"}')
        if not ok:
            break


# ─── Main ───────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are Victoria, the CFO and Chief of Staff for JCF HQ — \
a multi-agent AI trading operation run by Jase.

You receive a full data dump of the operation's current state, \
including Norman's latest statistical analysis of each agent. \
Your job is to produce three reports:

REPORT 1 — DAILY FINANCIAL SUMMARY
Analyze all P&L data and produce a clear financial picture:
- Total P&L today across all agents and manual trading
- P&L breakdown by source (manual trades, Blade, Crisp, \
Edge, Tao)
- MTD (month to date) performance
- Current bankroll status for each account
- Net worth snapshot (trading accounts + bank + crypto + investments)
- API costs today and MTD
- ROI calculation: are the API costs justified by the returns?

REPORT 2 — DAILY OPERATIONS BRIEFING
Plain English summary of what happened in the system:
- Which agents ran and what they did
- Any agents that are down or erroring
- Notable wins or losses
- Changes or updates that were made today
- What to watch for tomorrow
- Any recommendations (reduce exposure, increase size, \
pause an agent, etc.)

REPORT 3 — FIX PROMPTS (only when actionable problems are detected)

When you identify a problem — an agent losing money, a broken API, \
a strategy underperforming, a data gap — generate a specific Claude \
Code prompt that Jase can paste directly to fix it.

Use Norman's statistical verdicts as inputs: if Norman flags a FAIL \
verdict or critical alert, translate that into a concrete fix prompt.

For each actionable problem:
1. State the problem clearly with specific numbers from the data
2. Identify the root cause (use Norman's analysis where available)
3. Write 2-3 sentences of YOUR strategic diagnosis before the prompt. \
This is your opinion as CFO — why you think this is happening and \
what you would do about it. Be direct, no hedging. Write in your \
voice: cold, aristocratic, blunt. Example: \
"The bleeding from Edge is not accidental. It overtraded noise for \
weeks with no real structural edge. The new 1H strategy must prove \
itself before I recommend further intervention."
4. Write a complete Claude Code prompt — include file paths, \
specific instructions, and verification steps
5. Estimate the impact of the fix

Rules:
- Only generate fix prompts for ACTIONABLE problems (broken code, \
wrong config, missing data pipeline, bad position sizing)
- Do NOT generate fix prompts for: "insufficient data", \
"need more trades", market conditions, or normal variance
- If Norman says FAIL, always generate a fix prompt
- If Norman says INSUFFICIENT_DATA but flags a structural issue \
(e.g., missing settlement data, broken logging), generate a fix prompt
- Minimum 1, maximum 5 fix prompts per report

Be direct and honest. If something is losing money, say so clearly. \
If an agent should be paused, recommend it. Jase relies on your \
analysis to make decisions.

Use actual numbers from the data — don't generalize. \
"Blade made $18.40 across 2 trades" not "Blade had a good day."

OUTPUT FORMAT (respond in valid JSON only, no markdown):
{
  "date": "YYYY-MM-DD",
  "financial_summary": {
    "total_pnl_today": 0.00,
    "breakdown": {
      "manual_trading": 0.00,
      "blade": 0.00,
      "crisp": 0.00,
      "edge": 0.00,
      "tao": 0.00
    },
    "mtd_pnl": 0.00,
    "net_worth": 0.00,
    "api_costs_today": 0.00,
    "api_costs_mtd": 0.00,
    "roi_assessment": "string"
  },
  "operations_briefing": "Plain English paragraph...",
  "agent_status": {
    "lens": "ran at 04:55, all instruments covered",
    "blade": "next session: London 07:55",
    "tao": "staking, next report Saturday"
  },
  "recommendations": [
    "string recommendation 1"
  ],
  "alerts": ["any urgent issues"],
  "fix_prompts": [
    {
      "problem": "one-line problem description with specific numbers",
      "severity": "critical",
      "root_cause": "specific root cause — cite Norman's metrics if relevant",
      "fix_prompt": "Complete Claude Code prompt Jase can paste directly. Include: file paths, what to read, what to change, verification steps.",
      "estimated_impact": "what this fix will change and by how much"
    }
  ]
}"""


def run_victoria() -> dict:
    today  = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    now_ts = datetime.now(timezone.utc).isoformat()

    print(f'[victoria] Starting daily analysis — {today}')

    # ── 1. Collect all data ──
    tl_data     = _load_json(DASHBOARD / 'tradelocker_trades.json', 'tradelocker')
    lens_data   = _load_json(DASHBOARD / 'market_bias.json',        'market_bias')
    plaid_data  = _load_json(DASHBOARD / 'plaid_data.json',         'plaid')
    kraken_data = _load_json(DASHBOARD / 'kraken_data.json',        'kraken')
    sent_data   = _load_json(DASHBOARD / 'sentinel_data.json',      'sentinel')
    edge_data   = _load_json(DASHBOARD / 'edge_portfolio.json',     'edge')
    tao_data    = _load_json(DASHBOARD / 'tao_portfolio.json',      'tao')
    apnl_data   = _load_json(DASHBOARD / 'agent_pnl.json',          'agent_pnl')
    nw_data     = _load_json(DASHBOARD / 'net_worth.json',          'net_worth')
    rb_data     = _load_json(DASHBOARD / 'robinhood_data.json',     'robinhood')
    tw_data     = _load_json(DASHBOARD / 'trustwallet_data.json',   'trustwallet')
    norman_data = _load_json(NORMAN_PATH,                           'norman_report')

    if norman_data:
        print(f'[victoria] Norman report loaded — dated {norman_data.get("date","?")}')
    else:
        print('[victoria] Norman report not available')

    # ── 2. Aggregate API costs ──
    api_costs = aggregate_api_costs()
    print(
        f'[victoria] API costs — today: ${api_costs["total_today"]:.4f} | '
        f'MTD: ${api_costs["total_mtd"]:.4f}'
    )

    # ── 3. Check service statuses ──
    svc_statuses = check_service_statuses()
    print(f'[victoria] Service statuses: {svc_statuses}')

    # ── 4. Format data for prompt ──
    tl_text     = _format_tradelocker(tl_data)      if tl_data   else 'TradeLocker: unavailable'
    edge_text   = _format_edge(edge_data)            if edge_data else 'Edge: unavailable'
    tao_text    = _format_tao(tao_data)              if tao_data  else 'Tao: unavailable'
    apnl_text   = _format_agent_pnl(apnl_data)      if apnl_data else 'Blade/Crisp: unavailable'
    accts_text  = _format_accounts(plaid_data, rb_data, kraken_data, tw_data, nw_data)
    lens_text   = _format_lens_bias(lens_data)       if lens_data else 'Lens: unavailable'
    sent_text   = _format_sentinel(sent_data)        if sent_data else 'Sentinel: unavailable'
    norman_text = _format_norman(norman_data)        if norman_data else 'Norman Report: not yet run'

    svc_text = (
        'Service Status (systemctl):\n'
        + '\n'.join(f'  {svc}: {status}' for svc, status in svc_statuses.items())
        + '\n  NOTE: crisp-v5 is intentionally stopped — Crisp is being repurposed. Do not flag as an error.'
    )

    api_text = (
        f"API Costs (all agents):\n"
        f"  Today total: ${api_costs['total_today']:.4f}\n"
        f"  MTD total:   ${api_costs['total_mtd']:.4f}\n"
    ) + '\n'.join(
        f"  {agent}: today ${vals['today']:.4f} | mtd ${vals['mtd']:.4f}"
        for agent, vals in api_costs['per_agent'].items()
    )

    user_message = (
        f"Today: {today} | Analysis timestamp: {now_ts}\n\n"
        f"{tl_text}\n\n"
        f"{apnl_text}\n\n"
        f"{edge_text}\n\n"
        f"{tao_text}\n\n"
        f"{accts_text}\n\n"
        f"{lens_text}\n\n"
        f"{sent_text}\n\n"
        f"{svc_text}\n\n"
        f"{api_text}\n\n"
        f"{norman_text}\n\n"
        "Analyze all the above data and respond with ONLY valid JSON — "
        "no markdown, no prose outside the JSON object. "
        "Include fix_prompts for every actionable problem Norman flagged "
        "or that you identify in the data."
    )

    # ── 5. Call Claude ──
    print(f'[victoria] Calling {MODEL} (Codex via gateway)...')

    # Codex has no separate system slot — persona is prepended into the message.
    result_text  = _run_codex(SYSTEM_PROMPT, user_message)
    total_input  = 0  # Codex free tier — no Anthropic token billing
    total_output = 0

    print(f'[victoria] Turn 1 — {len(result_text or "")} chars returned')
    result = _extract_json(result_text) if result_text else None

    # Fallback turn — re-ask for JSON only, echoing the prior attempt.
    if result is None and result_text:
        print('[victoria] No JSON in turn 1 — requesting JSON-only follow-up...')
        follow_up_msg = (
            user_message
            + '\n\nYOUR PREVIOUS RESPONSE:\n' + result_text
            + '\n\nYour analysis is complete. Now output ONLY the final JSON '
              'object — no prose, no markdown, no explanation. '
              'Start your response with { and end with }.'
        )
        result_text2 = _run_codex(SYSTEM_PROMPT, follow_up_msg)
        result = _extract_json(result_text2) if result_text2 else None
        if result is None:
            print(f'[victoria] Turn 2 snippet:\n{(result_text2 or "")[:400]}')

    # ── 6. Track cost ──
    cost_usd = _save_cost(total_input, total_output)
    print(f'[victoria] Total — {total_input} in + {total_output} out | ${cost_usd:.4f}')

    # Fallback result if parsing failed entirely
    if result is None:
        print('[victoria] No valid JSON after 2 turns — using minimal result')
        result = {
            'date':               today,
            'financial_summary':  {'total_pnl_today': 0, 'breakdown': {}, 'mtd_pnl': 0,
                                   'net_worth': 0, 'api_costs_today': api_costs['total_today'],
                                   'api_costs_mtd': api_costs['total_mtd'],
                                   'roi_assessment': 'Analysis failed — no JSON returned'},
            'operations_briefing': 'Victoria Brain returned no parseable JSON today.',
            'agent_status':       {},
            'recommendations':    [],
            'alerts':             ['JSON parse failure — check victoria.log'],
        }
    else:
        # Ensure date is set
        result['date'] = today
        # Inject actual API costs
        result.setdefault('financial_summary', {})
        result['financial_summary']['api_costs_today'] = api_costs['total_today']
        result['financial_summary']['api_costs_mtd']   = api_costs['total_mtd']
        # Ensure fix_prompts key always exists
        result.setdefault('fix_prompts', [])

    # ── 7. Save victoria_report.json ──
    result['_meta'] = {
        'input_tokens':     total_input,
        'output_tokens':    total_output,
        'cost_usd':         cost_usd,
        'model':            MODEL,
        'timestamp':        now_ts,
        'api_costs':        api_costs,
        'svc_statuses':     svc_statuses,
        'norman_available': norman_data is not None,
        'norman_date':      (norman_data or {}).get('date'),
        'fix_prompts_count': len(result.get('fix_prompts', [])),
    }

    DASHBOARD.mkdir(parents=True, exist_ok=True)
    try:
        with open(REPORT_PATH, 'w') as f:
            json.dump(result, f, indent=2)
        print(f'[victoria] victoria_report.json written')
    except Exception as e:
        print(f'[victoria] Error writing report: {e}')

    # ── 8. Append to victoria_history.json ──
    try:
        history = _load_json(HISTORY_PATH, 'victoria_history') or []
        if not isinstance(history, list):
            history = []
        history.append(result)
        with open(HISTORY_PATH, 'w') as f:
            json.dump(history, f, indent=2)
        print(f'[victoria] victoria_history.json updated ({len(history)} entries)')
    except Exception as e:
        print(f'[victoria] Error updating history: {e}')

    # ── 9. Send Telegram ──
    tg_msg = _build_telegram_report(result, svc_statuses)
    _send_telegram(tg_msg)

    print(
        f'[victoria] Done — P&L today: ${result.get("financial_summary",{}).get("total_pnl_today", 0):.2f} | '
        f'${cost_usd:.4f} API cost'
    )
    return result


# ─── Weekly Report ─────────────────────────────────────────────────────────────

WEEKLY_SYSTEM_PROMPT = """\
You are Victoria, the CFO and Chief of Staff for JCF HQ — \
a multi-agent AI trading operation run by Jase.

You are writing the WEEKLY TRIBUNAL — a summary of the past 7 days.

Review all data and produce a weekly report in this JSON format:

{
  "week_start": "YYYY-MM-DD",
  "week_end": "YYYY-MM-DD",
  "net_worth_change": 0.00,
  "total_pnl_week": 0.00,
  "best_agent": "name",
  "worst_agent": "name",
  "api_costs_week": 0.00,
  "top_wounds": [
    {"issue": "description", "action": "recommended fix"}
  ],
  "matters_of_note": ["observation 1", "observation 2"],
  "verdict": "2-3 sentence CFO verdict on the week",
  "scouting_verdict": "2-3 sentences ruling on this week's scouting findings — which, if any, are worth the coin and the maintenance burden. Name the one you would actually adopt, or say plainly that none earn their keep this week."
}

You also receive a SCOUTING REPORT — tools, skills, and MCP servers found \
this week (this desk was Lucy's until 2026-07-25; it is yours now). Rule on \
it as CFO: what is worth adopting, what is noise, what costs more than it \
returns. Populate "scouting_verdict".

Be direct, use actual numbers, and be honest about what is \
working and what is not."""


def run_victoria_weekly(with_scout: bool = False) -> dict:
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    print(f'[victoria-weekly] Starting weekly tribunal — {today}')

    # Load same data sources as daily
    tl_data     = _load_json(DASHBOARD / 'tradelocker_trades.json', 'tradelocker')
    lens_data   = _load_json(DASHBOARD / 'market_bias.json',        'market_bias')
    plaid_data  = _load_json(DASHBOARD / 'plaid_data.json',         'plaid')
    kraken_data = _load_json(DASHBOARD / 'kraken_data.json',        'kraken')
    edge_data   = _load_json(DASHBOARD / 'edge_portfolio.json',     'edge')
    tao_data    = _load_json(DASHBOARD / 'tao_portfolio.json',      'tao')
    apnl_data   = _load_json(DASHBOARD / 'agent_pnl.json',          'agent_pnl')
    nw_data     = _load_json(DASHBOARD / 'net_worth.json',          'net_worth')
    rb_data     = _load_json(DASHBOARD / 'robinhood_data.json',     'robinhood')
    tw_data     = _load_json(DASHBOARD / 'trustwallet_data.json',   'trustwallet')
    norman_data = _load_json(NORMAN_PATH,                           'norman_report')

    # Load Victoria's daily history for 7-day aggregation
    history = _load_json(HISTORY_PATH, 'victoria_history') or []
    recent_dailies = [
        h for h in (history if isinstance(history, list) else [])
        if h.get('date', '') >= (datetime.now(timezone.utc) - __import__('datetime').timedelta(days=7)).strftime('%Y-%m-%d')
    ]

    api_costs = aggregate_api_costs()
    svc_statuses = check_service_statuses()

    # ── Scouting desk (absorbed from Lucy 2026-07-25) ──────────────────────────
    # Runs as an additional weekly output alongside the CFO tribunal. Its
    # findings are folded into this prompt so Victoria rules on them in her own
    # voice rather than sending a second, disconnected report. A failure here
    # must never take the tribunal down — the CFO report is the primary product.
    # ⛔ DEFAULT OFF. Victoria's weekly cron line is ALREADY LIVE (Sun 8:00 AM ET).
    #    Defaulting the scout ON would have silently activated Lucy's absorbed
    #    function on a schedule this Sunday without approval — exactly what the
    #    consolidation brief said not to do. It runs only when explicitly asked
    #    (--with-scout / VICTORIA_WITH_SCOUT=1) until Jase signs off.
    if os.getenv('VICTORIA_WITH_SCOUT', '').strip() in ('1', 'true', 'yes'):
        with_scout = True
    scout_result, scout_text = None, 'SCOUTING REPORT: not run (scouting desk held pending approval).'
    if with_scout:
        try:
            import victoria_scout
            scout_result = victoria_scout.research_tools(send_telegram=False)
            scout_text = victoria_scout.summarize_for_tribunal(scout_result)
            print(f'[victoria-weekly] Scout: {len(scout_result.get("findings", []))} findings')
        except Exception as e:
            print(f'[victoria-weekly] Scout failed (non-fatal): {e}')
            scout_text = f'SCOUTING REPORT: failed to run ({e}).'

    # Build data dump
    tl_text     = _format_tradelocker(tl_data)  if tl_data   else 'TradeLocker: unavailable'
    edge_text   = _format_edge(edge_data)        if edge_data else 'Edge: unavailable'
    tao_text    = _format_tao(tao_data)          if tao_data  else 'Tao: unavailable'
    apnl_text   = _format_agent_pnl(apnl_data)  if apnl_data else 'Blade/Crisp: unavailable'
    accts_text  = _format_accounts(plaid_data, rb_data, kraken_data, tw_data, nw_data)
    norman_text = _format_norman(norman_data)    if norman_data else 'Norman Report: not available'

    daily_summaries = ''
    if recent_dailies:
        daily_summaries = 'DAILY REPORTS FROM PAST 7 DAYS:\n'
        for d in recent_dailies[-7:]:
            fs = d.get('financial_summary', {})
            daily_summaries += (
                f"  {d.get('date','?')}: P&L={fs.get('total_pnl_today',0)}, "
                f"MTD={fs.get('mtd_pnl',0)}, NW={fs.get('net_worth',0)}\n"
            )

    user_message = (
        f"Today: {today} | WEEKLY TRIBUNAL\n\n"
        f"{daily_summaries}\n"
        f"{tl_text}\n\n{apnl_text}\n\n"
        f"{edge_text}\n\n{tao_text}\n\n{accts_text}\n\n"
        f"{norman_text}\n\n"
        f"{scout_text}\n\n"
        f"API costs MTD: ${api_costs['total_mtd']:.4f}\n\n"
        "Analyze the full week and respond with ONLY valid JSON."
    )

    print(f'[victoria-weekly] Calling {MODEL} (Codex via gateway)...')
    result_text  = _run_codex(WEEKLY_SYSTEM_PROMPT, user_message)
    total_input  = 0  # Codex free tier — no Anthropic token billing
    total_output = 0
    print(f'[victoria-weekly] {len(result_text or "")} chars returned')

    result = _extract_json(result_text) if result_text else None
    cost_usd = _save_cost(total_input, total_output)

    if result is None:
        print('[victoria-weekly] No JSON returned')
        result = {
            'week_start': today,
            'week_end': today,
            'verdict': 'Weekly tribunal failed to produce JSON.',
            'top_wounds': [],
            'matters_of_note': [],
        }

    # Build Telegram message in Victoria's voice
    wounds = result.get('top_wounds', [])
    notes = result.get('matters_of_note', [])
    verdict = result.get('verdict', '')
    best = result.get('best_agent', '?')
    worst = result.get('worst_agent', '?')

    def fmt_w(val):
        try:
            f = float(val)
            return f'+${f:.2f}' if f >= 0 else f'-${abs(f):.2f}'
        except Exception:
            return str(val)

    tg_lines = [
        'WEEKLY TRIBUNAL',
        '',
        f'Week of {result.get("week_start", "?")} to {result.get("week_end", "?")}',
        '',
        '⚔️ THE NUMBERS',
        f'Net worth change: {fmt_w(result.get("net_worth_change", 0))}',
        f'Total P&L this week: {fmt_w(result.get("total_pnl_week", 0))}',
        f'Best performing: {best}',
        f'Worst performing: {worst}',
        f'API costs this week: ${result.get("api_costs_week", 0):.4f}',
        '',
    ]

    if wounds:
        tg_lines.append('\U0001fa78 THE THREE WOUNDS')
        for w in wounds[:3]:
            tg_lines.append(f'• {w.get("issue", "?")}')
            tg_lines.append(f'  → {w.get("action", "?")}')
        tg_lines.append('')

    if notes:
        tg_lines.append('\U0001f4dc MATTERS OF NOTE')
        for n in notes[:5]:
            tg_lines.append(f'• {n}')
        tg_lines.append('')

    if verdict:
        tg_lines.append('⚰️ MY VERDICT')
        tg_lines.append(verdict)
        tg_lines.append('')

    # Scouting desk (absorbed from Lucy) — reported inside the tribunal.
    if scout_result is not None:
        finds = scout_result.get('findings', [])
        highs = [f for f in finds if f.get('priority') == 'HIGH']
        tg_lines.append('\U0001f50d THE SCOUTING DESK')
        tg_lines.append(f'{len(finds)} brought before me ({len(highs)} HIGH). '
                        f'Top pick: {scout_result.get("top_pick", "none")}')
        for f in highs[:3]:
            tg_lines.append(f'• {f.get("name", "?")} [{f.get("category", "?")}]')
        sv = result.get('scouting_verdict')
        if sv:
            tg_lines.append(sv)
        tg_lines.append('')

    tg_lines.append('— Victoria')

    body = '\n'.join(tg_lines)
    _send_telegram(wrap_message('victoria', body))

    # Save weekly report
    weekly_path = DASHBOARD / 'victoria_weekly.json'
    result['scouting'] = scout_result
    result['_meta'] = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'cost_usd': cost_usd,
        'model': MODEL,
        'scout_findings': len((scout_result or {}).get('findings', [])),
        'absorbed': ['lucy scouting (2026-07-25)'],
    }
    try:
        with open(weekly_path, 'w') as f:
            json.dump(result, f, indent=2)
        print(f'[victoria-weekly] Weekly report saved to {weekly_path}')
    except Exception as e:
        print(f'[victoria-weekly] Error writing: {e}')

    print(f'[victoria-weekly] Done | ${cost_usd:.4f} API cost')
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Victoria — CFO & Chief of Staff')
    parser.add_argument('--weekly', action='store_true', help='Run weekly tribunal')
    parser.add_argument('--with-scout', action='store_true',
                        help='Weekly only: also run the scouting desk (absorbed from Lucy). '
                             'OFF by default — Victoria\'s weekly cron is live and the '
                             'scouting desk is held pending approval.')
    args = parser.parse_args()

    if args.weekly:
        run_victoria_weekly(with_scout=args.with_scout)
    else:
        run_victoria()
