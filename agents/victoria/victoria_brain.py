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

# ── Validation sources (repointed 2026-07-27) ─────────────────────────────────
# Victoria used to read dashboard/norman_report.json. Norman was retired
# 2026-07-25 and his last report — still on disk, still being read every
# morning — graded Blade off 330 dormant TradeLocker trades and carried an
# impossible 468% max drawdown for Chad. That is what reached Jase's phone as
# "BLADE FAIL: 330 trades" and "CRISP CRITICAL: 468.0% maximum drawdown".
#
# The consolidation replaced Norman with two validators that already refuse to
# grade dead feeds. Victoria's briefings now read THOSE, the same corrected
# sources scripts/risk_validation.py drives:
LENS_VALIDATION_PATH     = DASHBOARD / 'lens_validation.json'      # Blade, Edge
VICTORIA_VALIDATION_PATH = DASHBOARD / 'victoria_validation.json'  # Jerry, Chad
# norman_report.json is quarantined (dashboard/_archive/pre_reset_2026-07-27/).
# Do not re-add it here.

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
    """Victoria's model call, via the shared router (scripts/llm_router.py).

    Name kept for call-site compatibility; the routing is no longer Codex-only.
    Chain for the 'report_writing' job:

        Codex  ->  nvidia/nemotron-3-super-120b-a12b:free  (OpenRouter)
               ->  deepseek/deepseek-v3.2                  (OpenRouter)
               ->  Anthropic claude-sonnet-4-6             (safety net)

    Replaces the ad-hoc opt-in Anthropic fallback added earlier the same day.
    That was the right call when Anthropic was the only alternative — routing
    an agent to a paid provider is a spend decision. Now the first two
    fallbacks are free-tier OpenRouter models, so the default chain costs
    nothing and Anthropic is genuinely a last resort rather than hop two.

    Which model actually served each run is logged to
    logs/llm_router_spend.json for cost attribution.
    """
    from llm_router import route
    text, meta = route('report_writing', system_prompt, user_message,
                       agent='victoria', timeout=timeout)
    if text:
        print(f"[victoria] served by {meta.get('provider')}:"
              f"{meta.get('model')} (hop {meta.get('hop')})")
    else:
        print(f"[victoria] all routing hops failed: {meta.get('error')}")
    return text


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
    """Safe float conversion.

    Handles percent/currency STRINGS. Feeds store win_rate as "53.3%"; the old
    version could not parse that and silently returned 0.0, which is why
    Victoria reported "0.0% win rate" in the same breath as "176W / 139L".
    Coercing a value we cannot read to 0.0 is exactly the failure Rule #9 is
    about — an unparseable number is unknown, not zero.
    """
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        pass
    try:
        cleaned = str(val).strip().replace('%', '').replace('$', '').replace(',', '')
        return float(cleaned)
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


# ══════════════════════════════════════════════════════════════════════════════
# Net worth — computed here, NOT by the model
# ══════════════════════════════════════════════════════════════════════════════
#
# Why this function exists (2026-07-30). `net_worth` was a field in the JSON
# OUTPUT TEMPLATE the model fills in — there was no deterministic computation
# anywhere. The model was handed a list of account balances and asked to total
# them, so the reported figure drifted with whatever model happened to answer:
#
#     $36,578  — correct: the exact sum of the four real-money accounts
#     $38,578  — +$2,000, no source
#     $41,578  — +$5,000, the size of Edge's PAPER balance
#
# Arithmetic is not a job for a language model, and "net worth" in particular
# must be reproducible: same inputs, same number, every run. So the total is
# computed in Python from the same feeds, injected into the prompt as an
# authoritative value, and — because a prompt instruction is not a gate
# (Critical Rule #10) — OVERWRITTEN in the result after the model returns.
#
# PAPER MONEY IS NOT NET WORTH. Alpaca (Jerry) and the OANDA practice books
# (Blade, Edge) are excluded by construction and listed under `excluded` so the
# omission is visible rather than assumed. This matches
# `scripts/net_worth_report.py`, which already drew that line correctly.

_NW_STALE_DAYS = 20   # portfolio syncs run on the 1st and 15th, so <=15d is normal


def _feed_age_days(filename: str):
    """Age of a dashboard feed in days, preferring an embedded timestamp over
    file mtime (Rule #9: a sync rewriting a file keeps mtime fresh while the
    payload rots)."""
    data = _load_json(DASHBOARD / filename, filename) or {}
    for key in ('last_update', 'last_updated', 'updated', 'timestamp'):
        raw = data.get(key)
        if isinstance(raw, str) and raw:
            try:
                ts = datetime.fromisoformat(raw.replace('Z', '+00:00'))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                return (datetime.now(timezone.utc) - ts).total_seconds() / 86400
            except ValueError:
                pass
    try:
        mtime = (DASHBOARD / filename).stat().st_mtime
        return (datetime.now(timezone.utc).timestamp() - mtime) / 86400
    except OSError:
        return None


def compute_net_worth(plaid: dict, robinhood: dict, kraken: dict,
                      trustwallet: dict, net_worth_cfg: dict) -> dict:
    """Deterministic net worth from the real-money feeds.

    Returns {total, sources, excluded, missing, computed_at}. Pure arithmetic —
    no model, no rounding heuristics, no invented values. A feed that fails to
    load contributes nothing AND is named in `missing`, so a partial total can
    never be mistaken for a complete one.
    """
    sources, missing = [], []

    def add(label, value, filename, note=''):
        if value is None:
            missing.append(label)
            return
        age = _feed_age_days(filename) if filename else None
        sources.append({
            'label': label,
            'value': round(float(value), 2),
            'age_days': round(age, 1) if age is not None else None,
            'stale': bool(age is not None and age > _NW_STALE_DAYS),
            'note': note,
        })

    add('Robinhood', _f((robinhood or {}).get('total_equity')) if robinhood else None,
        'robinhood_data.json')
    add('Kraken', _f((kraken or {}).get('total_usd')) if kraken else None,
        'kraken_data.json')
    add('TrustWallet', _f((trustwallet or {}).get('total_usd')) if trustwallet else None,
        'trustwallet_data.json')

    if plaid:
        for acct in plaid.get('accounts', []) or []:
            name = str(acct.get('name', '?')).strip()
            label = name if name.lower().startswith('truist') else f'Truist {name}'
            add(label, _f(acct.get('balance')), 'plaid_data.json')
    else:
        missing.append('Banks (Plaid)')

    # Manually-maintained lines, counted only when non-zero.
    for key, label in (('hysa', 'HYSA'), ('life_insurance', 'Life insurance')):
        v = _f((net_worth_cfg or {}).get(key))
        if v:
            add(label, v, 'net_worth.json', note='manual')

    total = round(sum(s['value'] for s in sources), 2)

    return {
        'total': total,
        'sources': sources,
        'missing': missing,
        'excluded': [
            'Alpaca / Jerry (PAPER)',
            'OANDA practice books — Blade, Edge (PAPER)',
        ],
        'computed_at': datetime.now(timezone.utc).isoformat(),
        'method': 'deterministic sum of real-money feeds (scripts-side, not model-computed)',
    }


def _format_net_worth(nw: dict) -> str:
    """Render the computed net worth for the prompt — as a value the model must
    quote verbatim, not a set of numbers for it to add up."""
    lines = [
        'NET WORTH (ALREADY COMPUTED — DO NOT RECALCULATE):',
        f"  TOTAL REAL NET WORTH: ${nw['total']:,.2f}",
        '  Components:',
    ]
    for s in nw['sources']:
        age = '' if s['age_days'] is None else f"  [{s['age_days']:.0f}d old{' — STALE' if s['stale'] else ''}]"
        note = f"  ({s['note']})" if s['note'] else ''
        lines.append(f"    {s['label']}: ${s['value']:,.2f}{note}{age}")
    if nw['missing']:
        lines.append(f"  NOT COUNTED (feed unavailable): {', '.join(nw['missing'])}")
    lines.append(f"  EXCLUDED as paper money: {', '.join(nw['excluded'])}")
    lines.append('  You MUST use the TOTAL above verbatim in financial_summary.net_worth. '
                 'Do not add, round, or re-derive it. Paper balances are NOT net worth.')
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


# Internal id -> the name Jase sees. Critical Rule #7: code/JSON keys use the
# internal id, user-facing text uses the display name. Norman's report printed
# `agent.capitalize()`, which is how "crisp" reached Jase's phone as "Crisp"
# when the agent is called Chad.
_VALIDATION_DISPLAY = {
    'blade': 'Blade', 'edge': 'Edge', 'jerry': 'Jerry', 'crisp': 'Chad',
}

# Verdicts where the deterministic layer DECLINED to grade. Victoria may
# describe the gap but must not issue or relay a grade (Critical Rule #10).
_UNGRADEABLE = {'NO_DATA', 'STALE_DATA', 'INSUFFICIENT_DATA', 'NO_BALANCE', 'UNKNOWN'}


def _format_validation(lens_data: dict, victoria_data: dict) -> str:
    """Render the two validators' output for the briefing prompt.

    Replaces _format_norman(). Three behavioural differences that matter:

      1. Reads lens_validation.json + victoria_validation.json, not the
         retired norman_report.json.
      2. Never prints a number for an ungradeable verdict. The old version
         formatted `report.get('win_rate', 0)` etc. unconditionally, so a
         NO_DATA agent still rendered "WR=0.0% | PF=0.000" — numbers the model
         then narrated as real findings.
      3. Names agents by display name (crisp -> Chad).
    """
    lines = []
    for source_name, data, covers in (
        ('Lens validation (Blade, Edge)', lens_data, 'blade/edge'),
        ('Victoria validation (Jerry, Chad)', victoria_data, 'jerry/chad'),
    ):
        if not data:
            lines.append(f'{source_name}: NOT YET RUN — no verdicts available. '
                         f'Do not infer performance for {covers}.')
            continue
        if data.get('_QUARANTINED'):
            lines.append(f'{source_name}: QUARANTINED SOURCE — ignore entirely.')
            continue

        lines.append(f"{source_name} — generated {data.get('date', '?')}:")
        for agent, report in (data.get('agent_reports') or {}).items():
            shown = _VALIDATION_DISPLAY.get(agent, agent.capitalize())
            verdict = (report.get('verdict') or 'UNKNOWN').upper()
            n = report.get('total_trades', report.get('n', 0)) or 0

            if verdict in _UNGRADEABLE:
                # No metrics. The whole point is that there is nothing to grade.
                lines.append(
                    f'  {shown}: {verdict} on {n} usable trades — NOT GRADED. '
                    f'State this as "no verdict"; do NOT report win rate, '
                    f'profit factor, drawdown or any performance number for '
                    f'{shown}, and do not carry one over from an older report.'
                )
            else:
                lines.append(
                    f"  {shown}: verdict={verdict} | "
                    f"Trades={n} | "
                    f"WR={_f(report.get('win_rate')):.1f}% | "
                    f"PF={_f(report.get('profit_factor')):.3f} | "
                    f"Sharpe={_f(report.get('sharpe')):.3f} | "
                    f"MaxDD={_f(report.get('max_drawdown_pct')):.1f}% | "
                    f"Expectancy=${_f(report.get('expectancy')):.2f}"
                )
            rec = report.get('recommendation', '')
            if rec:
                lines.append(f'    Validator says: {rec[:300]}')

        fresh = (data.get('_freshness') or {})
        stale = fresh.get('stale_labels') or []
        if stale:
            shown_stale = ', '.join(_VALIDATION_DISPLAY.get(s, s) for s in stale)
            lines.append(f'  ⚠ Feeds not current: {shown_stale}. '
                         f'No confident verdict may be issued on these.')

    lines.append(
        '  RULE: where a validator declined to grade (NO_DATA / STALE_DATA / '
        'INSUFFICIENT_DATA), report that as the finding. Describing the gap is '
        'correct; inventing or reusing a performance number is not.'
    )
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
        lines.append(f'Net Worth: {nw}')

    # Source breakdown — the number must be checkable, not just asserted.
    # Added 2026-07-30 after the figure drifted $36,578 -> $38,578 -> $41,578
    # across runs with nothing in the report to show where it came from.
    nwb = fs.get('net_worth_breakdown') or {}
    for s in nwb.get('sources', []):
        flag = ' ⚠️ STALE' if s.get('stale') else ''
        lines.append(f"    {s['label']}: ${s['value']:,.2f}{flag}")
    if nwb.get('missing'):
        lines.append(f"    ⚠️ not counted (no feed): {', '.join(nwb['missing'])}")
    if nwb.get('sources'):
        lines.append('    (paper accounts excluded — Alpaca, OANDA practice)')

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


# ══════════════════════════════════════════════════════════════════════════════
# TWO-TIER REPORTING (2026-07-27)
# ══════════════════════════════════════════════════════════════════════════════
# One generation, two renderings. Tier 1 is what reaches Jase's phone: the
# decision first, a handful of one-line headlines, every number carrying a
# plain-language tag, under a hard length cap. Tier 2 is the full analysis,
# sectioned and collapsible, written to a dashboard JSON.
#
# The builder lives in scripts/agent_report.py and is SHARED — Victoria, Lens
# and the Council all call the same module. Do not copy this logic into
# another agent; extend the shared module instead (same anti-drift principle
# as scripts/risk_validation.py).

TIER2_PATH = DASHBOARD / 'victoria_report_v2.json'
TIER2_WEEKLY_PATH = DASHBOARD / 'victoria_weekly_v2.json'


def build_two_tier(result: dict, lens_val: dict | None, vic_val: dict | None,
                   kind: str = 'daily') -> 'object':
    """Assemble the shared Report object from Victoria's payload.

    Structure here is deterministic — it holds up even when the model returns
    nothing, which is not hypothetical: the Codex subscription hit its usage
    limit on 2026-07-27 and synthesis came back empty.
    """
    from agent_report import Report, plain_verdict, label_for, explain

    today = result.get('date') or datetime.now(timezone.utc).strftime('%Y-%m-%d')
    r = Report(agent='victoria', kind=kind, date=today)

    recs   = result.get('recommendations') or []
    alerts = result.get('alerts') or []
    fin    = result.get('financial_summary') or {}
    ops    = result.get('operations_briefing') or ''
    agents = result.get('agent_status') or {}

    # ── Decision: lead with it ──────────────────────────────────────────────
    if recs:
        r.decide(*[str(x) for x in recs[:3]])
    elif alerts:
        r.decide(f'{len(alerts)} issue(s) need attention — see headlines.')
    else:
        r.decide('Nothing to action today. Hold everything.')

    # ── Headlines from the validators, with plain tags ──────────────────────
    ungradeable = {'NO_DATA', 'STALE_DATA', 'INSUFFICIENT_DATA', 'NO_BALANCE', 'UNKNOWN'}
    for val, src in ((lens_val, 'lens_validation'), (vic_val, 'victoria_validation')):
        if not val:
            continue
        for internal, ar in (val.get('agent_reports') or {}).items():
            shown = _VALIDATION_DISPLAY.get(internal, internal.capitalize())
            verdict = (ar.get('verdict') or 'UNKNOWN').upper()
            n = ar.get('total_trades', 0) or 0
            plain = plain_verdict(verdict)
            if verdict in ungradeable:
                r.headline(f'{shown}: no verdict — {plain}')
            else:
                r.headline(f'{shown}: {verdict} on {n} trades — {plain}')
                for term in ('profit_factor', 'sharpe'):
                    if ar.get(term) is not None:
                        r.metric(term, ar[term], subject=shown)
        for name, f in ((val.get('_freshness') or {}).get('detail') or {}).items():
            r.source(_VALIDATION_DISPLAY.get(name, name), f)

    # A money line is worth one headline slot.
    nw = fin.get('net_worth')
    if nw is not None:
        try:
            r.headline(f'Net worth ${float(nw):,.0f}')
        except (TypeError, ValueError):
            pass

    # ── Tier 2 sections ─────────────────────────────────────────────────────
    r.section('Decision', body='\n'.join(str(x) for x in recs) or 'No action required.',
              collapsed=False)

    holdings = [{'agent': a, 'status': str(s)} for a, s in agents.items()]
    if holdings:
        r.section('Holdings', rows=holdings)

    fixes = result.get('fix_prompts') or []
    if fixes:
        r.section('New Ideas',
                  rows=[{'severity': f.get('severity'), 'problem': f.get('problem'),
                         'fix': f.get('prompt', '')[:2000]} for f in fixes])

    if alerts:
        r.section('Risk Notes', rows=[{'alert': str(a)} for a in alerts])

    reasoning = ops
    if fin.get('summary'):
        reasoning = f"{fin['summary']}\n\n{reasoning}"
    r.section('Reasoning', body=reasoning)

    return r


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
    # --no-send regenerates a report without pushing it to Jase's phone.
    if '--no-send' in sys.argv:
        print(f'[victoria] --no-send: Telegram suppressed ({len(text)} chars)')
        return
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
    lens_val_data = _load_json(LENS_VALIDATION_PATH,     'lens_validation')
    vic_val_data  = _load_json(VICTORIA_VALIDATION_PATH, 'victoria_validation')

    for label, d in (('Lens', lens_val_data), ('Victoria', vic_val_data)):
        if d:
            print(f'[victoria] {label} validation loaded — dated {d.get("date","?")}')
        else:
            print(f'[victoria] {label} validation not available — no verdicts for its agents')

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
    norman_text = _format_validation(lens_val_data, vic_val_data)

    # Net worth is computed here and only QUOTED by the model — see
    # compute_net_worth() for why the model must not do this arithmetic.
    nw_computed = compute_net_worth(plaid_data, rb_data, kraken_data, tw_data, nw_data)
    nw_text     = _format_net_worth(nw_computed)
    print(f'[victoria] Net worth (deterministic): ${nw_computed["total"]:,.2f} '
          f'from {len(nw_computed["sources"])} source(s)'
          + (f'; MISSING {nw_computed["missing"]}' if nw_computed['missing'] else ''))

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
        f"{nw_text}\n\n"
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

    # ── 6b. Net worth: overwrite whatever the model produced ──
    # A prompt instruction is not a gate (Critical Rule #10). The prompt asks
    # the model to quote the computed total verbatim; this makes it so. Logged
    # when it disagrees, because a disagreement means the model tried to do the
    # arithmetic itself and is worth seeing in the run log.
    reported = result.get('financial_summary', {}).get('net_worth')
    if reported is not None and abs(_f(reported) - nw_computed['total']) > 0.01:
        print(f'[victoria] Net worth OVERRIDE: model said ${_f(reported):,.2f}, '
              f'deterministic sum is ${nw_computed["total"]:,.2f} — using the sum')
    result.setdefault('financial_summary', {})
    result['financial_summary']['net_worth']           = nw_computed['total']
    result['financial_summary']['net_worth_breakdown'] = nw_computed

    # ── 7. Save victoria_report.json ──
    result['_meta'] = {
        'input_tokens':     total_input,
        'output_tokens':    total_output,
        'cost_usd':         cost_usd,
        'model':            MODEL,
        'timestamp':        now_ts,
        'api_costs':        api_costs,
        'svc_statuses':     svc_statuses,
        'validation_sources': {
            'lens_validation':     {'available': lens_val_data is not None,
                                    'date': (lens_val_data or {}).get('date')},
            'victoria_validation': {'available': vic_val_data is not None,
                                    'date': (vic_val_data or {}).get('date')},
        },
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

    # ── 9. Two-tier output ──
    # Tier 1 (the glance) goes to Telegram; Tier 2 (the depth) goes to the
    # dashboard. Nothing is lost — the full prose that used to be pasted into
    # Telegram now lives in Tier 2's Reasoning section.
    try:
        report_obj = build_two_tier(result, lens_val_data, vic_val_data, kind='daily')
        tg_msg = report_obj.tier1()
        report_obj.write_tier2(TIER2_PATH)
        print(f'[victoria] Tier 2 written → {TIER2_PATH}')
    except Exception as e:
        # Never lose the report because the formatter failed.
        print(f'[victoria] two-tier build failed ({e}); falling back to long form')
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
    lens_val_data = _load_json(LENS_VALIDATION_PATH,     'lens_validation')
    vic_val_data  = _load_json(VICTORIA_VALIDATION_PATH, 'victoria_validation')

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
    norman_text = _format_validation(lens_val_data, vic_val_data)

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

    # Two-tier: the weekly tribunal follows the same rule as the daily —
    # decision to the phone, depth to the dashboard.
    try:
        report_obj = build_two_tier(result, lens_val_data, vic_val_data, kind='weekly')
        report_obj.write_tier2(TIER2_WEEKLY_PATH)
        print(f'[victoria] Tier 2 written → {TIER2_WEEKLY_PATH}')
        _send_telegram(report_obj.tier1())
    except Exception as e:
        print(f'[victoria] two-tier build failed ({e}); falling back to long form')
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
    parser.add_argument('--no-send', action='store_true',
                        help='Generate and save the report without sending to Telegram')
    parser.add_argument('--with-scout', action='store_true',
                        help='Weekly only: also run the scouting desk (absorbed from Lucy). '
                             'OFF by default — Victoria\'s weekly cron is live and the '
                             'scouting desk is held pending approval.')
    args = parser.parse_args()

    if args.weekly:
        run_victoria_weekly(with_scout=args.with_scout)
    else:
        run_victoria()
