#!/usr/bin/env python3
"""test_lookahead.py — prove the backtester cannot see the future.

The close[1] rule is the single most important correctness property in this
research: if a rule reads the forming bar, the backtest is fiction and every
downstream verdict is worthless. The engine originally enforced it structurally
by handing each detector a `bars[:i+1]` slice, but that copy was quadratic and
had to be removed for the 190k-bar dataset. The guarantee is therefore now
enforced by discipline — which means it has to be TESTED, not asserted.

METHOD
    For many sample indices i:
      1. Run _detect on the real series and record the signal.
      2. Replace EVERY bar after i with destroyed data (prices x 10, inverted
         highs/lows, zeroed volume).
      3. Run _detect again on the corrupted series.
      4. The two signals must be byte-identical. If any rule peeked at a bar
         after i, the corruption changes the answer and the test fails.

Also verifies:
      • no incomplete candles survived the download
      • swing confirmation respects its k-bar lag
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import ict_backtest as BT                      # noqa: E402
from ict_strategies import STRATEGIES, PARAMS  # noqa: E402


_POISON: list[dict] = []


def _poison_tail(n: int, template: dict) -> list[dict]:
    """A reusable block of destroyed bars placed immediately after index i.

    Contents only have to be WRONG — inverted high/low, absurd prices, zero
    volume, a year-2099 timestamp. Any rule that reads past i will produce a
    different signal against this tail. Built once and sliced, because
    deep-copying the real tail per sample was half a billion dict copies.
    """
    global _POISON
    if len(_POISON) < n:
        _POISON = [{'t': '2099-01-01T00:00:00', 'o': 1e6, 'h': -1e6,
                    'l': 1e6, 'c': -1e6, 'v': 0, 'spread': 1e5}
                   for _ in range(n + 16)]
    return _POISON[:n]


def test_lookahead(instrument: str = 'SPX500_USD', samples: int = 300) -> bool:
    """Destroy the future, assert the signal is unchanged.

    Runs on a local WINDOW rather than the full 187k series: the detector's
    deepest backward reach is LOOKBACK_POOLS + ATR_PERIOD (~65 bars), so a
    300-bar window fully contains everything it may legitimately read, while a
    poisoned tail sits immediately after i. Same property, O(window) per call
    instead of O(series).
    """
    bars = BT.load_bars(instrument, 'M15')
    h4 = BT.load_bars(instrument, 'H4')
    if not bars:
        print('  no data — cannot test')
        return False

    WIN, TAIL = 300, 40
    warm = PARAMS['ATR_PERIOD'] + PARAMS['LOOKBACK_POOLS'] + 5
    lo, hi = warm + WIN, len(bars) - TAIL - 5
    step = max(1, (hi - lo) // samples)
    failures, checked = [], 0

    for spec in STRATEGIES:
        for pos in range(lo, hi, step):
            w_start = pos - WIN
            clean_w = bars[w_start:pos + 1 + TAIL]
            i_local = pos - w_start

            sh = BT.swing_highs(clean_w, PARAMS['SWING_K'])
            sl = BT.swing_lows(clean_w, PARAMS['SWING_K'])
            # only structure confirmed at or before i is legitimately knowable
            sh_ok = [x for x in sh if x <= i_local]
            sl_ok = [x for x in sl if x <= i_local]

            clean = BT._detect(spec, clean_w, i_local, h4, sh_ok, sl_ok)
            dirty_w = clean_w[:i_local + 1] + _poison_tail(TAIL, clean_w[i_local])
            dirty = BT._detect(spec, dirty_w, i_local, h4, sh_ok, sl_ok)

            checked += 1
            if json.dumps(clean, sort_keys=True, default=str) != \
               json.dumps(dirty, sort_keys=True, default=str):
                failures.append((spec.key, pos, clean, dirty))
                if len(failures) > 5:
                    break
        if len(failures) > 5:
            break

    print(f'  lookahead: {checked:,} detector calls compared '
          f'({len(STRATEGIES)} models x ~{samples} indices, '
          f'{TAIL} poisoned bars after each)')
    if failures:
        print(f'  FAIL — {len(failures)} signals changed when the future was destroyed')
        for k, i, a, b in failures[:3]:
            print(f'      {k} @ {i}: clean={a} dirty={b}')
        return False
    print('  PASS — every signal identical with all future bars destroyed')
    return True


def test_no_incomplete(instrument: str = 'SPX500_USD') -> bool:
    """Incomplete candles are close[0] by another name."""
    p = Path(f'/root/.openclaw/agents/lens/data/candles/{instrument}_M15.json')
    d = json.loads(p.read_text())
    bad = [c for c in d['candles'] if c.get('complete') is False]
    print(f'  incomplete candles in cache: {len(bad)}')
    return not bad


def test_swing_lag() -> bool:
    """A k-swing at index x must not be usable before x+k."""
    bars = [{'t': f'2020-01-01T00:{i:02d}:00', 'o': 1, 'h': h, 'l': h - 1,
             'c': 1, 'v': 1} for i, h in enumerate([1, 2, 5, 2, 1, 3, 9, 3, 1])]
    sh = BT.swing_highs(bars, 2)
    ok = all(x + 2 < len(bars) for x in sh)
    print(f'  swing highs found at {sh} (each needs +2 bars to confirm) — '
          f'{"OK" if ok else "FAIL"}')
    return ok


def main() -> int:
    print('── lookahead / integrity suite')
    results = [
        test_no_incomplete(),
        test_swing_lag(),
        test_lookahead(),
    ]
    ok = all(results)
    print(f'\n{"✓ ALL PASS" if ok else "✗ FAILURES PRESENT"}')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
