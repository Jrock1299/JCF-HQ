#!/usr/bin/env python3
"""futures_validation.py — validate the sweep-fade strategy on CME futures
(ES, NQ, GC) through the same gate that graded OANDA turtle_soup.

Not blind extrapolation: the validated OANDA product for each futures
instrument is documented on the row, so the answer is "does the edge that
held on OANDA X transfer to CME Y", per-instrument.

  ES ↔ SPX500_USD    (OANDA turtle_soup PASS 2026-07-27)
  NQ ↔ (no OANDA analog validated)
  GC ↔ XAU_USD       (OANDA turtle_soup PASS 2026-07-27)

Same 100-trade floor, same annualised-Sharpe basis, same fixed-size MC ruin,
same multi-regime rail. If the sample is too small (60d of M15 caps around
50-70 trades / instrument), the verdict is INSUFFICIENT_DATA — same as
every other row that falls under the floor. No compromise threshold.

CAVEAT — see futures_data.py. yfinance's intraday cap makes an at-parity
M15 test infeasible on 8 years of history. The H1 alternative gives 2
years of sample but is a different timeframe than the validated one; it
is graded here for completeness and clearly labelled as timeframe-shifted,
NOT promoted.

Usage:
    python3 futures_validation.py --interval 15m
    python3 futures_validation.py --interval 1h        # timeframe-shifted
    python3 futures_validation.py --all-intervals
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, '/root/.openclaw/scripts')

from ict_backtest import run as bt_run, STARTING_BALANCE                   # noqa: E402
from ict_strategies import BY_KEY, PARAMS                                  # noqa: E402
from ict_research import FIXED_RISK_PER_TRADE, _augment_stats, _verdict    # noqa: E402
from risk_validation import calculate_stats, monte_carlo_simulation        # noqa: E402
from futures_data import (                                                 # noqa: E402
    load_bars, download_all, YF_TICKERS, CONTRACT_SPECS,
)


TURTLE = BY_KEY['turtle_soup']
OUT_PATH = Path('/root/.openclaw/dashboard/futures_validation.json')

# Where the validated OANDA analog for each futures instrument lives.
# 'none' = no direct OANDA analog was validated; treat as pure new.
OANDA_ANALOG = {
    'ES': 'SPX500_USD',
    'NQ': 'none',
    'GC': 'XAU_USD',
}


def _aggregate_to_h4(m_bars: list[dict], target_minutes: int = 240) -> list[dict]:
    """Aggregate the M15 (or M30/H1) series into H4 bars for the HTF-bias
    filter turtle_soup uses. Simple bucket by floor(minute / target_minutes).
    Loses some precision at bucket boundaries; fine for a bias filter."""
    from datetime import datetime as _dt
    if not m_bars:
        return []
    out = []
    bucket = None
    bucket_ts = None
    for b in m_bars:
        try:
            ts = _dt.fromisoformat(b['t'])
        except (ValueError, TypeError):
            continue
        epoch = int(ts.timestamp())
        bs = epoch - (epoch % (target_minutes * 60))
        if bs != bucket_ts:
            if bucket is not None:
                out.append(bucket)
            bucket = {'t': _dt.utcfromtimestamp(bs).strftime('%Y-%m-%dT%H:%M:%S'),
                      'o': b['o'], 'h': b['h'], 'l': b['l'], 'c': b['c'],
                      'v': b.get('v', 0),
                      'spread': b.get('spread', 0.0)}
            bucket_ts = bs
        else:
            bucket['h'] = max(bucket['h'], b['h'])
            bucket['l'] = min(bucket['l'], b['l'])
            bucket['c'] = b['c']
            bucket['v'] += b.get('v', 0)
    if bucket is not None:
        out.append(bucket)
    return out


def _grade(trades_list: list, instrument: str) -> dict:
    """Same grading path as ict_research.run_matrix, per-instrument."""
    trades = [{'pnl': t.pnl, 'timestamp': t.entry_time,
               'direction': t.direction, 'r_multiple': t.r_multiple,
               'result': 'W' if t.pnl > 0 else 'L'}
              for t in trades_list]
    n = len(trades)
    if n == 0:
        return {'n': 0, 'verdict': 'NO_DATA', 'why': 'no trades', 'stats': {}, 'mc': {}}

    stats = calculate_stats(trades, TURTLE.key, starting_balance=STARTING_BALANCE)
    _augment_stats(stats, trades)

    fixed_pnl = [t['r_multiple'] * FIXED_RISK_PER_TRADE for t in trades]
    mc = (monte_carlo_simulation(fixed_pnl, starting_balance=STARTING_BALANCE)
          if n >= 10 else {})

    # regime split by year (from ict_research)
    by_year: dict = {}
    for t in trades_list:
        y = t.entry_time[:4]
        by_year.setdefault(y, []).append(t.pnl)
    regimes = {y: {'n': len(v), 'pnl': round(sum(v), 2),
                   'wr': round(100 * sum(1 for x in v if x > 0) / len(v), 1)}
               for y, v in sorted(by_year.items())}

    verdict, why = _verdict(stats, mc, n, regimes)
    return {'n': n, 'verdict': verdict, 'why': why,
            'stats': stats, 'mc': mc, 'regimes': regimes}


def validate_one(sym: str, interval: str = '15m') -> dict:
    bars = load_bars(sym, interval)
    if not bars:
        return {'instrument': sym, 'interval': interval,
                'error': 'no cached bars — run futures_data.py --download first'}

    # Build an HTF series for the bias filter. Turtle_soup calls _htf_bias
    # which reads H4 close vs H4 EMA-50.
    if interval == '15m':
        h4 = _aggregate_to_h4(bars, 240)
    elif interval == '30m':
        h4 = _aggregate_to_h4(bars, 240)
    elif interval == '1h':
        h4 = _aggregate_to_h4(bars, 240)
    else:
        # daily: no HTF filter meaningful; use itself
        h4 = bars

    result = bt_run(TURTLE, bars, h4, sym)
    graded = _grade(result.trades, sym)
    graded.update({
        'instrument': sym,
        'yf_ticker': YF_TICKERS[sym],
        'oanda_analog': OANDA_ANALOG.get(sym, 'unknown'),
        'interval': interval,
        'contract_spec': CONTRACT_SPECS[sym],
        'span': {'first_bar': bars[0]['t'] if bars else None,
                 'last_bar':  bars[-1]['t'] if bars else None,
                 'n_bars':    len(bars)},
    })
    return graded


def _print_row(r: dict) -> None:
    s = r.get('stats', {}) or {}
    print(f'  {r["instrument"]:4} {r["interval"]:>4} n={r["n"]:>5}  '
          f'WR={(s.get("win_rate") or 0):>5.1f}%  '
          f'PF={(s.get("profit_factor") or 0):>6.3f}  '
          f'Sh_ann={(s.get("sharpe_annualised") or 0):>7.3f}  '
          f'MaxDD={(s.get("max_drawdown_pct") or 0):>5.1f}%  '
          f'ruin={((r.get("mc") or {}).get("ruin_probability") or 0):>5.2f}%  '
          f'→ {r["verdict"]}')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--interval', default='15m',
                    choices=('15m', '30m', '1h'))
    ap.add_argument('--all-intervals', action='store_true',
                    help='run every interval (15m, 30m, 1h) for cross-check')
    ap.add_argument('--download', action='store_true',
                    help='download fresh data before running')
    ap.add_argument('--instrument', action='append', help='limit to ES/NQ/GC')
    a = ap.parse_args()

    intervals = ['15m', '30m', '1h'] if a.all_intervals else [a.interval]
    instruments = a.instrument or list(YF_TICKERS)

    if a.download:
        for iv in intervals:
            print(f'\ndownload interval={iv}')
            download_all(iv, '60d' if iv in ('15m', '30m') else '730d')

    out = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'gate_basis':   'same as ict_research: annualised Sharpe, 100-trade floor, '
                        'PF>=1.5 for PASS, MaxDD<25, ruin<=10 on fixed-size MC.',
        'data_source':  'yfinance (see futures_data.py caveats)',
        'results': [],
    }
    for iv in intervals:
        print(f'\n── interval {iv}')
        for sym in instruments:
            r = validate_one(sym, iv)
            out['results'].append(r)
            if 'error' in r:
                print(f'  {sym} {iv}: {r["error"]}')
            else:
                _print_row(r)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, default=str))
    print(f'\nresult → {OUT_PATH}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
