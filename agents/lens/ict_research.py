#!/usr/bin/env python3
"""ict_research.py — run every codified ICT/ICC model across every instrument,
grade each through the SHARED gate, rank, and write validated winners to the
strategy library.

Verdicts come from scripts/risk_validation.py — the same gate Lens and Victoria
use on live agents. A backtest does not get a friendlier standard than a
running bot, and nothing is graded on a free-text impression.

    python3 ict_research.py --run          # full matrix, writes results
    python3 ict_research.py --report       # print the ranked shortlist
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, '/root/.openclaw/scripts')
sys.path.insert(0, str(Path(__file__).parent))

from ict_backtest import run as bt_run, load_bars, STARTING_BALANCE  # noqa: E402
from ict_strategies import STRATEGIES, PARAMS                        # noqa: E402
from risk_validation import calculate_stats, monte_carlo_simulation   # noqa: E402

RESULTS_PATH = Path('/root/.openclaw/dashboard/ict_research.json')
LIBRARY_PATH = Path('/root/.openclaw/dashboard/strategy_library.json')

# Fixed-dollar risk per trade for MC ruin. RISK_PCT (0.75%) of the $10k
# starting balance = $75 per trade — the same risk_amt every trade, always.
# Passing THIS series to monte_carlo_simulation resolves the compounding
# artefact that produced 68-74% ruin figures against $10k starts while the
# backtest itself grew to $7-53M peak equity (2026-07-28 fix).
FIXED_RISK_PER_TRADE = STARTING_BALANCE * PARAMS['RISK_PCT']


def _augment_stats(stats: dict, trades: list) -> dict:
    """Add ICT-specific fields the shared calculate_stats does not know about.

    - expectancy_R:      mean R-multiple per trade (position-size-invariant)
    - fixed_size_pnl:    total $ at FIXED_RISK_PER_TRADE per trade
    - trades_per_year:   real trades-per-year from the timestamp span
                         (matches the shared stats' annualisation_factor)

    These make the report meaningful independently of the compounding balance:
    two rows with wildly different total_pnl but identical R distributions read
    as the same edge under expectancy_R + fixed_size_pnl.
    """
    if not trades:
        return stats
    rms = [t.get('r_multiple', 0) or 0 for t in trades]
    n = len(rms)
    stats['expectancy_R'] = round(sum(rms) / n, 4) if n else 0.0
    stats['fixed_size_pnl'] = round(sum(rms) * FIXED_RISK_PER_TRADE, 2)
    stats['trades_per_year'] = float(stats.get('annualisation_factor') or 252.0)
    return stats

# Blade's book per Jase's brief. NOTE: the brief lists XAU as Blade's third
# instrument while CLAUDE.md §2 lists CHF_JPY. Both are tested and the
# discrepancy is reported rather than silently resolved.
BLADE_INSTRUMENTS = ['SPX500_USD', 'DE30_EUR', 'XAU_USD', 'CHF_JPY']
EDGE_INSTRUMENTS = ['SPX500_USD']          # Edge trades SPX500 only
ALL_INSTRUMENTS = BLADE_INSTRUMENTS

MIN_TRADES_FOR_VERDICT = 100               # the brief's bar, stricter than the
                                           # validator's own 20


def _regime_split(trades: list, bars: list) -> dict:
    """Split trades by calendar year — a crude but honest regime proxy.

    The brief requires multi-regime evidence. Calendar years across 2018-2026
    span trending, chopping, high-vol and low-vol conditions; a model that only
    works in one year is not validated, it is fitted.
    """
    by_year: dict = {}
    for t in trades:
        y = t.entry_time[:4]
        by_year.setdefault(y, []).append(t.pnl)
    return {y: {'n': len(v), 'pnl': round(sum(v), 2),
                'wr': round(100 * sum(1 for x in v if x > 0) / len(v), 1)}
            for y, v in sorted(by_year.items())}


def _verdict(stats: dict, mc: dict, n: int, regimes: dict) -> tuple[str, str]:
    """Gated verdict. NO free-text grade below the trade floor.

    Sharpe basis, 2026-07-27: ANNUALISED, not per-trade. Per-trade Sharpe
    structurally penalises high-frequency models and is not the industry
    basis for comparing strategies of different frequencies. Every other
    gate criterion (trade floor, PF, MaxDD, multi-regime, ruin) is unchanged.
    """
    if n == 0:
        return 'NO_DATA', 'No trades generated.'
    if n < MIN_TRADES_FOR_VERDICT:
        return ('INSUFFICIENT_DATA',
                f'{n} trades — below the {MIN_TRADES_FOR_VERDICT}-trade floor. '
                f'Not graded. Any performance figure here is descriptive only.')

    pf = stats.get('profit_factor', 0) or 0
    # Annualised Sharpe is the deployment gate. Per-trade Sharpe is retained
    # in the record for continuity but is no longer graded on.
    sharpe_ann = stats.get('sharpe_annualised', 0) or 0
    sharpe_pt = stats.get('sharpe', 0) or 0
    dd = stats.get('max_drawdown_pct') or 0
    ruin = mc.get('ruin_probability', 0) or 0
    profitable_years = sum(1 for r in regimes.values() if r['pnl'] > 0)
    total_years = len(regimes)

    if ruin > 10:
        return 'FAIL', f'Ruin probability {ruin:.1f}% exceeds the 10% ceiling.'
    if sharpe_ann < 0.5:
        return 'FAIL', (f'Annualised Sharpe {sharpe_ann:.3f} below 0.5 — no '
                        f'risk-adjusted edge (per-trade {sharpe_pt:.3f}).')
    if pf < 1.2:
        return 'MARGINAL', f'Profit factor {pf:.3f} below 1.2.'
    if total_years >= 3 and profitable_years < max(2, total_years // 2):
        return ('MARGINAL',
                f'Profitable in only {profitable_years}/{total_years} years — '
                f'edge is regime-dependent, not validated across conditions.')
    if pf >= 1.5 and sharpe_ann >= 0.5 and dd is not None and dd < 25:
        return 'PASS', (f'PF {pf:.3f}, ann. Sharpe {sharpe_ann:.3f}, '
                        f'max DD {dd:.1f}%, profitable in '
                        f'{profitable_years}/{total_years} years.')
    return 'MARGINAL', (f'PF {pf:.3f}, ann. Sharpe {sharpe_ann:.3f} — '
                        f'positive but not strong.')


def run_matrix(instruments=None) -> dict:
    instruments = instruments or ALL_INSTRUMENTS
    out = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'starting_balance': STARTING_BALANCE,
        'min_trades_for_verdict': MIN_TRADES_FOR_VERDICT,
        'params': PARAMS,
        'results': [],
    }

    for inst in instruments:
        bars = load_bars(inst, 'M15')
        h4 = load_bars(inst, 'H4')
        if not bars or not h4:
            print(f'  {inst}: NO DATA — skipped')
            continue
        print(f'\n═══ {inst}  ({len(bars):,} M15 bars, '
              f'{bars[0]["t"][:10]} → {bars[-1]["t"][:10]})')

        for spec in STRATEGIES:
            res = bt_run(spec, bars, h4, inst)
            trades = [{'pnl': t.pnl, 'timestamp': t.entry_time,
                       'direction': t.direction,
                       'r_multiple': t.r_multiple,
                       'result': 'W' if t.pnl > 0 else 'L'}
                      for t in res.trades]
            n = len(trades)
            stats = calculate_stats(trades, spec.key,
                                    starting_balance=STARTING_BALANCE) if n else {'n': 0}
            if n:
                _augment_stats(stats, trades)
            # MC RUIN on FIXED-SIZE P&L (2026-07-28 fix). Bootstrapping the raw
            # `pnl` series against a $10k start is the compounding artefact —
            # trades sized off a $50M peak resampled against $10k wipe by
            # construction. r_multiple is position-size-invariant; scaling it
            # by the same FIXED_RISK_PER_TRADE every trade produces a fixed-
            # size P&L distribution that the bootstrap can meaningfully test.
            fixed_pnl_series = [t['r_multiple'] * FIXED_RISK_PER_TRADE
                                for t in trades]
            mc = (monte_carlo_simulation(fixed_pnl_series,
                                         starting_balance=STARTING_BALANCE)
                  if n >= 10 else {})
            # Also record the OLD compounded MC for transparency — same input
            # the previous gate saw, so before/after is visible in one file.
            mc_compounded = (monte_carlo_simulation([t['pnl'] for t in trades],
                                                    starting_balance=STARTING_BALANCE)
                             if n >= 10 else {})
            regimes = _regime_split(res.trades, bars)
            verdict, why = _verdict(stats, mc, n, regimes)

            row = {
                'strategy': spec.key, 'name': spec.name, 'family': spec.family,
                'instrument': inst, 'n': n,
                'verdict': verdict, 'why': why,
                'stats': stats,
                'monte_carlo': mc,
                'monte_carlo_compounded': mc_compounded,
                'mc_basis': 'fixed_size_pnl (r_multiple * $75 per trade)',
                'regimes': regimes,
                'final_balance': res.final_balance,
                'skipped_low_rr': res.skipped_rr,
            }
            out['results'].append(row)
            pf = stats.get('profit_factor', 0) or 0
            sh = stats.get('sharpe', 0) or 0
            print(f'  {spec.key:16} n={n:>4}  WR {stats.get("win_rate", 0):>5.1f}%  '
                  f'PF {pf:>6.3f}  Sharpe {sh:>7.3f}  → {verdict}')

    RESULTS_PATH.write_text(json.dumps(out, indent=2, default=str))
    print(f'\nResults → {RESULTS_PATH}')
    return out


def rank(results: dict) -> list:
    """Rank by verdict tier, then profit factor. Ungraded models never rank."""
    tier = {'PASS': 0, 'MARGINAL': 1, 'FAIL': 2,
            'INSUFFICIENT_DATA': 3, 'NO_DATA': 4}
    rows = [r for r in results['results']]
    rows.sort(key=lambda r: (tier.get(r['verdict'], 9),
                             -(r['stats'].get('profit_factor', 0) or 0)))
    return rows


def _mechanism_label(strategy: str, validation: dict | None,
                     instrument: str | None = None) -> str:
    """Honest label for what a strategy's edge actually is.

    Uses the mean-reversion baseline result to differentiate three cases:
      SAME magnitudes           → mean reversion, ICT filters redundant
      turtle > baseline         → ICT filters ADD edge (real ICT)
      baseline > turtle         → mean reversion IS the edge; ICT filters HURT

    The third case is the one the previous version incorrectly folded into
    "filters are earning some of the edge" — if the baseline wins, the
    filters are filtering out winning trades, not earning edge. Say so.
    """
    if strategy != 'turtle_soup':
        return f'ICT: {strategy}'
    if not validation or 'baseline' not in validation:
        return 'turtle_soup — mechanism not yet validated (baseline pending)'
    baseline = validation.get('baseline') or []
    if not baseline:
        return 'turtle_soup — baseline result missing'

    def _direction(b: dict) -> str:
        # Compare turtle vs baseline on the two headline metrics. sharpe_ann is
        # the deployment-gate basis; PF is what MC ruin ultimately reflects.
        t = b.get('turtle_soup', {}); bl = b.get('sweep_fade_baseline', {})
        sh_delta = (t.get('sharpe_ann') or 0) - (bl.get('sharpe_ann') or 0)
        pf_ratio = (t.get('pf') or 0) / (bl.get('pf') or 1) if bl.get('pf') else 0
        if abs(sh_delta) < 0.30 and 0.85 <= pf_ratio <= 1.15:
            return 'same'
        if sh_delta > 0 and pf_ratio > 1.0:
            return 'turtle_wins'
        if sh_delta < 0 and pf_ratio < 1.0:
            return 'baseline_wins'
        return 'mixed'      # metrics disagree with each other

    counts = {'same': 0, 'turtle_wins': 0, 'baseline_wins': 0, 'mixed': 0}
    per_inst = {}
    for b in baseline:
        d = _direction(b)
        counts[d] += 1
        per_inst[b.get('instrument')] = d

    total = len(baseline)

    # If we have an instrument, give the per-instrument label — a library
    # entry is per-instrument, and the mechanism can differ across them.
    if instrument and instrument in per_inst:
        d = per_inst[instrument]
        if d == 'baseline_wins':
            return ('MEAN REVERSION (post-sweep fade). The ICT filters (H4 bias + '
                    'London/NY killzones) filter out winning trades — the plain '
                    'sweep-fade 24/7 baseline out-performs on all headline metrics '
                    'on this instrument. Deployed as-configured, but the edge is '
                    'not ICT structure.')
        if d == 'turtle_wins':
            return ('ICT structure. Killzone + H4 bias contribute measurable edge '
                    'over the plain sweep-fade baseline on this instrument.')
        if d == 'same':
            return ('MEAN REVERSION (post-sweep fade). ICT filters produce no '
                    'measurable edge over the plain sweep-fade baseline; the '
                    'filters are redundant, not harmful.')
        return ('MIXED. Turtle vs baseline metrics disagree — one metric favours '
                'the ICT filters, another does not.')

    # Fleet-wide summary (used when instrument is not provided).
    if counts['baseline_wins'] >= max(2, total * 3 // 4):
        return (f'MEAN REVERSION (post-sweep fade). On {counts["baseline_wins"]}/{total} '
                'instruments the plain sweep-fade baseline out-performs turtle_soup — '
                'the ICT filters filter out winning trades. This is mean reversion, '
                'not ICT structure. Deploy is defensible, but do not label it ICT.')
    if counts['same'] >= max(2, total * 3 // 4):
        return (f'MEAN REVERSION. On {counts["same"]}/{total} instruments turtle_soup '
                'and plain sweep-fade produce indistinguishable numbers — the ICT '
                'filters are redundant.')
    if counts['turtle_wins'] >= max(2, total * 3 // 4):
        return (f'ICT structure. On {counts["turtle_wins"]}/{total} instruments the '
                'ICT filters add measurable edge over the plain baseline.')
    return (f'MIXED. turtle_wins={counts["turtle_wins"]} baseline_wins='
            f'{counts["baseline_wins"]} same={counts["same"]} mixed={counts["mixed"]} '
            f'across {total} instruments.')


def write_library(results: dict, turtle_validation: dict | None = None) -> dict:
    """Write ONLY gate-cleared models to the shared strategy library.

    Feeds the next build (shared library + Jerry crypto). Nothing that failed
    the trade floor or the verdict gate is written as deployable — the library
    records those as researched-but-not-validated so the work is not lost and
    cannot be mistaken for a green light.

    If a `ict_turtle_validation.json` output is present, its mean-reversion-
    baseline result is used to label turtle_soup entries with what the edge
    actually is (structural ICT vs. plain post-sweep mean reversion), so a
    downstream reader is never misled about what they are deploying.
    """
    from ict_strategies import BY_KEY
    import hashlib
    validated, rejected = [], []
    for r in rank(results):
        spec = BY_KEY[r['strategy']]
        # Executor contract — the fields a live executor needs to run this
        # strategy without importing ict_strategies. Kept here so the library
        # is self-sufficient and a downstream (Blade, Edge, Pine port) has
        # everything it needs from one JSON.
        execution = {
            'entry_zone':          spec.entry_zone,
            'reverse_on_sweep':    spec.reverse_on_sweep,
            'require_sweep':       spec.require_sweep,
            'require_mss':         spec.require_mss,
            'require_displacement':spec.require_displacement,
            'require_amd':         spec.require_amd,
            'icc_filter':          spec.icc_filter,
            'htf_bias_required':   spec.htf_bias_required,
            'killzones':           list(spec.killzones),
            'entry_type':          'MARKET_ON_CLOSE' if spec.reverse_on_sweep else 'LIMIT_AT_ZONE_50',
        }
        entry = {
            'id': f"ict.{r['strategy']}.{r['instrument']}",
            'strategy': r['strategy'], 'name': r['name'],
            'family': r['family'], 'asset_class': 'cfd_index_metal_fx',
            'instrument': r['instrument'], 'timeframe': 'M15',
            'version': 1,
            'n_trades': r['n'], 'verdict': r['verdict'], 'why': r['why'],
            'stats': {k: r['stats'].get(k) for k in
                      ('win_rate', 'profit_factor', 'sharpe', 'sharpe_annualised',
                       'expectancy', 'expectancy_R',
                       'max_drawdown_pct', 'total_pnl', 'fixed_size_pnl')},
            'monte_carlo': {k: (r.get('monte_carlo') or {}).get(k) for k in
                            ('ruin_probability', 'double_probability',
                             'median_final', 'p5_final')},
            'mc_basis': r.get('mc_basis'),
            'mechanism_label': _mechanism_label(r['strategy'], turtle_validation,
                                                r['instrument']),
            'regimes': r['regimes'],
            'rules': spec.rules,
            'execution': execution,
            'params': PARAMS,
            'source': 'agents/lens/ict_research.py',
            'researched_at': results['generated_at'],
            'deployable': r['verdict'] == 'PASS',
        }
        # Content hash for change-detection by consumers. Excludes fields that
        # change on every regenerate (researched_at, mechanism_label narrative,
        # stats which vary run-to-run by MC seed). Hash covers the DECISION-
        # SURFACE fields: rules, execution contract, params, verdict — anything
        # that would materially change what a live executor does.
        surface = {
            'rules': spec.rules, 'execution': execution, 'params': PARAMS,
            'verdict': r['verdict'], 'deployable': r['verdict'] == 'PASS',
            'strategy': r['strategy'], 'instrument': r['instrument'],
        }
        entry['content_hash'] = hashlib.sha1(
            json.dumps(surface, sort_keys=True, default=str).encode()
        ).hexdigest()[:12]
        (validated if r['verdict'] == 'PASS' else rejected).append(entry)

    lib = {
        'schema': 'jcf.strategy_library/v1',
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'written_by': 'lens (ict_research.py)',
        'readers': ['blade', 'edge', 'jerry', 'chad'],
        'note': ('Only entries with deployable=true cleared the gate. Everything '
                 'else is retained as researched-but-not-validated so the work is '
                 'preserved and cannot be mistaken for approval. Jase decides '
                 'what goes live; nothing here deploys itself.'),
        'validated': validated,
        'not_validated': rejected,
    }
    LIBRARY_PATH.write_text(json.dumps(lib, indent=2, default=str))
    print(f'Library → {LIBRARY_PATH}  ({len(validated)} validated, '
          f'{len(rejected)} not validated)')
    return lib


def report(results: dict) -> str:
    rows = rank(results)
    out = ['', '═' * 100,
           'ICT / ICC RESEARCH — RANKED RESULTS  (gate: annualised Sharpe)', '═' * 100,
           f'{"strategy":16}{"instrument":12}{"n":>5}{"WR%":>7}{"PF":>8}'
           f'{"Sh_pt":>8}{"Sh_ann":>8}{"maxDD%":>8}{"net$":>11}  verdict']
    for r in rows:
        s = r['stats']
        dd = s.get('max_drawdown_pct')
        out.append(
            f'{r["strategy"]:16}{r["instrument"]:12}{r["n"]:>5}'
            f'{(s.get("win_rate") or 0):>7.1f}{(s.get("profit_factor") or 0):>8.3f}'
            f'{(s.get("sharpe") or 0):>8.3f}'
            f'{(s.get("sharpe_annualised") or 0):>8.3f}'
            f'{(dd if dd is not None else 0):>8.1f}'
            f'{(s.get("total_pnl") or 0):>11,.0f}  {r["verdict"]}')
    return '\n'.join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', action='store_true')
    ap.add_argument('--report', action='store_true')
    ap.add_argument('--rewrite-library', action='store_true',
                    help='regenerate strategy_library.json from existing '
                         'ict_research.json + ict_turtle_validation.json '
                         'without re-running the backtest')
    ap.add_argument('--instrument')
    a = ap.parse_args()

    if a.run:
        res = run_matrix([a.instrument] if a.instrument else None)
        turtle_val = _load_turtle_validation()
        write_library(res, turtle_val)
        print(report(res))
    elif a.rewrite_library:
        res = json.loads(RESULTS_PATH.read_text())
        turtle_val = _load_turtle_validation()
        write_library(res, turtle_val)
        print(report(res))
    elif a.report:
        res = json.loads(RESULTS_PATH.read_text())
        print(report(res))
    else:
        ap.print_help()
    return 0


def _load_turtle_validation() -> dict | None:
    """Read the ict_turtle_validation.json produced by the deep-validation
    script, if present, so write_library can label turtle_soup honestly with
    what its edge actually is. Missing file is silent — the library entry
    just says 'validation pending' rather than pretending to know."""
    p = Path('/root/.openclaw/dashboard/ict_turtle_validation.json')
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


if __name__ == '__main__':
    sys.exit(main())
