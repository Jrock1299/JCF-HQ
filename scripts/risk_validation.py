#!/usr/bin/env python3
"""
risk_validation.py — Norman's validation pipeline, extracted for reuse.

Norman was retired 2026-07-25 and his risk-validation duty was split:
  • Lens     validates Blade and Edge   (agents/lens/lens_validator.py)
  • Victoria validates Jerry and Chad   (agents/victoria/victoria_validator.py)

Both copies import THIS module. That is a deliberate deviation from a
literal copy-paste duplication: the sample-size gate is a safety rail, and
two hand-copied rails drift. One implementation, imported twice, is the
strongest available guarantee that the gate is identical in both places —
and it is tested independently in each (see each validator's --test-gate).

Everything below is ported verbatim from agents/norman/norman_brain.py as it
stood post-fix on 2026-07-25 (commit 5bd3b5a "Kill silent data fallbacks").
Behaviour is unchanged:

  • calculate_stats()        — WR / PF / Sharpe / Sortino / max DD / streaks
  • monte_carlo_simulation() — 10K bootstrap, seed=42, ruin + double probs
  • regime_analysis()        — hour / day-of-week / recent-divergence
  • _determine_verdict()     — the DETERMINISTIC sample-size gate
  • validate_strategy()      — NO_DATA / STALE_DATA / NO_BALANCE refusals
  • final_verdict()          — deterministic layer outranks LLM synthesis

CLAUDE.md Critical Rule #9 (never substitute a stale or invented value) and
Rule #10 (a deterministic gate outranks an LLM's narrative) both live here.
"""

import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, '/root/.openclaw/scripts')
from agent_config import load_strategy as _load_strategy
from data_freshness import from_records, from_file, summarize   # noqa: F401  (re-exported)
from telegram_personalities import AGENT_DISPLAY

# ── Config ─────────────────────────────────────────────────────────────────────
# Read from the SAME dashboard/agent_strategies.json 'norman' block Norman used,
# so the knobs stay on one tunable surface and both validators see one value.
_CFG = _load_strategy('norman', {
    'MIN_TRADES_FOR_VERDICT': 20,
    'RUIN_DRAWDOWN_PCT':      0.50,   # 50% drawdown = "ruin"
    'DOUBLE_TARGET_PCT':      1.00,   # 100% gain = "doubled"
})
MIN_TRADES_FOR_VERDICT = _CFG['MIN_TRADES_FOR_VERDICT']
RUIN_DRAWDOWN_PCT      = _CFG['RUIN_DRAWDOWN_PCT']
DOUBLE_TARGET_PCT      = _CFG['DOUBLE_TARGET_PCT']

# A trade file whose newest record is older than this is reported, not graded.
STALE_AFTER_DAYS = 14

# Verdicts the deterministic layer owns outright. When one of these is set, the
# synthesis layer may DESCRIBE the situation but may NOT substitute a graded
# verdict — it is overwritten in code after synthesis regardless of what the
# model returns. Belt and braces: the prompt asks, the merge enforces.
LOCKED_VERDICTS = {'INSUFFICIENT_DATA', 'NO_DATA', 'STALE_DATA', 'NO_BALANCE'}


def display(agent_key: str) -> str:
    """User-facing name for an internal agent id ('crisp' -> 'Chad')."""
    return AGENT_DISPLAY.get(agent_key, agent_key.capitalize())


# ══════════════════════════════════════════════════════════════════════════════
# STATISTICS ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def calculate_stats(trades: list[dict], strategy_name: str = '',
                    starting_balance: float | None = None) -> dict:
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

    # Max drawdown, measured against ACCOUNT EQUITY.
    #
    # This used to anchor the equity curve at 0.0 — i.e. cumulative P&L, not
    # equity — and then divide the drawdown by the peak of that curve. The
    # denominator was therefore "peak cumulative profit", which early in a
    # track record is a tiny number. That is what produced Chad's 468.0% max
    # drawdown (an impossible figure for a percentage that is bounded by 100)
    # and Jerry's 107.8%. Both were relayed to Jase as real risk findings.
    #
    # Anchoring at the real starting balance bounds the ratio correctly: you
    # cannot draw down more than the peak equity you reached.
    equity_base = float(starting_balance) if (starting_balance or 0) > 0 else None
    equity      = np.cumsum([0.0] + pnls) + (equity_base or 0.0)
    running_max = np.maximum.accumulate(equity)
    drawdowns   = equity - running_max
    max_dd_abs  = float(np.min(drawdowns))
    peak_before_dd = float(running_max[np.argmin(drawdowns)])

    account_wiped = False
    if equity_base is None:
        # Without a real account size a drawdown PERCENTAGE is not defined.
        # Report the dollar figure and say so, rather than emitting a ratio
        # against peak cumulative profit that reads like a percentage but is
        # not one (Rule #9 — never substitute a fabricated value).
        max_dd_pct   = None
        max_dd_basis = 'undefined_no_starting_balance'
    else:
        max_dd_pct   = (max_dd_abs / peak_before_dd * 100) if peak_before_dd > 0 else 0.0
        max_dd_basis = 'account_equity'
        # A drawdown cannot exceed the peak equity that preceded it: past 100%
        # the account is gone and the remaining losses could not have been
        # taken. Arithmetic beyond 100 means the modelled curve went negative,
        # so report ruin rather than an impossible percentage.
        if abs(max_dd_pct) > 100.0:
            max_dd_pct    = 100.0
            account_wiped = True
            max_dd_basis  = 'account_equity_capped_at_ruin'

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
        'max_drawdown_pct':   (round(abs(max_dd_pct), 1) if max_dd_pct is not None else None),
        'max_drawdown_basis': max_dd_basis,
        'account_wiped':      account_wiped,
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

    # Double: equity ever reaches 2x starting_balance
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
# THE SAMPLE-SIZE GATE
# ══════════════════════════════════════════════════════════════════════════════

def determine_verdict(stats: dict, mc: dict) -> str:
    """The DETERMINISTIC verdict. Sample size is checked FIRST and unconditionally.

    Below MIN_TRADES_FOR_VERDICT there is no grade — not a lenient one, not a
    harsh one. No amount of profit factor or Sharpe can buy a verdict off a
    sample too small to mean anything.
    """
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


def final_verdict(val: dict, synthesized: str | None, log_prefix: str = 'validator') -> str:
    """Reconcile the deterministic verdict with whatever synthesis returned.

    The deterministic layer wins whenever it declined to grade. The bug fixed
    on 2026-07-25 was `ar.get('verdict') or val.get('verdict')` — the model's
    answer first — which is how Edge received a substantive verdict off 0
    trades while determine_verdict had correctly refused to issue one.
    """
    deterministic = val.get('verdict', 'INSUFFICIENT_DATA')
    if deterministic in LOCKED_VERDICTS:
        if synthesized and synthesized != deterministic:
            print(f'[{log_prefix}]  ⚠️  synthesis returned "{synthesized}" for '
                  f'{val.get("strategy")} (n={val.get("n", 0)}); '
                  f'overriding with "{deterministic}" — sample gate.')
        return deterministic
    return synthesized or deterministic


# ══════════════════════════════════════════════════════════════════════════════
# STRATEGY VALIDATOR
# ══════════════════════════════════════════════════════════════════════════════

def validate_strategy(
    trade_history: list[dict],
    strategy_name: str,
    starting_balance: float | None = None,
    extra_context: dict = None,
    freshness=None,
    balance_source: str = '',
    log_prefix: str = 'validator',
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
    print(f'[{log_prefix}] Validating {strategy_name} — {len(trade_history)} trades')

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

    # An all-zero P&L column is an UNPOPULATED FIELD, not a break-even record.
    # Added 2026-07-25 when Jerry was brought under validation: all 90 of his
    # closed trades carry pnl=0.0 because the field is never written on close.
    # Without this guard the sample is large enough to clear the gate and grades
    # FAIL (0% WR, PF 0.0, Sharpe 0) — a real-looking verdict on a feed that
    # reported nothing. CLAUDE.md Rule #9: an empty success is not a verified
    # zero. Requires n>=5 so a genuinely flat small sample is not misread.
    if len(pnls) >= 5 and all(p == 0 for p in pnls):
        return {
            **base,
            'n': len(pnls),
            'verdict': 'NO_DATA',
            'message': (f'All {len(pnls)} trades report P&L of exactly 0.00. That is an '
                        f'unpopulated field, not a break-even record — the source is not '
                        f'writing realised P&L on close. Not graded: a verdict here would '
                        f'describe a feed that reported nothing.'),
            'stats': {}, 'monte_carlo': {}, 'regime': {},
        }

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
        stats = calculate_stats(trade_history, strategy_name, starting_balance)
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

    stats  = calculate_stats(trade_history, strategy_name, starting_balance)
    mc     = monte_carlo_simulation(pnls, starting_balance=starting_balance)
    regime = regime_analysis(trade_history)

    # Augment with aggregate context if provided
    if extra_context:
        stats['aggregate_total_trades'] = extra_context.get('total_trades')
        stats['aggregate_win_rate']     = extra_context.get('win_rate_pct')
        stats['aggregate_total_pnl']    = extra_context.get('total_pnl')

    verdict = determine_verdict(stats, mc)

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
        f'[{log_prefix}]  {strategy_name}: verdict={verdict}  '
        f'WR={stats["win_rate"]}%  PF={stats["profit_factor"]}  '
        f'Sharpe={stats["sharpe"]}  Ruin={mc.get("ruin_probability")}%  '
        f'MC_median=${mc.get("median_final")}'
    )

    return report


# ══════════════════════════════════════════════════════════════════════════════
# SYNTHESIS SUPPORT
# ══════════════════════════════════════════════════════════════════════════════

def build_verdict_rules_header(today: str) -> list[str]:
    """The binding verdict-rules preamble Norman put at the top of every prompt."""
    return [
        f"WEEKLY STRATEGY REVIEW DATA — {today}",
        "",
        "VERDICT RULES (binding):",
        "  • Each agent below carries a DETERMINISTIC VERDICT computed from its",
        "    trade sample. You may not override it with a graded verdict.",
        f"  • Any agent marked LOCKED ({', '.join(sorted(LOCKED_VERDICTS))}) must be",
        "    reported with that exact verdict string. Do NOT emit ABANDON, REFINE,",
        "    MARGINAL, PASS, or FAIL for a LOCKED agent — there is not enough",
        f"    evidence to grade it (minimum {MIN_TRADES_FOR_VERDICT} trades).",
        "  • Explain the gap and what would resolve it. Do not infer performance",
        "    from an insufficient, stale, or absent sample.",
        "",
    ]


def format_agent_block(agent: str, val: dict) -> list[str]:
    """Render one agent's validation data for the synthesis prompt."""
    lines    = []
    n        = val.get('n', 0)
    verdict  = val.get('verdict', 'UNKNOWN')
    stats    = val.get('stats', {})
    mc       = val.get('monte_carlo', {})
    regime   = val.get('regime', {})

    lines.append(f"═══ {display(agent).upper()} ══════════════════")
    lines.append(f"  Trades (with P&L): {n}  |  DETERMINISTIC VERDICT: {verdict}")

    if verdict in LOCKED_VERDICTS:
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
    return lines


def merge_validation_into_report(report: dict, validations: dict,
                                 log_prefix: str = 'validator') -> dict:
    """Overwrite the synthesis layer's numbers and verdicts with our own.

    This is where Rule #10 is ENFORCED (not merely requested in the prompt):
    every agent's verdict is passed through final_verdict(), so a LOCKED
    deterministic verdict survives no matter what the model returned.
    """
    for agent_key, val in validations.items():
        if agent_key not in report.get('agent_reports', {}):
            report.setdefault('agent_reports', {})[agent_key] = {}

        ar = report['agent_reports'][agent_key]
        s  = val.get('stats', {})
        mc = val.get('monte_carlo', {})
        sb = mc.get('starting_balance')

        ar.update({
            'total_trades':       val.get('n', 0),
            'win_rate':           s.get('win_rate', 0),
            'profit_factor':      s.get('profit_factor', 0),
            'sharpe':             s.get('sharpe', 0),
            'sortino':            s.get('sortino', 0),
            'max_drawdown_pct':   s.get('max_drawdown_pct', 0),
            # Carry the drawdown's provenance, so a reader can tell a real
            # percentage from one that is undefined or capped at ruin.
            'max_drawdown_abs':   s.get('max_drawdown_abs'),
            'max_drawdown_basis': s.get('max_drawdown_basis'),
            'account_wiped':      s.get('account_wiped', False),
            'total_pnl':          s.get('total_pnl', 0),
            'expectancy':         s.get('expectancy', 0),
            'max_consec_losses':  s.get('max_consec_losses', 0),
            'monte_carlo': {
                'median_outcome':     mc.get('median_final', 0),
                'worst_case_5pct':    mc.get('p5_final', 0),
                'best_case_95pct':    mc.get('p95_final', 0),
                'ruin_probability':   mc.get('ruin_probability', 0),
                'double_probability': mc.get('double_probability', 0),
                'starting_balance':   sb,
            },
            'verdict': final_verdict(val, ar.get('verdict'), log_prefix),
            'deterministic_verdict': val.get('verdict'),
            'balance_source': val.get('balance_source', ''),
            'freshness':      val.get('freshness'),
            'notes':          val.get('notes', []),
        })
        if val.get('message'):
            ar.setdefault('data_status', val['message'])

    return report


def extract_json(text: str) -> dict | None:
    """Parse JSON from an LLM response: raw, fenced, or embedded in prose."""
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


def verdict_emoji(verdict: str) -> str:
    return {
        'PASS':              '✅',
        'FAIL':              '❌',
        'MARGINAL':          '⚠️',
        'INSUFFICIENT_DATA': '📊',
        'NO_DATA':           '🚫',
        'STALE_DATA':        '🕰️',
        'NO_BALANCE':        '💵',
    }.get(verdict, '❓')


# ══════════════════════════════════════════════════════════════════════════════
# GATE SELF-TEST — the rogue-synthesis test, runnable from either validator
# ══════════════════════════════════════════════════════════════════════════════

def run_gate_test(log_prefix: str) -> bool:
    """Feed the merge layer a rogue synthesis response and prove the gate holds.

    This is the same test applied to norman_brain.py on 2026-07-25. It must
    pass identically in both Lens's and Victoria's validator.
    """
    print(f'\n[{log_prefix}] ═══ SAMPLE-SIZE GATE TEST ═══')
    print(f'[{log_prefix}] MIN_TRADES_FOR_VERDICT = {MIN_TRADES_FOR_VERDICT}')
    passed = True

    # ── Case 1: under-sample → INSUFFICIENT_DATA, rogue "PASS" must not stick ──
    few = [{'pnl': 12.0, 'timestamp': '2026-07-20T10:00:00+00:00'} for _ in range(5)]
    val = validate_strategy(few, 'GateTest-UnderSample', starting_balance=5_000,
                            log_prefix=log_prefix)
    assert_det = val['verdict']
    rogue = {'agent_reports': {'gatetest': {
        'verdict': 'PASS',
        'recommendation': 'Ship it live immediately, the edge is obvious.',
    }}}
    merged = merge_validation_into_report(rogue, {'gatetest': val}, log_prefix)
    got = merged['agent_reports']['gatetest']['verdict']
    ok = (assert_det == 'INSUFFICIENT_DATA' and got == 'INSUFFICIENT_DATA')
    passed &= ok
    print(f'[{log_prefix}]  [1] n=5, synthesis said PASS  → deterministic={assert_det}, '
          f'final={got}  {"✅ HELD" if ok else "❌ BREACHED"}')

    # ── Case 2: no data → NO_DATA, rogue "FAIL" must not stick ────────────────
    val2 = validate_strategy([], 'GateTest-NoData', starting_balance=5_000,
                             log_prefix=log_prefix)
    rogue2 = {'agent_reports': {'gatetest': {'verdict': 'FAIL'}}}
    merged2 = merge_validation_into_report(rogue2, {'gatetest': val2}, log_prefix)
    got2 = merged2['agent_reports']['gatetest']['verdict']
    ok2 = (val2['verdict'] == 'NO_DATA' and got2 == 'NO_DATA')
    passed &= ok2
    print(f'[{log_prefix}]  [2] n=0, synthesis said FAIL  → deterministic={val2["verdict"]}, '
          f'final={got2}  {"✅ HELD" if ok2 else "❌ BREACHED"}')

    # ── Case 3: no balance → NO_BALANCE, rogue "MARGINAL" must not stick ──────
    many = [{'pnl': (7.0 if i % 2 else -3.0),
             'timestamp': '2026-07-20T10:00:00+00:00'} for i in range(40)]
    val3 = validate_strategy(many, 'GateTest-NoBalance', starting_balance=None,
                             balance_source='balance file holds 0 (placeholder)',
                             log_prefix=log_prefix)
    rogue3 = {'agent_reports': {'gatetest': {'verdict': 'MARGINAL'}}}
    merged3 = merge_validation_into_report(rogue3, {'gatetest': val3}, log_prefix)
    got3 = merged3['agent_reports']['gatetest']['verdict']
    ok3 = (val3['verdict'] == 'NO_BALANCE' and got3 == 'NO_BALANCE')
    passed &= ok3
    print(f'[{log_prefix}]  [3] balance unknown, synthesis said MARGINAL → '
          f'deterministic={val3["verdict"]}, final={got3}  '
          f'{"✅ HELD" if ok3 else "❌ BREACHED"}')

    # ── Case 4: sufficient sample → synthesis IS allowed to refine ────────────
    val4 = validate_strategy(many, 'GateTest-Graded', starting_balance=5_000,
                             log_prefix=log_prefix)
    rogue4 = {'agent_reports': {'gatetest': {'verdict': 'REFINE'}}}
    merged4 = merge_validation_into_report(rogue4, {'gatetest': val4}, log_prefix)
    got4 = merged4['agent_reports']['gatetest']['verdict']
    ok4 = (val4['verdict'] not in LOCKED_VERDICTS and got4 == 'REFINE')
    passed &= ok4
    print(f'[{log_prefix}]  [4] n=40 graded ({val4["verdict"]}), synthesis said REFINE → '
          f'final={got4}  {"✅ synthesis allowed" if ok4 else "❌ wrongly blocked"}')

    print(f'[{log_prefix}] ═══ GATE TEST {"PASSED" if passed else "FAILED"} ═══\n')
    return passed


if __name__ == '__main__':
    ok = run_gate_test('risk_validation')
    sys.exit(0 if ok else 1)
