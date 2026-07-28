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


def write_library(results: dict) -> dict:
    """Write ONLY gate-cleared models to the shared strategy library.

    Feeds the next build (shared library + Jerry crypto). Nothing that failed
    the trade floor or the verdict gate is written as deployable — the library
    records those as researched-but-not-validated so the work is not lost and
    cannot be mistaken for a green light.
    """
    from ict_strategies import BY_KEY
    validated, rejected = [], []
    for r in rank(results):
        entry = {
            'id': f"ict.{r['strategy']}.{r['instrument']}",
            'strategy': r['strategy'], 'name': r['name'],
            'family': r['family'], 'asset_class': 'cfd_index_metal_fx',
            'instrument': r['instrument'], 'timeframe': 'M15',
            'version': 1,
            'n_trades': r['n'], 'verdict': r['verdict'], 'why': r['why'],
            'stats': {k: r['stats'].get(k) for k in
                      ('win_rate', 'profit_factor', 'sharpe', 'expectancy',
                       'max_drawdown_pct', 'total_pnl')},
            'regimes': r['regimes'],
            'rules': BY_KEY[r['strategy']].rules,
            'params': PARAMS,
            'source': 'agents/lens/ict_research.py',
            'researched_at': results['generated_at'],
            'deployable': r['verdict'] == 'PASS',
        }
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
    ap.add_argument('--instrument')
    a = ap.parse_args()

    if a.run:
        res = run_matrix([a.instrument] if a.instrument else None)
        write_library(res)
        print(report(res))
    elif a.report:
        res = json.loads(RESULTS_PATH.read_text())
        print(report(res))
    else:
        ap.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
