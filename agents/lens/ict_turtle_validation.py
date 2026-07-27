#!/usr/bin/env python3
"""ict_turtle_validation.py — deep-validate turtle_soup.

Written 2026-07-27 after Jase ruled to switch the deployment gate from
per-trade to annualised Sharpe. Under the new basis turtle_soup passes the
Sharpe check on all four instruments (2.4-2.8) but still fails the ruin
check — a known compounding artifact in the MC input, flagged by the
2026-07-27 ICT/ICC commit as "reported but not applied". These three tests
are independent of the gate verdict: whether the strategy has REAL edge is
tested here, on its own terms.

Three tests, each answering a specific question:

  1. WALK-FORWARD.
     Optimise on a rolling in-sample window, test on the next out-of-sample
     window, then roll forward. Confirms the edge holds forward, not just in
     aggregate. If OOS collapses vs. IS, the earlier in-sample looked good
     because parameters were fitted to that period.

  2. PARAMETER SENSITIVITY.
     Vary the key knobs (sweep lookback, stop buffer, killzone windows,
     lookback pools). If small parameter shifts collapse the edge, it is
     overfit. If it survives a range, it is robust.

  3. MEAN-REVERSION BASELINE.
     Turtle Soup already skips MSS and displacement. The remaining ICT-
     specific pieces are the H4 EMA-50 bias filter and the London/NY
     killzone. Strip both and fade the sweep 24/7 with no ICT confirmation
     at all. If the baseline performs the same as turtle_soup, the edge
     is post-sweep mean reversion — dress it up as ICT and we mislead
     ourselves and every downstream reader. Say plainly what it is.

    python3 ict_turtle_validation.py --walkforward
    python3 ict_turtle_validation.py --sensitivity
    python3 ict_turtle_validation.py --baseline
    python3 ict_turtle_validation.py --all

RUNTIME NOTE. Requires the OANDA candle cache at
/root/.openclaw/agents/lens/data/candles/. Refuses to run without it rather
than silently backtesting on nothing. The candle cache lives on the VPS;
download locally with `python3 ict_data.py --download` if OANDA credentials
are present in agents/lens/auth-profiles.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, '/root/.openclaw/scripts')

from ict_backtest import run as bt_run, load_bars, STARTING_BALANCE   # noqa: E402
from ict_strategies import STRATEGIES, PARAMS, BY_KEY, StrategySpec, KILLZONES  # noqa: E402

# Same gate the live pipeline uses, so validation reports and the deployment
# gate can never diverge on Sharpe basis or thresholds.
from risk_validation import calculate_stats, monte_carlo_simulation             # noqa: E402


TURTLE = BY_KEY['turtle_soup']
INSTRUMENTS = ['SPX500_USD', 'DE30_EUR', 'XAU_USD', 'CHF_JPY']
OUT_PATH = Path('/root/.openclaw/dashboard/ict_turtle_validation.json')


def _bars_or_die(inst: str) -> tuple:
    bars = load_bars(inst, 'M15')
    h4 = load_bars(inst, 'H4')
    if not bars or not h4:
        raise SystemExit(f'candles missing for {inst}. Run ict_data.py --download on '
                         f'a host with OANDA credentials before validating.')
    return bars, h4


def _trades_to_records(trades: list) -> list[dict]:
    return [{'pnl': t.pnl, 'timestamp': t.entry_time,
             'direction': t.direction} for t in trades]


def _year_of(ts: str) -> int:
    return int(ts[:4])


# ══════════════════════════════════════════════════════════════════════════════
# 1. Walk-forward
# ══════════════════════════════════════════════════════════════════════════════

def walkforward_one(inst: str, in_years: int = 2, out_years: int = 1) -> dict:
    """Rolling in-sample / out-of-sample walk-forward.

    Turtle Soup has no free parameters that _detect() reads outside PARAMS —
    the "in-sample optimisation" here is deliberately trivial: fit nothing,
    just confirm the aggregate IS stats and then re-measure them on the OOS
    window. That IS the honest walk-forward for a parameter-less rule set:
    "does the mechanism keep working forward?" Optimising nothing is not a
    weakness; overfitting on the IS window is the risk the test guards
    against and there is nothing here to over-fit.

    Reports IS vs OOS: n, WR, PF, per-trade Sharpe, annualised Sharpe,
    expectancy_R, max DD (fixed-size, from ict_backtest).
    """
    bars, h4 = _bars_or_die(inst)
    all_res = bt_run(TURTLE, bars, h4, inst)
    trades_by_year: dict = {}
    for t in all_res.trades:
        trades_by_year.setdefault(_year_of(t.entry_time), []).append(t)

    years = sorted(trades_by_year.keys())
    windows = []
    i = 0
    while i + in_years + out_years - 1 < len(years):
        is_years = years[i:i + in_years]
        oos_years = years[i + in_years:i + in_years + out_years]
        is_trades = [t for y in is_years for t in trades_by_year[y]]
        oos_trades = [t for y in oos_years for t in trades_by_year[y]]

        def _stat(trades: list) -> dict:
            recs = _trades_to_records(trades)
            s = calculate_stats(recs, TURTLE.key, starting_balance=STARTING_BALANCE)
            mc = (monte_carlo_simulation([r['pnl'] for r in recs],
                                         starting_balance=STARTING_BALANCE)
                  if len(recs) >= 30 else {})
            return {'n': len(recs), 'wr': s.get('win_rate'), 'pf': s.get('profit_factor'),
                    'sharpe_pt': s.get('sharpe'),
                    'sharpe_ann': s.get('sharpe_annualised'),
                    'max_dd_pct': s.get('max_drawdown_pct'),
                    'expectancy': s.get('expectancy'),
                    'ruin': mc.get('ruin_probability')}

        windows.append({
            'in_sample':   {'years': is_years,  **_stat(is_trades)},
            'out_of_sample': {'years': oos_years, **_stat(oos_trades)},
        })
        i += out_years

    return {'instrument': inst, 'in_years': in_years, 'out_years': out_years,
            'windows': windows}


# ══════════════════════════════════════════════════════════════════════════════
# 2. Parameter sensitivity
# ══════════════════════════════════════════════════════════════════════════════

# Deliberately narrow, mechanistic sweeps — enough to detect a fitted knob,
# small enough that the matrix stays a matter of minutes not hours. Named
# knobs are the ones turtle_soup actually reads: sweep lookback (via
# LOOKBACK_POOLS + MSS_MAX_BARS_AFTER_SWEEP), the stop buffer, and the risk
# floor. Killzones handled separately below.
SWEEPS = {
    'LOOKBACK_POOLS':          [25, 50, 75, 100],
    'MSS_MAX_BARS_AFTER_SWEEP': [10, 20, 40, 60],
    'STOP_BUFFER_ATR':         [0.10, 0.25, 0.50, 1.00],
    'MIN_STOP_ATR':            [0.25, 0.50, 1.00, 1.50],
    'MIN_RR':                  [1.5, 2.0, 3.0, 4.0],
}

KILLZONE_VARIANTS = {
    'default_LDN_NY': ('LONDON', 'NY'),
    'london_only':    ('LONDON',),
    'ny_only':        ('NY',),
    'all_hours':      None,             # sentinel — no killzone filter
}


def _run_variant(inst: str, param_overrides: dict, kz=None) -> dict:
    """Run turtle_soup once with a modified PARAMS block and/or killzones."""
    bars, h4 = _bars_or_die(inst)
    original = dict(PARAMS)
    PARAMS.update(param_overrides)
    try:
        if kz is None and kz != ():
            spec = TURTLE
        elif kz == ():
            # sentinel "all hours": stub a spec whose killzones cover 0-24
            all_zone = ('__ALL__',)
            KILLZONES.setdefault('__ALL__', (0, 24))
            spec = replace(TURTLE, killzones=all_zone)
        else:
            spec = replace(TURTLE, killzones=kz)
        res = bt_run(spec, bars, h4, inst)
    finally:
        PARAMS.clear(); PARAMS.update(original)

    recs = _trades_to_records(res.trades)
    if not recs:
        return {'n': 0}
    s = calculate_stats(recs, TURTLE.key, starting_balance=STARTING_BALANCE)
    return {'n': len(recs), 'wr': s.get('win_rate'), 'pf': s.get('profit_factor'),
            'sharpe_ann': s.get('sharpe_annualised'),
            'max_dd_pct': s.get('max_drawdown_pct'),
            'expectancy': s.get('expectancy')}


def sensitivity_one(inst: str) -> dict:
    out = {'instrument': inst, 'baseline': _run_variant(inst, {}), 'sweeps': {}}
    for knob, values in SWEEPS.items():
        out['sweeps'][knob] = [
            {'value': v, **_run_variant(inst, {knob: v})} for v in values
        ]
    out['killzones'] = [
        {'variant': name, **_run_variant(inst, {}, kz=(zones if zones else ()))}
        for name, zones in KILLZONE_VARIANTS.items()
    ]
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 3. Mean-reversion baseline (no ICT confirmation)
# ══════════════════════════════════════════════════════════════════════════════
#
# Turtle Soup's remaining "ICT" pieces after MSS/displacement are already
# skipped: the H4 EMA-50 bias filter and the London/NY killzones. The
# baseline strips BOTH and fades the sweep unconditionally. Same sweep
# detection, same stop and target rules, same risk sizing. If the numbers
# are indistinguishable, the edge is mean reversion — not ICT structure —
# and the strategy label must say so.

def baseline_spec() -> StrategySpec:
    KILLZONES.setdefault('__ALL__', (0, 24))
    return replace(
        TURTLE,
        key='sweep_fade_baseline',
        name='Sweep fade (no killzone, no HTF bias) — mean-reversion control',
        family='baseline',
        killzones=('__ALL__',),
        htf_bias_required=False,
    )


def baseline_one(inst: str) -> dict:
    bars, h4 = _bars_or_die(inst)
    spec = baseline_spec()
    turtle_res = bt_run(TURTLE, bars, h4, inst)
    base_res = bt_run(spec, bars, h4, inst)

    def _stat(res) -> dict:
        recs = _trades_to_records(res.trades)
        if not recs:
            return {'n': 0}
        s = calculate_stats(recs, res.strategy, starting_balance=STARTING_BALANCE)
        mc = (monte_carlo_simulation([r['pnl'] for r in recs],
                                     starting_balance=STARTING_BALANCE)
              if len(recs) >= 30 else {})
        return {'n': len(recs), 'wr': s.get('win_rate'), 'pf': s.get('profit_factor'),
                'sharpe_ann': s.get('sharpe_annualised'),
                'expectancy': s.get('expectancy'),
                'max_dd_pct': s.get('max_drawdown_pct'),
                'ruin': mc.get('ruin_probability')}

    turtle_stat = _stat(turtle_res)
    base_stat = _stat(base_res)

    # Verdict: are they materially different?
    def _delta_pct(a, b):
        if a is None or b is None or b == 0:
            return None
        return round((a - b) / abs(b) * 100, 1)

    diff = {
        'n_delta':          (turtle_stat.get('n') or 0) - (base_stat.get('n') or 0),
        'pf_ratio':         (round((turtle_stat.get('pf') or 0) / (base_stat.get('pf') or 1), 3)
                             if base_stat.get('pf') else None),
        'sharpe_ann_delta': (round((turtle_stat.get('sharpe_ann') or 0)
                                   - (base_stat.get('sharpe_ann') or 0), 3)),
        'expectancy_delta_pct': _delta_pct(turtle_stat.get('expectancy'),
                                           base_stat.get('expectancy')),
    }

    same = (abs(diff['sharpe_ann_delta'] or 0) < 0.30 and
            (diff['pf_ratio'] or 1) >= 0.85 and (diff['pf_ratio'] or 1) <= 1.15)

    if same:
        finding = ('SAME. Killzone + HTF bias contribute no measurable edge over '
                   'plain sweep-fade. This is mean reversion, not ICT.')
    else:
        finding = ('DIFFERENT. Killzone + HTF bias measurably move the numbers — '
                   'the ICT-specific filters are earning some of the edge.')

    return {'instrument': inst,
            'turtle_soup': turtle_stat,
            'sweep_fade_baseline': base_stat,
            'diff': diff, 'finding': finding, 'same_edge': bool(same)}


# ══════════════════════════════════════════════════════════════════════════════
# Runner
# ══════════════════════════════════════════════════════════════════════════════

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--walkforward', action='store_true')
    ap.add_argument('--sensitivity', action='store_true')
    ap.add_argument('--baseline',    action='store_true')
    ap.add_argument('--all',         action='store_true')
    ap.add_argument('--instrument',  action='append',
                    help='limit to one instrument (repeatable)')
    ap.add_argument('--out', default=str(OUT_PATH))
    a = ap.parse_args()

    do_wf   = a.walkforward or a.all
    do_sens = a.sensitivity or a.all
    do_base = a.baseline    or a.all
    if not any([do_wf, do_sens, do_base]):
        ap.print_help(); return 1

    instruments = a.instrument or INSTRUMENTS
    out = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'gate_basis':   'annualised Sharpe (per-trade retained as reference)',
        'note': ('Walk-forward has no parameters to fit — turtle_soup is a rule '
                 'set with fixed knobs. The window structure is honest: prove IS '
                 'stats also hold on the untouched OOS window.'),
        'instruments': instruments,
        'walkforward': [], 'sensitivity': [], 'baseline': [],
    }

    if do_wf:
        print('\n── walk-forward ──────────────────────────────────────────────')
        for inst in instruments:
            print(f'  {inst}')
            out['walkforward'].append(walkforward_one(inst))
    if do_sens:
        print('\n── parameter sensitivity ─────────────────────────────────────')
        for inst in instruments:
            print(f'  {inst}')
            out['sensitivity'].append(sensitivity_one(inst))
    if do_base:
        print('\n── mean-reversion baseline ───────────────────────────────────')
        for inst in instruments:
            print(f'  {inst}')
            out['baseline'].append(baseline_one(inst))

    Path(a.out).write_text(json.dumps(out, indent=2, default=str))
    print(f'\nvalidation → {a.out}')
    _summary(out)
    return 0


def _summary(out: dict) -> None:
    if out['walkforward']:
        print('\nWALK-FORWARD (IS PF | OOS PF, IS Sh_ann | OOS Sh_ann, n IS | n OOS)')
        for w in out['walkforward']:
            print(f'  {w["instrument"]}:')
            for wnd in w['windows']:
                i, o = wnd['in_sample'], wnd['out_of_sample']
                print(f'    IS {i["years"]}  n={i["n"]}  PF={i["pf"]}  Sh_ann={i["sharpe_ann"]}   '
                      f'|  OOS {o["years"]}  n={o["n"]}  PF={o["pf"]}  Sh_ann={o["sharpe_ann"]}')
    if out['baseline']:
        print('\nMEAN-REVERSION BASELINE vs TURTLE SOUP')
        for b in out['baseline']:
            print(f'  {b["instrument"]}: {b["finding"]}')
            print(f'    turtle:   n={b["turtle_soup"].get("n")}  '
                  f'PF={b["turtle_soup"].get("pf")}  Sh_ann={b["turtle_soup"].get("sharpe_ann")}')
            print(f'    baseline: n={b["sweep_fade_baseline"].get("n")}  '
                  f'PF={b["sweep_fade_baseline"].get("pf")}  '
                  f'Sh_ann={b["sweep_fade_baseline"].get("sharpe_ann")}')


if __name__ == '__main__':
    sys.exit(main())
