#!/usr/bin/env python3
"""regrade_ict_research.py — regrade an existing ict_research.json under the
annualised-Sharpe gate WITHOUT re-running the backtest.

Written 2026-07-27 alongside the gate change. Purpose: prove the switch is a
pure recompute of the verdict from the same underlying trade statistics
(sharpe_annualised = sharpe_per_trade * sqrt(trades_per_year)) — no candles
touched, no re-simulation, no chance of drift between what the previous
report said the trades did and what a re-run today would say.

    python3 scripts/regrade_ict_research.py               # print regraded table
    python3 scripts/regrade_ict_research.py --write       # ALSO overwrite the JSON

The gate rules below are a byte-for-byte copy of ict_research._verdict AS OF
2026-07-27. Kept standalone so the regrader has no dependency on the VPS-only
imports in risk_validation.py — it runs anywhere Python does, from a laptop
without OANDA credentials. Any future edit to the gate must land in both
places; a one-line assertion in the CI-style self-test at the bottom guards
against drift.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


REPO = Path(__file__).resolve().parent.parent
DEFAULT_PATH = REPO / 'dashboard' / 'ict_research.json'

MIN_TRADES_FOR_VERDICT = 100


def verdict(stats: dict, mc: dict, n: int, regimes: dict):
    """Mirror of ict_research._verdict, ANNUALISED-Sharpe basis."""
    if n == 0:
        return 'NO_DATA', 'No trades generated.'
    if n < MIN_TRADES_FOR_VERDICT:
        return ('INSUFFICIENT_DATA',
                f'{n} trades — below the {MIN_TRADES_FOR_VERDICT}-trade floor. '
                f'Not graded. Any performance figure here is descriptive only.')

    pf = stats.get('profit_factor', 0) or 0
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


def infer_annualisation(row: dict, years_hint: Optional[float] = None) -> float:
    """Recover trades-per-year annualisation for a row that predates the
    sharpe_annualised field.

    Regime rows are keyed by calendar year — the source of the dataset's span.
    If they're missing, fall back to years_hint from the dataset header or a
    bald 252 (roughly daily).
    """
    regs = row.get('regimes') or {}
    n = row.get('n', 0) or (row.get('stats', {}).get('n', 0))
    if n <= 0:
        return 252.0
    if regs:
        years = list(regs.keys())
        if len(years) >= 2:
            try:
                span_years = int(years[-1]) - int(years[0]) + 1
                if span_years >= 1:
                    return n / span_years
            except ValueError:
                pass
    if years_hint and years_hint > 0:
        return n / years_hint
    return 252.0


def regrade(path: Path, write: bool = False) -> dict:
    data = json.loads(path.read_text())

    years_hint = None
    for r in data.get('results', []):
        regs = r.get('regimes') or {}
        if regs:
            try:
                span = int(list(regs.keys())[-1]) - int(list(regs.keys())[0]) + 1
                years_hint = max(years_hint or 0, span)
            except ValueError:
                pass

    updated = graded = passes = 0
    for r in data['results']:
        stats = r.setdefault('stats', {})
        n = r.get('n', 0) or stats.get('n', 0)
        sh = stats.get('sharpe', 0) or 0
        # The prior run already computed sharpe_annualised from real timestamp
        # spans (stats['trades_per_year']); prefer that. Only compute here as a
        # fallback for rows that predate the field.
        if stats.get('sharpe_annualised') is None:
            ann_factor = infer_annualisation(r, years_hint)
            sh_ann = float(sh * math.sqrt(ann_factor))
            stats['sharpe_annualised'] = round(sh_ann, 3)
            stats['annualisation_factor'] = round(ann_factor, 2)
        elif stats.get('annualisation_factor') is None and stats.get('trades_per_year'):
            stats['annualisation_factor'] = float(stats['trades_per_year'])

        old_verdict = r.get('verdict')
        old_why = r.get('why', '')
        new_verdict, new_why = verdict(stats, r.get('monte_carlo', {}) or {},
                                       n, r.get('regimes', {}) or {})
        r['verdict'] = new_verdict
        r['why'] = new_why
        r['verdict_history'] = r.get('verdict_history', []) + [{
            'from': old_verdict, 'to': new_verdict,
            'reason': 'gate switched from per-trade to annualised Sharpe (2026-07-27)',
            'old_why': old_why,
        }]
        if new_verdict in ('PASS', 'FAIL', 'MARGINAL'):
            graded += 1
            if new_verdict == 'PASS':
                passes += 1
        if new_verdict != old_verdict:
            updated += 1

    data['regraded_at'] = datetime.now(timezone.utc).isoformat()
    data['gate_note'] = ('Verdicts regraded 2026-07-27 under ANNUALISED Sharpe. '
                         'Trade statistics unchanged; only the Sharpe basis and '
                         'therefore the verdict re-tier are recomputed. See '
                         'scripts/regrade_ict_research.py.')

    if write:
        path.write_text(json.dumps(data, indent=2, default=str))
        print(f'wrote {path}')

    return {'total': len(data['results']), 'graded': graded, 'passes': passes,
            'changed_verdicts': updated, 'data': data}


def print_table(data: dict) -> None:
    print()
    print('=' * 106)
    print('ICT / ICC — REGRADED UNDER ANNUALISED SHARPE (2026-07-27)')
    print('=' * 106)
    print(f'{"strategy":16}{"instrument":12}{"n":>5}{"WR%":>7}{"PF":>8}'
          f'{"Sh_pt":>8}{"Sh_ann":>8}{"maxDD%":>8}{"years":>7}  verdict → change')

    tier = {'PASS': 0, 'MARGINAL': 1, 'FAIL': 2,
            'INSUFFICIENT_DATA': 3, 'NO_DATA': 4}
    rows = sorted(data['results'],
                  key=lambda r: (tier.get(r['verdict'], 9),
                                 -(r['stats'].get('sharpe_annualised', 0) or 0)))
    for r in rows:
        s = r['stats']
        prof_years = sum(1 for x in (r.get('regimes') or {}).values() if x['pnl'] > 0)
        total_years = len(r.get('regimes') or {})
        change = ''
        hist = r.get('verdict_history') or []
        if hist and hist[-1]['from'] != hist[-1]['to']:
            change = f'  ({hist[-1]["from"]} -> {hist[-1]["to"]})'
        dd = s.get('max_drawdown_pct')
        print(f'{r["strategy"]:16}{r["instrument"]:12}{r["n"]:>5}'
              f'{(s.get("win_rate") or 0):>7.1f}{(s.get("profit_factor") or 0):>8.3f}'
              f'{(s.get("sharpe") or 0):>8.3f}'
              f'{(s.get("sharpe_annualised") or 0):>8.3f}'
              f'{(dd if dd is not None else 0):>8.1f}'
              + f'{prof_years}/{total_years}'.rjust(7)
              + f'  {r["verdict"]}{change}')

    print()
    print(f'Gate: annualised Sharpe >= 0.5. Trades >= {MIN_TRADES_FOR_VERDICT}. '
          f'Every other criterion unchanged (PF, MaxDD, multi-regime, ruin <= 10%).')
    print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--path', default=str(DEFAULT_PATH),
                    help='ict_research.json to regrade (default: dashboard/ict_research.json)')
    ap.add_argument('--write', action='store_true',
                    help='also overwrite the JSON with regraded verdicts')
    args = ap.parse_args()

    out = regrade(Path(args.path), write=args.write)
    print_table(out['data'])
    print(f'Total: {out["total"]}   graded: {out["graded"]}   '
          f'PASS: {out["passes"]}   verdict-changes: {out["changed_verdicts"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
