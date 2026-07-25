#!/usr/bin/env python3
"""
norman_brain.py — Monte Carlo strategy validator for JCF HQ.

Norman validates trading strategies by running statistical analysis and
Monte Carlo simulation on historical trade data. Named after the strategist
from The Promised Neverland — cold, calculated, always 10 steps ahead.

Modes:
    python3 norman_brain.py --weekly          # Full weekly deep analysis
    python3 norman_brain.py --validate blade  # On-demand: single agent
    python3 norman_brain.py --validate edge
    python3 norman_brain.py --validate all    # On-demand: all agents
"""

import csv
import json
import math
import os
import subprocess
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
import sys
sys.path.insert(0, "/root/.openclaw/scripts")
from telegram_personalities import wrap_message
from pathlib import Path

import numpy as np
import requests

# ── Paths ──────────────────────────────────────────────────────────────────────

DASHBOARD   = Path('/root/.openclaw/dashboard')
LOGS        = Path('/root/.openclaw/logs')
AGENTS      = Path('/root/.openclaw/agents')

REPORT_PATH  = DASHBOARD / 'norman_report.json'
HISTORY_PATH = LOGS / 'norman_history.json'
COSTS_PATH   = LOGS / 'norman_api_costs.json'

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

# Internal id stays 'crisp' (matches strategist→JARVIS convention, CLAUDE.md
# Critical Rule #7); user-facing text uses the AGENT_DISPLAY alias -> "Chad".
CRISP_TRADES_PATH   = AGENTS / 'crisp' / 'data' / 'trade_history.json'
EDGE_PORTFOLIO_PATH = DASHBOARD / 'edge_portfolio.json'

# A trade file whose newest record is older than this is reported, not graded.
# Two weeks is generous for agents that trade on weekday sessions; it exists to
# catch dead feeds (months), not quiet weeks.
STALE_AFTER_DAYS = 14

# ── Config ─────────────────────────────────────────────────────────────────────

# Migrated 2026-07-24 off the Anthropic SDK to Codex via the openclaw gateway
# (Lucy's subprocess pattern). Tier: GPT-5.6 Terra (balanced everyday tier,
# cheaper than the Sol flagship — and Sol is NOT available on this Codex OAuth
# backend, it 400s). Was openai/gpt-5.5.
# NOTE: the override must be a plain tier id ('openai/gpt-5.6-terra') AND be
# whitelisted in `agents.defaults.models` (openclaw.json). The '-codex' suffixed
# ids are runtime-bound and rejected as --model overrides by `openclaw agent`.
MODEL      = 'openai/gpt-5.6-terra'
MAX_TOKENS = 4096


def _run_codex(system_prompt: str, user_message: str, timeout: int = 300) -> str | None:
    """Route a prompt through the openclaw gateway agent (Codex).

    Mirrors Lucy's `_run_agent` subprocess pattern. The gateway agent has no
    separate `system` slot, so the persona/system prompt is prepended into the
    message. The payload is passed via --message-file to avoid the ~128KB
    single CLI-arg limit. Returns response text, or None.
    """
    import tempfile
    combined = f"{system_prompt}\n\n=== TASK ===\n\n{user_message}"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            'w', suffix='.txt', prefix='norman_codex_',
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
            print(f'[norman] Codex call failed: {proc.stderr[:300]}')
            return None
        data = json.loads(proc.stdout)
        payloads = data.get('result', {}).get('payloads', [])
        return payloads[0].get('text', '') if payloads else None
    except subprocess.TimeoutExpired:
        print('[norman] Codex call timed out')
        return None
    except Exception as e:
        print(f'[norman] Codex call error: {e}')
        return None
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


TELEGRAM_TOKEN   = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_ALERT_CHAT_ID') or os.getenv('TELEGRAM_CHAT_ID')
TG_MAX           = 4000

# Norman's thresholds
sys.path.insert(0, '/root/.openclaw/scripts')
from agent_config import load_strategy as _load_strategy
from data_freshness import from_records, from_file, banner, summarize
from telegram_personalities import AGENT_DISPLAY


def _display(agent_key: str) -> str:
    """User-facing name for an internal agent id ('crisp' -> 'Chad')."""
    return AGENT_DISPLAY.get(agent_key, agent_key.capitalize())
_NORMAN_CFG = _load_strategy('norman', {
    'MIN_TRADES_FOR_VERDICT': 20,
    'RUIN_DRAWDOWN_PCT':      0.50,   # 50% drawdown = "ruin"
    'DOUBLE_TARGET_PCT':      1.00,   # 100% gain = "doubled"
})
MIN_TRADES_FOR_VERDICT = _NORMAN_CFG['MIN_TRADES_FOR_VERDICT']
RUIN_DRAWDOWN_PCT      = _NORMAN_CFG['RUIN_DRAWDOWN_PCT']
DOUBLE_TARGET_PCT      = _NORMAN_CFG['DOUBLE_TARGET_PCT']

SYSTEM_PROMPT = """\
You are Norman, the strategy validation specialist for JCF HQ. Named after \
the strategist from The Promised Neverland — cold, calculated, brutally honest.

You receive Monte Carlo simulation results and trade statistics for every \
trading agent in the system. Your job is to determine:

1. Which strategies have a genuine statistical edge
2. Which strategies are running on luck and will revert
3. What the portfolio-level risk looks like
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
  2. Initial backtest spans ≥5 years AND ≥2 distinct regimes.
  3. Parameter sensitivity: vary key knobs ±15–30%. PnL must stay positive across the sweep;
     a narrow peak (small adjustments crater performance) = OVERFIT — call it out.
  4. Execution friction: assume 1.5–2× the slippage and commissions the agent claims.
  5. Out-of-sample / walk-forward validation must replicate in-sample edge.
  6. Score five dimensions 0–100: Sample Size, Expectancy, Risk Management, Robustness,
     Execution Realism. A plateau of stable performance = real edge; a spike = mirage.
  Verdict: DEPLOY (survives all), REFINE (sound logic, needs tuning), ABANDON (fails stress
  tests or depends on fragile assumptions).

POSITION-SIZER LENS (apply when evaluating each agent's sizing):
  • Fixed Fractional: risk ≤ 1% per trade unless explicitly justified.
  • ATR-Based: stop distance scaled to volatility — preferred when volatility regime varies.
  • Kelly: use HALF KELLY, never full. Full Kelly is for unlimited bankrolls and zero ruin tolerance.
  • Portfolio heat: total open risk across all agents ≤ 6–8% — flag any combination above 6%.
  • If an agent's sizing exceeds these guardrails, flag it in the recommendation even if PnL
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
    }
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
# DATA LOADERS
# ══════════════════════════════════════════════════════════════════════════════

def _load_blade_trades() -> tuple[list[dict], object]:
    """Load Blade's OANDA closed trades from agent_trades.json (agent='blade').

    Returns (trades, freshness). Blade writes here via TRADES_JSON_PATH in
    blade_bot.py. If it holds no Blade records, that is reported as an absent
    source — NOT silently backfilled from the dormant TradeLocker feed, which
    is what produced two months of reports grading a dead broker account.
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
        print(f'[norman] blade load error: {e}')
        return [], from_file(BLADE_TRADES_PATH, STALE_AFTER_DAYS)


def _blade_legacy_note() -> str:
    """One-line description of the dormant TradeLocker feed, for the report.

    Named explicitly so the report can say WHY Blade has no data rather than
    leaving a bare zero the reader has to interpret.
    """
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
    is the authority, not the constant.

    It currently holds 0 with the note "Reset to clean slate 2026-07-17
    (Round 2). Jase sets a fresh starting number via edit mode." That is a
    deliberate placeholder, not a balance. Returning None here makes Norman
    say so instead of substituting the old hardcoded 10_000 notional, which
    was never connected to any real account.
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


def _load_crisp_trades() -> tuple[list[dict], object]:
    """Load Chad/crisp trades from trade_history.json (closed only).

    Returns (trades, freshness).
    """
    try:
        with open(CRISP_TRADES_PATH) as f:
            data = json.load(f)
        trades = data.get('trades', [])
        result = []
        for t in trades:
            if t.get('active', False):
                continue  # skip open positions
            pnl = t.get('pnl_usd')
            if pnl is None:
                continue
            ts = t.get('close_time') or t.get('open_time') or ''
            result.append({
                'pnl':        float(pnl),
                'direction':  t.get('direction', ''),
                'instrument': 'BTC/USD',
                'timestamp':  ts,
                'result':     t.get('result', 'W' if float(pnl) > 0 else 'L'),
            })
        return result, from_records(str(CRISP_TRADES_PATH), result, STALE_AFTER_DAYS)
    except Exception as e:
        print(f'[norman] crisp load error: {e}')
        return [], from_file(CRISP_TRADES_PATH, STALE_AFTER_DAYS)


def _load_edge_trades() -> list[dict]:
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
        # Attach aggregate totals for context (used in validation report)
        return result, {
            'total_trades': data.get('trades', 0),
            'win_rate_pct': data.get('win_rate', 0),
            'total_pnl':    data.get('total_pnl', 0),
            'balance':      data.get('balance', 0),
        }, from_file(EDGE_PORTFOLIO_PATH, STALE_AFTER_DAYS, ts_fields=('updated',))
    except Exception as e:
        print(f'[norman] edge load error: {e}')
        return [], {}, from_file(EDGE_PORTFOLIO_PATH, STALE_AFTER_DAYS)


# ══════════════════════════════════════════════════════════════════════════════
# STATISTICS ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def calculate_stats(trades: list[dict], strategy_name: str = '') -> dict:
    """
    Calculate comprehensive trading statistics from a list of trade dicts.
    Each trade must have a 'pnl' field (float).
    """
    pnls = [t['pnl'] for t in trades if t.get('pnl') is not None]
    n    = len(pnls)

    if n == 0:
        return {'n': 0, 'error': 'no trades with P&L data'}

    wins   = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    bes    = [p for p in pnls if p == 0]

    win_rate   = len(wins) / n * 100
    avg_win    = sum(wins)  / len(wins)  if wins   else 0.0
    avg_loss   = sum(losses)/ len(losses) if losses else 0.0   # negative value
    gross_win  = sum(wins)
    gross_loss = abs(sum(losses)) if losses else 0.0

    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (
        float('inf') if gross_win > 0 else 0.0
    )

    expectancy = (win_rate/100 * avg_win) + ((1 - win_rate/100) * avg_loss)

    total_pnl = sum(pnls)
    mean_pnl  = total_pnl / n
    std_pnl   = float(np.std(pnls, ddof=1)) if n > 1 else 0.0

    # Sharpe (per-trade, not annualised)
    sharpe = (mean_pnl / std_pnl) if std_pnl > 0 else 0.0

    # Sortino (downside deviation only)
    downside = [p for p in pnls if p < 0]
    downside_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else (
        abs(downside[0]) if downside else 0.0
    )
    sortino = (mean_pnl / downside_std) if downside_std > 0 else 0.0

    # Max drawdown (on cumulative equity curve)
    equity     = np.cumsum([0.0] + pnls)
    running_max = np.maximum.accumulate(equity)
    drawdowns   = equity - running_max
    max_dd_abs  = float(np.min(drawdowns))
    peak_before_dd = float(running_max[np.argmin(drawdowns)])
    max_dd_pct  = (max_dd_abs / peak_before_dd * 100) if peak_before_dd > 0 else 0.0

    # Max consecutive losses
    max_consec_loss = 0
    curr_streak     = 0
    for p in pnls:
        if p < 0:
            curr_streak += 1
            max_consec_loss = max(max_consec_loss, curr_streak)
        else:
            curr_streak = 0

    return {
        'n':                  n,
        'total_pnl':          round(total_pnl, 2),
        'win_rate':           round(win_rate, 1),
        'wins':               len(wins),
        'losses':             len(losses),
        'breakevens':         len(bes),
        'avg_win':            round(avg_win, 2),
        'avg_loss':           round(avg_loss, 2),
        'gross_win':          round(gross_win, 2),
        'gross_loss':         round(-gross_loss, 2),
        'profit_factor':      round(profit_factor, 3),
        'expectancy':         round(expectancy, 2),
        'mean_pnl':           round(mean_pnl, 2),
        'std_pnl':            round(std_pnl, 2),
        'sharpe':             round(sharpe, 3),
        'sortino':            round(sortino, 3),
        'max_drawdown_abs':   round(max_dd_abs, 2),
        'max_drawdown_pct':   round(abs(max_dd_pct), 1),
        'max_consec_losses':  max_consec_loss,
    }


# ══════════════════════════════════════════════════════════════════════════════
# MONTE CARLO ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def monte_carlo_simulation(
    trades_pnl: list[float],
    num_simulations: int = 10_000,
    starting_balance: float = 10_000,
) -> dict:
    """
    Bootstrap Monte Carlo simulation on trade P&L series.

    For each of num_simulations runs:
      1. Randomly resample len(trades_pnl) trades with replacement
      2. Build equity curve from starting_balance
      3. Track final equity and max drawdown

    Returns percentile outcomes and ruin/double probabilities.
    """
    if not trades_pnl:
        return {
            'median_final': 0.0, 'p5_final': 0.0, 'p95_final': 0.0,
            'median_max_drawdown': 0.0, 'ruin_probability': 0.0,
            'double_probability': 0.0, 'simulations': 0,
        }

    arr      = np.array(trades_pnl, dtype=np.float64)
    n_trades = len(arr)
    rng      = np.random.default_rng(seed=42)   # reproducible results

    # Vectorised: shape (num_simulations, n_trades)
    samples   = rng.choice(arr, size=(num_simulations, n_trades), replace=True)

    # Equity curves: shape (num_simulations, n_trades + 1)
    equity    = np.hstack([
        np.full((num_simulations, 1), starting_balance),
        starting_balance + np.cumsum(samples, axis=1),
    ])

    final_equity = equity[:, -1]

    # Max drawdown per simulation
    running_max = np.maximum.accumulate(equity, axis=1)
    drawdowns   = equity - running_max
    max_dd_per_sim = np.min(drawdowns, axis=1)   # most negative value per sim

    # Ruin: equity ever drops 50%+ below starting_balance
    ruin_threshold = starting_balance * (1 - RUIN_DRAWDOWN_PCT)
    ruin_sims      = np.any(equity <= ruin_threshold, axis=1)
    ruin_prob      = float(np.mean(ruin_sims) * 100)

    # Double: equity ever reaches 2× starting_balance
    double_threshold = starting_balance * (1 + DOUBLE_TARGET_PCT)
    double_sims      = np.any(equity >= double_threshold, axis=1)
    double_prob      = float(np.mean(double_sims) * 100)

    return {
        'median_final':        round(float(np.percentile(final_equity, 50)), 2),
        'p5_final':            round(float(np.percentile(final_equity,  5)), 2),
        'p95_final':           round(float(np.percentile(final_equity, 95)), 2),
        'mean_final':          round(float(np.mean(final_equity)), 2),
        'median_max_drawdown': round(float(np.percentile(max_dd_per_sim, 50)), 2),
        'ruin_probability':    round(ruin_prob, 2),
        'double_probability':  round(double_prob, 2),
        'simulations':         num_simulations,
        'starting_balance':    starting_balance,
    }


# ══════════════════════════════════════════════════════════════════════════════
# REGIME ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def regime_analysis(trades: list[dict]) -> dict:
    """
    Analyse performance by time-of-day, day-of-week, and detect recent divergence.
    """
    pnl_by_hour = defaultdict(list)
    pnl_by_dow  = defaultdict(list)   # 0=Mon, 6=Sun
    DOW_NAMES   = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

    timestamped = []
    for t in trades:
        ts_str = t.get('timestamp') or t.get('close_time') or t.get('exit_time') or ''
        pnl    = t.get('pnl')
        if not ts_str or pnl is None:
            continue
        try:
            dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            pnl_by_hour[dt.hour].append(pnl)
            pnl_by_dow[dt.weekday()].append(pnl)
            timestamped.append({'dt': dt, 'pnl': pnl})
        except Exception:
            continue

    # Best / worst hours
    hour_totals = {h: sum(v) for h, v in pnl_by_hour.items()}
    best_hour   = max(hour_totals, key=hour_totals.get) if hour_totals else None
    worst_hour  = min(hour_totals, key=hour_totals.get) if hour_totals else None

    # Best / worst day of week
    dow_totals   = {d: sum(v) for d, v in pnl_by_dow.items()}
    best_dow     = DOW_NAMES[max(dow_totals, key=dow_totals.get)] if dow_totals else None
    worst_dow    = DOW_NAMES[min(dow_totals, key=dow_totals.get)] if dow_totals else None

    # Recent divergence: last 10 trades vs overall
    all_pnls    = [t['pnl'] for t in trades if t.get('pnl') is not None]
    recent_pnls = all_pnls[-10:] if len(all_pnls) >= 10 else all_pnls

    overall_mean = float(np.mean(all_pnls))    if all_pnls    else 0.0
    overall_std  = float(np.std(all_pnls, ddof=1)) if len(all_pnls) > 1 else 1.0
    recent_mean  = float(np.mean(recent_pnls)) if recent_pnls else 0.0

    divergence_z = abs(recent_mean - overall_mean) / (overall_std if overall_std > 0 else 1)
    divergence_flag = divergence_z > 2.0

    return {
        'best_hour_utc':     best_hour,
        'worst_hour_utc':    worst_hour,
        'best_day_of_week':  best_dow,
        'worst_day_of_week': worst_dow,
        'overall_mean_pnl':  round(overall_mean, 2),
        'recent_mean_pnl':   round(recent_mean, 2),
        'divergence_z':      round(divergence_z, 2),
        'recent_divergence': divergence_flag,
    }


# ══════════════════════════════════════════════════════════════════════════════
# STRATEGY VALIDATOR
# ══════════════════════════════════════════════════════════════════════════════

def _determine_verdict(stats: dict, mc: dict) -> str:
    n = stats.get('n', 0)
    if n < MIN_TRADES_FOR_VERDICT:
        return 'INSUFFICIENT_DATA'

    pf    = stats.get('profit_factor', 0)
    sh    = stats.get('sharpe', 0)
    ruin  = mc.get('ruin_probability', 100)

    if ruin > 10 or sh < 0.5 or pf < 1.0:
        return 'FAIL'
    if pf >= 1.5 and sh >= 0.5 and ruin <= 5:
        return 'PASS'
    return 'MARGINAL'


def validate_strategy(
    trade_history: list[dict],
    strategy_name: str,
    starting_balance: float | None = None,
    extra_context: dict = None,
    freshness=None,
    balance_source: str = '',
) -> dict:
    """
    Run full statistical validation on a strategy's trade history.

    Args:
        trade_history:    List of trade dicts with 'pnl' field.
        strategy_name:    Human-readable name for the strategy.
        starting_balance: Real account size for Monte Carlo. None means the
                          balance is unknown — MC is skipped rather than run
                          against a made-up notional.
        extra_context:    Additional aggregate data (e.g. from edge_portfolio).
        freshness:        Freshness of the source. Stale sources are reported,
                          not graded.
        balance_source:   Where starting_balance came from (or why it's absent).

    Returns:
        Structured validation report dict. `verdict` is the DETERMINISTIC
        verdict — it is the ceiling the synthesis layer may not exceed.
    """
    print(f'[norman] Validating {strategy_name} — {len(trade_history)} trades')

    pnls = [t['pnl'] for t in trade_history if t.get('pnl') is not None]

    base = {
        'strategy':       strategy_name,
        'freshness':      freshness.to_dict() if freshness is not None else None,
        'balance_source': balance_source,
    }

    if not pnls:
        detail = 'No P&L data available'
        if freshness is not None and freshness.reason == 'empty':
            detail = f'Source contains no trades ({freshness.source})'
        elif freshness is not None and freshness.reason == 'missing':
            detail = f'Source file missing ({freshness.source})'
        return {**base, 'n': 0, 'verdict': 'NO_DATA', 'message': detail,
                'stats': {}, 'monte_carlo': {}, 'regime': {}}

    # A stale source is refused BEFORE any statistics are computed. Grading it
    # would produce real-looking numbers describing a period that has already
    # ended — which is exactly what happened for two months on the dormant
    # TradeLocker feed.
    if freshness is not None and freshness.stale and freshness.reason == 'stale':
        return {
            **base,
            'n': len(pnls),
            'verdict': 'STALE_DATA',
            'message': (f'Newest trade is {freshness.age_days:.0f} days old '
                        f'({freshness.as_of_str()}). Not graded — a verdict here '
                        f'would describe a period that has already ended.'),
            'stats': {}, 'monte_carlo': {}, 'regime': {},
        }

    # No known account size means no Monte Carlo. The previous behaviour
    # substituted a 10_000 notional that was never tied to any real account,
    # so ruin/double probabilities were computed against a fiction.
    if starting_balance is None or starting_balance <= 0:
        stats = calculate_stats(trade_history, strategy_name)
        return {
            **base,
            'n': len(pnls),
            'verdict': 'NO_BALANCE',
            'message': (f'Account balance unknown ({balance_source}). Trade stats '
                        f'computed, but Monte Carlo (ruin/double probability) '
                        f'requires a real balance and was skipped.'),
            'stats': stats, 'monte_carlo': {},
            'regime': regime_analysis(trade_history),
        }

    stats  = calculate_stats(trade_history, strategy_name)
    mc     = monte_carlo_simulation(pnls, starting_balance=starting_balance)
    regime = regime_analysis(trade_history)

    # Augment with aggregate context if provided
    if extra_context:
        stats['aggregate_total_trades'] = extra_context.get('total_trades')
        stats['aggregate_win_rate']     = extra_context.get('win_rate_pct')
        stats['aggregate_total_pnl']    = extra_context.get('total_pnl')

    verdict = _determine_verdict(stats, mc)

    mc_pnl_change  = mc.get('median_final', starting_balance) - starting_balance
    mc_pnl_pct     = mc_pnl_change / starting_balance * 100 if starting_balance > 0 else 0

    report = {
        **base,
        'n':             stats['n'],
        'verdict':       verdict,
        'stats':         stats,
        'monte_carlo':   mc,
        'regime':        regime,
        'mc_summary': {
            'median_pnl_change':  round(mc_pnl_change, 2),
            'median_pnl_pct':     round(mc_pnl_pct, 2),
            'worst_5pct_change':  round(mc.get('p5_final', 0) - starting_balance, 2),
            'best_95pct_change':  round(mc.get('p95_final', 0) - starting_balance, 2),
        },
    }

    print(
        f'[norman]  {strategy_name}: verdict={verdict}  '
        f'WR={stats["win_rate"]}%  PF={stats["profit_factor"]}  '
        f'Sharpe={stats["sharpe"]}  Ruin={mc.get("ruin_probability")}%  '
        f'MC_median=${mc.get("median_final")}'
    )

    return report


# ══════════════════════════════════════════════════════════════════════════════
# WEEKLY ANALYSIS — Claude API synthesis
# ══════════════════════════════════════════════════════════════════════════════

# Verdicts the deterministic layer owns outright. When one of these is set,
# the synthesis layer may describe the situation but may NOT substitute a
# graded verdict — it is overwritten in code after synthesis regardless of
# what the model returns. Belt and braces: the prompt asks, the merge enforces.
_LOCKED_VERDICTS = {'INSUFFICIENT_DATA', 'NO_DATA', 'STALE_DATA', 'NO_BALANCE'}


def _final_verdict(val: dict, synthesized: str | None) -> str:
    """Reconcile the deterministic verdict with whatever synthesis returned.

    The deterministic layer wins whenever it declined to grade. Previously this
    was `ar.get('verdict') or val.get('verdict')` — the model's answer first —
    which is how Edge received a substantive verdict off 0 trades while
    _determine_verdict had correctly refused to issue one.
    """
    deterministic = val.get('verdict', 'INSUFFICIENT_DATA')
    if deterministic in _LOCKED_VERDICTS:
        if synthesized and synthesized != deterministic:
            print(f'[norman]  ⚠️  synthesis returned "{synthesized}" for '
                  f'{val.get("strategy")} (n={val.get("n", 0)}); '
                  f'overriding with "{deterministic}" — sample gate.')
        return deterministic
    return synthesized or deterministic


def _build_analysis_prompt(agent_validations: dict, today: str) -> str:
    """Format all agent validation results as compact text for Claude."""
    lines = [
        f"WEEKLY STRATEGY REVIEW DATA — {today}",
        "",
        "VERDICT RULES (binding):",
        "  • Each agent below carries a DETERMINISTIC VERDICT computed from its",
        "    trade sample. You may not override it with a graded verdict.",
        f"  • Any agent marked LOCKED ({', '.join(sorted(_LOCKED_VERDICTS))}) must be",
        "    reported with that exact verdict string. Do NOT emit ABANDON, REFINE,",
        "    MARGINAL, PASS, or FAIL for a LOCKED agent — there is not enough",
        f"    evidence to grade it (minimum {MIN_TRADES_FOR_VERDICT} trades).",
        "  • Explain the gap and what would resolve it. Do not infer performance",
        "    from an insufficient, stale, or absent sample.",
        "",
    ]

    for agent, val in agent_validations.items():
        n       = val.get('n', 0)
        verdict = val.get('verdict', 'UNKNOWN')
        stats   = val.get('stats', {})
        mc      = val.get('monte_carlo', {})
        regime  = val.get('regime', {})

        lines.append(f"═══ {_display(agent).upper()} ══════════════════")
        lines.append(f"  Trades (with P&L): {n}  |  DETERMINISTIC VERDICT: {verdict}")

        if verdict in _LOCKED_VERDICTS:
            lines.append(
                f"  ⚠️ LOCKED: {val.get('message', '')} "
                f"You MUST report this agent's verdict as exactly "
                f"\"{verdict}\". Do not grade it."
            )
        for note in val.get('notes', []):
            lines.append(f"  NOTE: {note}")
        if val.get('balance_source'):
            lines.append(f"  Balance source: {val['balance_source']}")
        fr = val.get('freshness')
        if fr and not fr.get('ok'):
            lines.append(f"  DATA FRESHNESS: {fr.get('marker')}")

        if stats:
            lines.append(
                f"  WinRate: {stats.get('win_rate')}%  "
                f"ProfitFactor: {stats.get('profit_factor')}  "
                f"Sharpe: {stats.get('sharpe')}  "
                f"Sortino: {stats.get('sortino')}"
            )
            lines.append(
                f"  TotalPnL: ${stats.get('total_pnl')}  "
                f"AvgWin: ${stats.get('avg_win')}  "
                f"AvgLoss: ${stats.get('avg_loss')}  "
                f"Expectancy: ${stats.get('expectancy')}/trade"
            )
            lines.append(
                f"  MaxDD: {stats.get('max_drawdown_pct')}%  "
                f"MaxConsecLoss: {stats.get('max_consec_losses')}"
            )
            # Aggregate context if available
            if stats.get('aggregate_total_trades'):
                lines.append(
                    f"  [Aggregate] Total trades: {stats.get('aggregate_total_trades')}  "
                    f"Win rate: {stats.get('aggregate_win_rate')}%  "
                    f"Total PnL: ${stats.get('aggregate_total_pnl')}  "
                    f"(only recent trades have individual P&L data)"
                )

        if mc:
            lines.append(
                f"  MC(10K): median=${mc.get('median_final')}  "
                f"P5=${mc.get('p5_final')}  P95=${mc.get('p95_final')}  "
                f"Ruin={mc.get('ruin_probability')}%  "
                f"2x={mc.get('double_probability')}%"
            )

        if regime and regime.get('n', 1) != 0:
            lines.append(
                f"  Best hour: {regime.get('best_hour_utc')}:00 UTC  "
                f"Best day: {regime.get('best_day_of_week')}  "
                f"Recent divergence: {regime.get('recent_divergence')}"
                f" (z={regime.get('divergence_z')})"
            )

        lines.append("")

    lines.append(
        "Based on the above data, provide your analysis following the JSON format. "
        "Be brutally honest. Respond with ONLY the JSON object."
    )

    return '\n'.join(lines)


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
                candidate = text[json_start:i+1]
                try:
                    last_complete = json.loads(candidate)
                except json.JSONDecodeError:
                    pass
    return last_complete


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
    try:
        costs = json.loads(COSTS_PATH.read_text()) if COSTS_PATH.exists() else []
        costs.append(entry)
        COSTS_PATH.write_text(json.dumps(costs, indent=2))
    except Exception as e:
        print(f'[norman] cost log error: {e}')
    return cost_usd


def weekly_analysis() -> dict:
    """
    Full weekly deep analysis:
      1. Load all agent trade histories
      2. Run validate_strategy() on each (pure Python)
      3. Call Claude to synthesise strategic recommendations
      4. Save report and send Telegram
    """
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    print(f'\n[norman] ═══ WEEKLY ANALYSIS — {today} ═══')

    # ── Load and validate each agent ─────────────────────────────────────────
    blade_trades, blade_fresh = _load_blade_trades()
    crisp_trades, crisp_fresh = _load_crisp_trades()
    edge_trades, edge_context, edge_fresh = _load_edge_trades()

    sources = {
        'blade': blade_fresh,
        'crisp': crisp_fresh,
        'edge':  edge_fresh,
    }
    stale_labels = [k for k, v in sources.items() if v is not None and v.stale]
    if stale_labels:
        print(f'[norman] ⚠️  {len(stale_labels)}/{len(sources)} sources not current:')
        for k in sorted(stale_labels):
            print(f'[norman]     {_display(k)}: {sources[k].marker()}')

    print(f'[norman] Data loaded: {_display("blade")}={len(blade_trades)}, '
          f'{_display("crisp")}={len(crisp_trades)}, {_display("edge")}={len(edge_trades)}')

    # Blade balance comes from blade_balance.json — the file blade_bot.py
    # itself reads and writes. No hardcoded notional.
    blade_bal, blade_bal_src = _blade_starting_balance()

    blade_val = validate_strategy(
        blade_trades, _display('blade'), starting_balance=blade_bal,
        freshness=blade_fresh, balance_source=blade_bal_src,
    )
    if blade_legacy := _blade_legacy_note():
        blade_val.setdefault('notes', []).append(blade_legacy)

    crisp_val = validate_strategy(
        crisp_trades, _display('crisp'), starting_balance=10_000,
        freshness=crisp_fresh, balance_source='paper account notional (10,000)',
    )
    edge_val = validate_strategy(
        edge_trades, _display('edge'), starting_balance=5_000,
        extra_context=edge_context, freshness=edge_fresh,
        balance_source='edge_portfolio.json balance (5,000)',
    )

    agent_validations = {
        'blade':  blade_val,
        'crisp':  crisp_val,
        'edge':   edge_val,
    }

    # ── Claude synthesis ──────────────────────────────────────────────────────
    print('[norman] Calling Codex (via gateway) for strategic synthesis...')
    prompt = _build_analysis_prompt(agent_validations, today)

    # Codex has no separate system slot — persona is prepended into the message.
    result_text   = _run_codex(SYSTEM_PROMPT, prompt)
    input_tokens  = 0  # Codex free tier — no Anthropic token billing
    output_tokens = 0
    cost_usd      = _save_cost(input_tokens, output_tokens)

    print(f'[norman] Codex synthesis — {len(result_text or "")} chars | ${cost_usd:.4f}')

    claude_report = _extract_json(result_text) if result_text else None

    if claude_report is None:
        print(f'[norman] No JSON from Claude, snippet: {result_text[:300]}')
        claude_report = {
            'date': today,
            'agent_reports': {},
            'portfolio_summary': {'total_pnl': 0, 'correlation_risk': 'unknown',
                                  'overall_assessment': 'Report generation failed'},
            'recommendations': [],
            'alerts': ['Norman report generation failed — check norman.log'],
        }

    # ── Merge stats into report ───────────────────────────────────────────────
    # Ensure agent_reports has entries for all agents, augmented with our stats
    for agent_key, val in [
        ('blade', blade_val), ('crisp', crisp_val),
        ('edge', edge_val),
    ]:
        if agent_key not in claude_report.get('agent_reports', {}):
            claude_report.setdefault('agent_reports', {})[agent_key] = {}

        ar = claude_report['agent_reports'][agent_key]
        s  = val.get('stats', {})
        mc = val.get('monte_carlo', {})
        sb = val.get('monte_carlo', {}).get('starting_balance')

        ar.update({
            'total_trades':       val.get('n', 0),
            'win_rate':           s.get('win_rate', 0),
            'profit_factor':      s.get('profit_factor', 0),
            'sharpe':             s.get('sharpe', 0),
            'sortino':            s.get('sortino', 0),
            'max_drawdown_pct':   s.get('max_drawdown_pct', 0),
            'total_pnl':          s.get('total_pnl', 0),
            'expectancy':         s.get('expectancy', 0),
            'max_consec_losses':  s.get('max_consec_losses', 0),
            'monte_carlo': {
                'median_outcome':    mc.get('median_final', 0),
                'worst_case_5pct':   mc.get('p5_final', 0),
                'best_case_95pct':   mc.get('p95_final', 0),
                'ruin_probability':  mc.get('ruin_probability', 0),
                'double_probability': mc.get('double_probability', 0),
                'starting_balance':  sb,
            },
            'verdict': _final_verdict(val, ar.get('verdict')),
            'deterministic_verdict': val.get('verdict'),
            'balance_source': val.get('balance_source', ''),
            'freshness':      val.get('freshness'),
            'notes':          val.get('notes', []),
        })
        if val.get('message'):
            ar.setdefault('data_status', val['message'])

    # Attach regime analysis and meta
    claude_report['_regime'] = {
        'blade': blade_val.get('regime', {}),
        'crisp': crisp_val.get('regime', {}),
        'edge':  edge_val.get('regime', {}),
    }
    claude_report['_meta'] = {
        'input_tokens':  input_tokens,
        'output_tokens': output_tokens,
        'cost_usd':      cost_usd,
        'model':         MODEL,
        'generated_at':  datetime.now(timezone.utc).isoformat(),
    }
    claude_report['_freshness'] = summarize({k: v for k, v in sources.items() if v})

    # ── Save report ───────────────────────────────────────────────────────────
    _save_report(claude_report)

    # ── Send Telegram ─────────────────────────────────────────────────────────
    tg_text = _format_telegram(claude_report, agent_validations)
    _send_telegram(tg_text)

    print(f'[norman] Done. Cost: ${cost_usd:.4f}')
    return claude_report


# ══════════════════════════════════════════════════════════════════════════════
# TELEGRAM FORMATTING
# ══════════════════════════════════════════════════════════════════════════════

def _verdict_emoji(verdict: str) -> str:
    return {
        'PASS':              '✅',
        'FAIL':              '❌',
        'MARGINAL':          '⚠️',
        'INSUFFICIENT_DATA': '📊',
        'NO_DATA':           '🚫',
        'STALE_DATA':        '🕰️',
        'NO_BALANCE':        '💵',
    }.get(verdict, '❓')


def _format_telegram(report: dict, agent_validations: dict) -> str:
    today = report.get('date', datetime.now(timezone.utc).strftime('%Y-%m-%d'))
    lines = [f"WEEKLY STRATEGY REVIEW | {today}", ""]

    # Data-quality banner first. A reader must know which inputs are trustworthy
    # before reading a single verdict.
    fresh_meta = report.get('_freshness', {})
    if fresh_meta and not fresh_meta.get('all_fresh', True):
        lines.append("━━ ⚠️ DATA QUALITY ━━")
        for label, d in sorted(fresh_meta.get('detail', {}).items()):
            if not d.get('ok'):
                lines.append(f"  {_display(label)}: {d.get('marker')}")
        lines.append("")

    # ── Agent verdicts ────────────────────────────────────────────────────────
    lines.append("━━ AGENT VERDICTS ━━")
    ar_map = report.get('agent_reports', {})

    agent_display_order = ['blade', 'crisp', 'edge']
    for agent in agent_display_order:
        ar = ar_map.get(agent, {})
        verdict = ar.get('verdict', 'INSUFFICIENT_DATA')
        emoji   = _verdict_emoji(verdict)
        name    = _display(agent)
        n       = ar.get('total_trades', 0)
        wr      = ar.get('win_rate', 0)
        pf      = ar.get('profit_factor', 0)
        sh      = ar.get('sharpe', 0)
        ruin    = ar.get('monte_carlo', {}).get('ruin_probability', 0)

        if verdict in _LOCKED_VERDICTS:
            # Ungraded: say why, in place of numbers that would imply a grade.
            reason = ar.get('data_status') or ar.get('note') or f'{n} trades'
            lines.append(f"  {name}: {emoji} {verdict}")
            lines.append(f"      {reason}")
            for note in ar.get('notes', []):
                lines.append(f"      {note}")
        elif verdict == 'FAIL':
            lines.append(
                f"  {name}: {emoji} FAIL — "
                f"{wr:.0f}% WR, PF {pf:.2f}, ruin {ruin:.1f}%"
            )
        elif verdict == 'PASS':
            lines.append(
                f"  {name}: {emoji} PASS — "
                f"{wr:.0f}% WR, PF {pf:.2f}, Sharpe {sh:.2f}"
            )
        else:  # MARGINAL / ABANDON / REFINE / other synthesis verdicts
            lines.append(
                f"  {name}: {emoji} {verdict} — "
                f"{wr:.0f}% WR, PF {pf:.2f}, {n} trades"
            )
    lines.append("")

    # ── Best MC results (pick the agent with most trades and a real verdict) ───
    # Only agents that were actually graded AND have a real starting balance
    # qualify. A Monte Carlo needs a genuine account size; the old code
    # defaulted to 10_000 here, which is how a fictional notional reached the
    # report even for agents whose balance was never known.
    best_agent = None
    best_n     = 0
    for agent in agent_display_order:
        ar = ar_map.get(agent, {})
        if ar.get('verdict') in _LOCKED_VERDICTS:
            continue
        if not ar.get('monte_carlo', {}).get('starting_balance'):
            continue
        if ar.get('total_trades', 0) > best_n:
            best_n     = ar.get('total_trades', 0)
            best_agent = agent

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

        lines.append(f"━━ MONTE CARLO ({_display(best_agent)}, 10K sims) ━━")
        lines.append(f"  Starting: ${sb:,.0f}")
        lines.append(f"  Median:   {_fmt_delta(med, sb)}")
        lines.append(f"  Worst 5%: {_fmt_delta(p5, sb)}")
        lines.append(f"  Best 95%: {_fmt_delta(p95, sb)}")
        lines.append(f"  Ruin prob: {mc.get('ruin_probability', 0):.1f}%  |  "
                     f"2x prob: {mc.get('double_probability', 0):.1f}%")
        lines.append("")

    # ── Claude recommendations ────────────────────────────────────────────────
    recs = report.get('recommendations', [])
    if recs:
        lines.append("━━ RECOMMENDATIONS ━━")
        for r in recs[:5]:
            lines.append(f"  • {r}")
        lines.append("")

    # ── Alerts ────────────────────────────────────────────────────────────────
    alerts = report.get('alerts', [])
    if alerts:
        lines.append("━━ ALERTS ━━")
        for a in alerts[:3]:
            lines.append(f"  ⚡ {a}")
        lines.append("")

    # ── Portfolio summary ─────────────────────────────────────────────────────
    ps = report.get('portfolio_summary', {})
    lines.append("━━ PORTFOLIO RISK ━━")
    lines.append(f"  Correlation: {ps.get('correlation_risk', '?').upper()}")
    lines.append(f"  Overall: {ps.get('overall_assessment', '?')[:120]}")

    lines.append('')
    lines.append('This week\'s results are attached. You will not enjoy reading them. Read them anyway.')
    lines.append('')
    lines.append('\u2014 Norman')

    body = '\n'.join(lines)
    return wrap_message('norman', body)


def _tg_send_chunk(text: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print('[norman] Telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)')
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
        print(f'[norman] Telegram send error: {e}')
        return False


def _send_telegram(text: str) -> None:
    if len(text) <= TG_MAX:
        if _tg_send_chunk(text):
            print('[norman] Telegram report sent')
        return
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
        print(f'[norman] Telegram chunk {i}/{len(chunks)} {"sent" if ok else "FAILED"}')
        if not ok:
            break


# ══════════════════════════════════════════════════════════════════════════════
# FILE I/O
# ══════════════════════════════════════════════════════════════════════════════

def _save_report(report: dict) -> None:
    try:
        DASHBOARD.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, indent=2, default=str))
        print(f'[norman] Report saved → {REPORT_PATH}')
    except Exception as e:
        print(f'[norman] Report save error: {e}')

    # Append to history
    try:
        history = json.loads(HISTORY_PATH.read_text()) if HISTORY_PATH.exists() else []
        if not isinstance(history, list):
            history = []
        history.append(report)
        HISTORY_PATH.write_text(json.dumps(history, indent=2, default=str))
        print(f'[norman] History appended → {HISTORY_PATH}')
    except Exception as e:
        print(f'[norman] History save error: {e}')


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def _run_validate_mode(target: str) -> None:
    """On-demand validation of one or all agents. No Claude call."""
    AGENT_MAP = {
        'blade':  lambda: (_load_blade_trades(), 10_000, {}),
        'crisp':  lambda: (_load_crisp_trades(), 10_000, {}),
        'edge':   lambda: (lambda r: (r[0], 5_000, r[1]))(_load_edge_trades()),
    }

    targets = list(AGENT_MAP.keys()) if target == 'all' else [target.lower()]

    for name in targets:
        if name not in AGENT_MAP:
            print(f'[norman] Unknown agent: {name}. Choose: {list(AGENT_MAP.keys())} or all')
            continue
        trades, balance, ctx = AGENT_MAP[name]()
        result = validate_strategy(trades, name.capitalize(),
                                   starting_balance=balance, extra_context=ctx or None)
        print(json.dumps(result, indent=2, default=str))


def main() -> None:
    args = sys.argv[1:]

    if '--weekly' in args:
        report = weekly_analysis()
        print('\n[norman] ═══ REPORT SUMMARY ═══')
        for agent, ar in report.get('agent_reports', {}).items():
            v = ar.get('verdict', '?')
            print(f"  {agent}: {_verdict_emoji(v)} {v}")
        meta = report.get('_meta', {})
        print(f"\n  API cost: ${meta.get('cost_usd', 0):.4f}")
        print(f"  Report: {REPORT_PATH}")

    elif '--validate' in args:
        idx = args.index('--validate')
        target = args[idx + 1] if idx + 1 < len(args) else 'all'
        _run_validate_mode(target)

    else:
        print('Usage:')
        print('  python3 norman_brain.py --weekly')
        print('  python3 norman_brain.py --validate blade')
        print('  python3 norman_brain.py --validate edge')
        print('  python3 norman_brain.py --validate all')


if __name__ == '__main__':
    main()
