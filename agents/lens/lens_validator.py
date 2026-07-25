#!/usr/bin/env python3
"""
lens_validator.py — Risk validation for BLADE and EDGE. (Absorbed from Norman.)

Norman was retired 2026-07-25 and his validation duty was split by agent:
    Lens     → Blade, Edge      (this file)
    Victoria → Jerry, Chad      (agents/victoria/victoria_validator.py)

The full pipeline — Monte Carlo simulation, the sample-size gate, and verdict
synthesis — lives in scripts/risk_validation.py and is imported by both copies.

⚠️  WHY IMPORTED, NOT COPY-PASTED
    The brief called for duplicating Norman's pipeline into both agents. The
    pipeline IS duplicated in the sense that matters — each validator owns its
    own roster, loaders, synthesis, report and delivery. But the sample-size
    gate itself is a safety rail, and two hand-copied rails drift: the next
    person to fix a bug in one has no way to know the other exists. A single
    implementation imported twice is the strongest available guarantee that
    the gate is byte-identical in both places. It is still tested independently
    from each side — run `--test-gate` here and in victoria_validator.py.

The gate, preserved exactly as fixed on 2026-07-25:
    • determine_verdict() checks n < MIN_TRADES_FOR_VERDICT FIRST, and returns
      INSUFFICIENT_DATA before any PF/Sharpe/ruin logic runs.
    • final_verdict() overrides the LLM's answer whenever the deterministic
      layer declined to grade. The bug fixed that night was the reverse
      precedence — `ar.get('verdict') or val.get('verdict')` — which let Edge
      receive a substantive verdict off 0 trades.

Modes:
    python3 lens_validator.py --weekly         # full weekly analysis + synthesis
    python3 lens_validator.py --validate blade # on-demand, no LLM call
    python3 lens_validator.py --validate edge
    python3 lens_validator.py --validate all
    python3 lens_validator.py --test-gate      # rogue-synthesis gate test
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, '/root/.openclaw/scripts')
from telegram_personalities import wrap_message
from risk_validation import (
    LOCKED_VERDICTS, MIN_TRADES_FOR_VERDICT, STALE_AFTER_DAYS,
    build_verdict_rules_header, display, extract_json, format_agent_block,
    from_file, from_records, merge_validation_into_report, run_gate_test,
    summarize, validate_strategy, verdict_emoji,
)

LOG = 'lens-val'

# ── Paths ──────────────────────────────────────────────────────────────────────

DASHBOARD = Path('/root/.openclaw/dashboard')
LOGS      = Path('/root/.openclaw/logs')

REPORT_PATH  = DASHBOARD / 'lens_validation.json'
HISTORY_PATH = LOGS / 'lens_validation_history.json'
COSTS_PATH   = LOGS / 'lens_validation_api_costs.json'

# ── Trade sources ─────────────────────────────────────────────────────────────
# Blade migrated to OANDA (blade_bot.py -> profiles['oanda:default']) and now
# writes closed positions to agent_trades.json, tagged agent='blade'.
#
# tradelocker_trades.json is the PRE-MIGRATION broker feed. Its newest trade
# closed 2026-05-27; the */30 sync keeps refreshing `last_sync` so the file
# looks live, but no new trades have arrived in two months. Norman graded it
# as "Blade" for that entire period — 330 dormant trades from a broker Blade
# no longer uses. It is retained below ONLY so the report can name it when
# explaining why Blade has no gradeable data. It is never graded.
BLADE_TRADES_PATH   = DASHBOARD / 'agent_trades.json'
BLADE_LEGACY_PATH   = DASHBOARD / 'tradelocker_trades.json'
BLADE_BALANCE_PATH  = DASHBOARD / 'blade_balance.json'
EDGE_PORTFOLIO_PATH = DASHBOARD / 'edge_portfolio.json'

# ── Model routing (same as Norman's, unchanged) ───────────────────────────────
MODEL      = 'openai/gpt-5.6-terra'
MAX_TOKENS = 4096

TELEGRAM_TOKEN   = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_ALERT_CHAT_ID') or os.getenv('TELEGRAM_CHAT_ID')
TG_MAX           = 4000


def _run_codex(system_prompt: str, user_message: str, timeout: int = 300) -> str | None:
    """Route a prompt through the openclaw gateway agent (Codex).

    The gateway agent has no separate `system` slot, so the persona/system
    prompt is prepended into the message. The payload is passed via
    --message-file to avoid the ~128KB single CLI-arg limit.
    """
    import tempfile
    combined = f"{system_prompt}\n\n=== TASK ===\n\n{user_message}"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            'w', suffix='.txt', prefix='lens_val_',
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
            print(f'[{LOG}] Codex call failed: {proc.stderr[:300]}')
            return None
        data = json.loads(proc.stdout)
        payloads = data.get('result', {}).get('payloads', [])
        return payloads[0].get('text', '') if payloads else None
    except subprocess.TimeoutExpired:
        print(f'[{LOG}] Codex call timed out')
        return None
    except Exception as e:
        print(f'[{LOG}] Codex call error: {e}')
        return None
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


# ── System prompt (Norman's methodology, Lens's voice) ────────────────────────

SYSTEM_PROMPT = """\
You are Lens, running the risk-validation desk for JCF HQ. You inherited this \
duty from Norman on 2026-07-25 and you hold his standard: cold, calculated, \
brutally honest about what the data does and does not support.

You cover TWO agents: BLADE (15m ORB on indices) and EDGE (1H SMA crossover \
on SPX500). You receive Monte Carlo simulation results and trade statistics \
for each. Your job is to determine:

1. Which strategies have a genuine statistical edge
2. Which strategies are running on luck and will revert
3. What the risk looks like across the two of them together
4. What should change next week

Be ruthless with the data. A 60% win rate over 10 trades means nothing — \
that's noise. A 55% win rate over 200 trades with positive expectancy is \
a real edge.

FRAMEWORK:
- Minimum 20 trades before any conclusion
- Probability of ruin > 10% = FAIL
- Sharpe < 0.5 = FAIL
- Profit factor < 1.2 = MARGINAL
- Profit factor > 1.5 = STRONG
- If recent 10 trades diverge >2 std from overall = FLAG

BACKTEST-EXPERT METHODOLOGY (apply silently to every agent under review):
A strategy passes only when it survives all six phases:
  1. Hypothesis stated and rule-codified.
  2. Initial backtest spans >=5 years AND >=2 distinct regimes.
  3. Parameter sensitivity: vary key knobs +/-15-30%. PnL must stay positive across the sweep;
     a narrow peak (small adjustments crater performance) = OVERFIT — call it out.
  4. Execution friction: assume 1.5-2x the slippage and commissions the agent claims.
  5. Out-of-sample / walk-forward validation must replicate in-sample edge.
  6. Score five dimensions 0-100: Sample Size, Expectancy, Risk Management, Robustness,
     Execution Realism. A plateau of stable performance = real edge; a spike = mirage.
  Verdict: DEPLOY (survives all), REFINE (sound logic, needs tuning), ABANDON (fails stress
  tests or depends on fragile assumptions).

POSITION-SIZER LENS (apply when evaluating each agent's sizing):
  - Fixed Fractional: risk <= 1% per trade unless explicitly justified.
  - ATR-Based: stop distance scaled to volatility — preferred when volatility regime varies.
  - Kelly: use HALF KELLY, never full. Full Kelly is for unlimited bankrolls and zero ruin tolerance.
  - Portfolio heat: total open risk across all agents <= 6-8% — flag any combination above 6%.
  - If an agent's sizing exceeds these guardrails, flag it in the recommendation even if PnL
    looks fine — survivorship bias is the silent killer.

OUTPUT FORMAT (valid JSON only, no markdown):
{
  "date": "YYYY-MM-DD",
  "agent_reports": {
    "blade": {
      "total_trades": 0,
      "win_rate": 0.0,
      "profit_factor": 0.0,
      "sharpe": 0.0,
      "max_drawdown_pct": 0.0,
      "monte_carlo": {
        "median_outcome": 0.0,
        "worst_case_5pct": 0.0,
        "best_case_95pct": 0.0,
        "ruin_probability": 0.0
      },
      "verdict": "PASS",
      "recommendation": "string"
    },
    "edge": { }
  },
  "portfolio_summary": {
    "total_pnl": 0.0,
    "correlation_risk": "low",
    "overall_assessment": "string"
  },
  "recommendations": ["string"],
  "alerts": ["string"]
}"""


# ══════════════════════════════════════════════════════════════════════════════
# DATA LOADERS  (ported from norman_brain.py — Blade + Edge only)
# ══════════════════════════════════════════════════════════════════════════════

def _load_blade_trades() -> tuple[list[dict], object]:
    """Load Blade's OANDA closed trades from agent_trades.json (agent='blade').

    If it holds no Blade records, that is reported as an absent source — NOT
    silently backfilled from the dormant TradeLocker feed, which is what
    produced two months of reports grading a dead broker account.
    """
    try:
        with open(BLADE_TRADES_PATH) as f:
            data = json.load(f)
        rows = [
            t for t in data.get('trades', [])
            if str(t.get('agent', '')).lower() == 'blade'
            and t.get('direction', 'none') != 'none'
        ]
        result = []
        for t in rows:
            pnl = t.get('pnl', t.get('pnl_usd'))
            if pnl is None:
                continue
            result.append({
                'pnl':        float(pnl),
                'direction':  t.get('direction', ''),
                'instrument': t.get('symbol', ''),
                'timestamp':  t.get('timestamp') or t.get('date') or '',
                'result':     t.get('result') or
                              ('W' if float(pnl) > 0 else ('L' if float(pnl) < 0 else 'BE')),
            })
        return result, from_records(str(BLADE_TRADES_PATH), result, STALE_AFTER_DAYS)
    except Exception as e:
        print(f'[{LOG}] blade load error: {e}')
        return [], from_file(BLADE_TRADES_PATH, STALE_AFTER_DAYS)


def _blade_legacy_note() -> str:
    """One-line description of the dormant TradeLocker feed, for the report."""
    try:
        with open(BLADE_LEGACY_PATH) as f:
            data = json.load(f)
        trades = data.get('trades', [])
        fr = from_records(str(BLADE_LEGACY_PATH), trades, STALE_AFTER_DAYS)
        return (f"{len(trades)} trades exist in the pre-migration TradeLocker feed "
                f"({BLADE_LEGACY_PATH.name}), newest {fr.as_of_str()} — not graded: "
                f"Blade trades OANDA now.")
    except Exception:
        return ""


def _blade_starting_balance() -> tuple[float | None, str]:
    """Authoritative Blade balance, or (None, reason) when it is not set.

    blade_bot.py's _load_paper_balance() reads blade_balance.json and treats
    STARTING_BALANCE_DEFAULT purely as a missing-file fallback — so this file
    is the authority, not the constant. Returning None makes the validator say
    so instead of substituting a notional never tied to any real account.
    """
    try:
        with open(BLADE_BALANCE_PATH) as f:
            d = json.load(f)
        bal = float(d.get('balance', 0) or 0)
        if bal > 0:
            return bal, f"{BLADE_BALANCE_PATH.name}"
        note = d.get('note', '').strip()
        return None, (f"{BLADE_BALANCE_PATH.name} balance={bal:g}"
                      + (f" — {note}" if note else ""))
    except Exception as e:
        return None, f"{BLADE_BALANCE_PATH.name} unreadable ({e})"


def _load_edge_trades():
    """Load Edge trades from edge_portfolio.json (recent only — full history not stored)."""
    try:
        with open(EDGE_PORTFOLIO_PATH) as f:
            data = json.load(f)
        recent = data.get('recent', [])
        result = []
        for t in recent:
            pnl = t.get('pnl')
            if pnl is None:
                continue
            ts = t.get('exit_time') or t.get('entry_time') or ''
            result.append({
                'pnl':        float(pnl),
                'direction':  t.get('direction', ''),
                'instrument': 'SPX500 (US100)',
                'timestamp':  ts,
                'result':     t.get('result', 'W' if float(pnl) > 0 else 'L'),
                'session':    t.get('session', ''),
                'hold_mins':  t.get('hold_minutes', 0),
            })
        return result, {
            'total_trades': data.get('trades', 0),
            'win_rate_pct': data.get('win_rate', 0),
            'total_pnl':    data.get('total_pnl', 0),
            'balance':      data.get('balance', 0),
        }, from_file(EDGE_PORTFOLIO_PATH, STALE_AFTER_DAYS, ts_fields=('updated',))
    except Exception as e:
        print(f'[{LOG}] edge load error: {e}')
        return [], {}, from_file(EDGE_PORTFOLIO_PATH, STALE_AFTER_DAYS)


# ══════════════════════════════════════════════════════════════════════════════
# WEEKLY ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

AGENTS_COVERED = ['blade', 'edge']


def _save_cost(input_tokens: int, output_tokens: int) -> float:
    cost_usd = round(
        (input_tokens * 3 / 1_000_000) + (output_tokens * 15 / 1_000_000), 6,
    )
    entry = {
        'date':          datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'timestamp':     datetime.now(timezone.utc).isoformat(),
        'input_tokens':  input_tokens,
        'output_tokens': output_tokens,
        'cost_usd':      cost_usd,
    }
    try:
        costs = json.loads(COSTS_PATH.read_text()) if COSTS_PATH.exists() else []
        costs.append(entry)
        COSTS_PATH.write_text(json.dumps(costs, indent=2))
    except Exception as e:
        print(f'[{LOG}] cost log error: {e}')
    return cost_usd


def collect_validations() -> tuple[dict, dict]:
    """Load and validate Blade + Edge. Returns (validations, freshness_sources)."""
    blade_trades, blade_fresh = _load_blade_trades()
    edge_trades, edge_context, edge_fresh = _load_edge_trades()

    sources = {'blade': blade_fresh, 'edge': edge_fresh}
    stale_labels = [k for k, v in sources.items() if v is not None and v.stale]
    if stale_labels:
        print(f'[{LOG}] ⚠️  {len(stale_labels)}/{len(sources)} sources not current:')
        for k in sorted(stale_labels):
            print(f'[{LOG}]     {display(k)}: {sources[k].marker()}')

    print(f'[{LOG}] Data loaded: {display("blade")}={len(blade_trades)}, '
          f'{display("edge")}={len(edge_trades)}')

    blade_bal, blade_bal_src = _blade_starting_balance()

    blade_val = validate_strategy(
        blade_trades, display('blade'), starting_balance=blade_bal,
        freshness=blade_fresh, balance_source=blade_bal_src, log_prefix=LOG,
    )
    if blade_legacy := _blade_legacy_note():
        blade_val.setdefault('notes', []).append(blade_legacy)

    edge_val = validate_strategy(
        edge_trades, display('edge'), starting_balance=5_000,
        extra_context=edge_context, freshness=edge_fresh,
        balance_source='edge_portfolio.json balance (5,000)', log_prefix=LOG,
    )

    return {'blade': blade_val, 'edge': edge_val}, sources


def weekly_analysis() -> dict:
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    print(f'\n[{LOG}] ═══ WEEKLY VALIDATION (Blade, Edge) — {today} ═══')

    agent_validations, sources = collect_validations()

    # ── Synthesis ─────────────────────────────────────────────────────────────
    print(f'[{LOG}] Calling Codex (via gateway) for strategic synthesis...')
    lines = build_verdict_rules_header(today)
    for agent, val in agent_validations.items():
        lines.extend(format_agent_block(agent, val))
    lines.append(
        "Based on the above data, provide your analysis following the JSON format. "
        "Be brutally honest. Respond with ONLY the JSON object."
    )
    prompt = '\n'.join(lines)

    result_text = _run_codex(SYSTEM_PROMPT, prompt)
    cost_usd = _save_cost(0, 0)   # Codex free tier — no Anthropic token billing
    print(f'[{LOG}] Codex synthesis — {len(result_text or "")} chars | ${cost_usd:.4f}')

    report = extract_json(result_text) if result_text else None
    if report is None:
        print(f'[{LOG}] No JSON from synthesis, snippet: {(result_text or "")[:300]}')
        report = {
            'date': today,
            'agent_reports': {},
            'portfolio_summary': {'total_pnl': 0, 'correlation_risk': 'unknown',
                                  'overall_assessment': 'Report generation failed'},
            'recommendations': [],
            'alerts': ['Lens validation report generation failed — check lens_validation.log'],
        }

    # ── THE GATE IS ENFORCED HERE, after the model has spoken ────────────────
    report = merge_validation_into_report(report, agent_validations, LOG)

    report['date'] = report.get('date') or today
    report['_regime'] = {k: v.get('regime', {}) for k, v in agent_validations.items()}
    report['_meta'] = {
        'input_tokens': 0, 'output_tokens': 0, 'cost_usd': cost_usd,
        'model': MODEL,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'validator': 'lens', 'covers': AGENTS_COVERED,
        'absorbed_from': 'norman (retired 2026-07-25)',
        'min_trades_for_verdict': MIN_TRADES_FOR_VERDICT,
    }
    report['_freshness'] = summarize({k: v for k, v in sources.items() if v})

    _save_report(report)
    _send_telegram(_format_telegram(report))

    print(f'[{LOG}] Done. Cost: ${cost_usd:.4f}')
    return report


# ══════════════════════════════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════════════════════════════

def _format_telegram(report: dict) -> str:
    today = report.get('date', datetime.now(timezone.utc).strftime('%Y-%m-%d'))
    lines = [f"RISK VALIDATION — BLADE & EDGE | {today}", ""]

    fresh_meta = report.get('_freshness', {})
    if fresh_meta and not fresh_meta.get('all_fresh', True):
        lines.append("━━ ⚠️ DATA QUALITY ━━")
        for label, d in sorted(fresh_meta.get('detail', {}).items()):
            if not d.get('ok'):
                lines.append(f"  {display(label)}: {d.get('marker')}")
        lines.append("")

    lines.append("━━ AGENT VERDICTS ━━")
    ar_map = report.get('agent_reports', {})

    for agent in AGENTS_COVERED:
        ar      = ar_map.get(agent, {})
        verdict = ar.get('verdict', 'INSUFFICIENT_DATA')
        emoji   = verdict_emoji(verdict)
        name    = display(agent)
        n       = ar.get('total_trades', 0)
        wr      = ar.get('win_rate', 0)
        pf      = ar.get('profit_factor', 0)
        sh      = ar.get('sharpe', 0)
        ruin    = ar.get('monte_carlo', {}).get('ruin_probability', 0)

        if verdict in LOCKED_VERDICTS:
            reason = ar.get('data_status') or ar.get('note') or f'{n} trades'
            lines.append(f"  {name}: {emoji} {verdict}")
            lines.append(f"      {reason}")
            for note in ar.get('notes', []):
                lines.append(f"      {note}")
        elif verdict == 'FAIL':
            lines.append(f"  {name}: {emoji} FAIL — {wr:.0f}% WR, PF {pf:.2f}, ruin {ruin:.1f}%")
        elif verdict == 'PASS':
            lines.append(f"  {name}: {emoji} PASS — {wr:.0f}% WR, PF {pf:.2f}, Sharpe {sh:.2f}")
        else:
            lines.append(f"  {name}: {emoji} {verdict} — {wr:.0f}% WR, PF {pf:.2f}, {n} trades")
    lines.append("")

    # Monte Carlo — only for a graded agent with a REAL balance.
    best_agent, best_n = None, 0
    for agent in AGENTS_COVERED:
        ar = ar_map.get(agent, {})
        if ar.get('verdict') in LOCKED_VERDICTS:
            continue
        if not ar.get('monte_carlo', {}).get('starting_balance'):
            continue
        if ar.get('total_trades', 0) > best_n:
            best_n, best_agent = ar.get('total_trades', 0), agent

    if best_agent:
        ar  = ar_map[best_agent]
        mc  = ar.get('monte_carlo', {})
        sb  = mc.get('starting_balance')
        med = mc.get('median_outcome', 0) - sb
        p5  = mc.get('worst_case_5pct', 0) - sb
        p95 = mc.get('best_case_95pct', 0) - sb

        def _fmt_delta(v, base):
            sign = '+' if v >= 0 else ''
            pct  = v / base * 100 if base > 0 else 0
            return f"{sign}${v:.0f} ({sign}{pct:.1f}%)"

        lines.append(f"━━ MONTE CARLO ({display(best_agent)}, 10K sims) ━━")
        lines.append(f"  Starting: ${sb:,.0f}")
        lines.append(f"  Median:   {_fmt_delta(med, sb)}")
        lines.append(f"  Worst 5%: {_fmt_delta(p5, sb)}")
        lines.append(f"  Best 95%: {_fmt_delta(p95, sb)}")
        lines.append(f"  Ruin prob: {mc.get('ruin_probability', 0):.1f}%  |  "
                     f"2x prob: {mc.get('double_probability', 0):.1f}%")
        lines.append("")

    if recs := report.get('recommendations', []):
        lines.append("━━ RECOMMENDATIONS ━━")
        for r in recs[:5]:
            lines.append(f"  • {r}")
        lines.append("")

    if alerts := report.get('alerts', []):
        lines.append("━━ ALERTS ━━")
        for a in alerts[:3]:
            lines.append(f"  ⚡ {a}")
        lines.append("")

    ps = report.get('portfolio_summary', {})
    lines.append("━━ RISK ━━")
    lines.append(f"  Correlation: {ps.get('correlation_risk', '?').upper()}")
    lines.append(f"  Overall: {str(ps.get('overall_assessment', '?'))[:120]}")
    lines.append('')
    lines.append('— Lens')

    return wrap_message('lens', '\n'.join(lines))


def _tg_send_chunk(text: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f'[{LOG}] Telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)')
        return False
    try:
        resp = requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={'chat_id': TELEGRAM_CHAT_ID, 'text': text},
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f'[{LOG}] Telegram send error: {e}')
        return False


def _send_telegram(text: str) -> None:
    if len(text) <= TG_MAX:
        if _tg_send_chunk(text):
            print(f'[{LOG}] Telegram report sent')
        return
    chunks, current = [], ''
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
        print(f'[{LOG}] Telegram chunk {i}/{len(chunks)} {"sent" if ok else "FAILED"}')
        if not ok:
            break


# ══════════════════════════════════════════════════════════════════════════════
# FILE I/O
# ══════════════════════════════════════════════════════════════════════════════

def _save_report(report: dict) -> None:
    try:
        DASHBOARD.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, indent=2, default=str))
        print(f'[{LOG}] Report saved → {REPORT_PATH}')
    except Exception as e:
        print(f'[{LOG}] Report save error: {e}')
    try:
        history = json.loads(HISTORY_PATH.read_text()) if HISTORY_PATH.exists() else []
        if not isinstance(history, list):
            history = []
        history.append(report)
        HISTORY_PATH.write_text(json.dumps(history, indent=2, default=str))
        print(f'[{LOG}] History appended → {HISTORY_PATH}')
    except Exception as e:
        print(f'[{LOG}] History save error: {e}')


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def _run_validate_mode(target: str) -> None:
    """On-demand validation of one or all covered agents. No LLM call.

    Note: Norman's equivalent had a latent bug here — AGENT_MAP passed the
    (trades, freshness) TUPLE through as `trades`, and hardcoded a 10_000
    notional for Blade that _blade_starting_balance() exists to prevent. Both
    are fixed below; the weekly path was always correct.
    """
    validations, _ = collect_validations()
    targets = AGENTS_COVERED if target == 'all' else [target.lower()]
    for name in targets:
        if name not in validations:
            print(f'[{LOG}] Unknown agent: {name}. Choose: {AGENTS_COVERED} or all')
            continue
        print(json.dumps(validations[name], indent=2, default=str))


def main() -> None:
    args = sys.argv[1:]

    if '--test-gate' in args:
        ok = run_gate_test(LOG)
        sys.exit(0 if ok else 1)

    elif '--weekly' in args:
        report = weekly_analysis()
        print(f'\n[{LOG}] ═══ REPORT SUMMARY ═══')
        for agent, ar in report.get('agent_reports', {}).items():
            v = ar.get('verdict', '?')
            print(f"  {agent}: {verdict_emoji(v)} {v}")
        print(f"\n  Report: {REPORT_PATH}")

    elif '--validate' in args:
        idx = args.index('--validate')
        target = args[idx + 1] if idx + 1 < len(args) else 'all'
        _run_validate_mode(target)

    else:
        print('Usage:')
        print('  python3 lens_validator.py --weekly')
        print('  python3 lens_validator.py --validate blade|edge|all')
        print('  python3 lens_validator.py --test-gate')


if __name__ == '__main__':
    main()
