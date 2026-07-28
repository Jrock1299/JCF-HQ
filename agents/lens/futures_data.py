#!/usr/bin/env python3
"""futures_data.py — yfinance fetcher for CME futures, output shaped like
ict_backtest's bar dicts so bt_run can consume it directly.

Written 2026-07-28 for the ES/NQ/GC validation of the sweep-fade strategy
that passed on OANDA SPX500/DE30/XAU. Uses yfinance because it's free and
gives us SOMETHING to grade; the intraday history is the constraint (see
below).

DATA-QUALITY CAVEATS (read before trusting anything below).

  1. **Intraday history is 60 days.** yfinance's 15m/30m endpoints are
     capped at ~60 days of history. That gives ~4,500 M15 bars per
     instrument — roughly 1/40th of what the OANDA validation ran on
     (~190k bars over 8 years). At turtle_soup's ~1.2 trades/day, 60
     days produces ~50-70 trades — BELOW the 100-trade gate floor.
     Verdict at M15 will be INSUFFICIENT_DATA regardless of the numbers.

  2. **H1 has ~2 years.** yfinance gives 730d of hourly data. That is
     a valid-size sample but a DIFFERENT TIMEFRAME than the one the
     strategy was validated on. Extrapolating M15 rules to H1 is
     precisely the "don't assume" the deploy brief warned against —
     H1 sweep dynamics are not the same as M15's. Report the numbers,
     do not promote.

  3. **Continuous-contract mechanics.** ES=F/NQ=F/GC=F are front-month
     roll-adjusted continuous series. Rolls introduce small gaps on
     the ~quarterly roll dates. Not a killer but worth knowing.

  4. **No bid/ask spread field.** yfinance gives OHLCV only. We
     approximate spread as 1 tick per instrument (see TICK_SIZE), which
     under-states the real spread during off-hours and news events.
     Costs will be conservatively OK for RTH; may be optimistic for
     overnight sessions.

For a genuine same-basis validation on futures, we need a paid feed
(Databento personal is ~$100/mo; Polygon.io similar; IBKR requires TWS
+ market-data subs). Scoped out separately.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


YF_TICKERS = {
    'ES': 'ES=F',
    'NQ': 'NQ=F',
    'GC': 'GC=F',
}

# CME futures per-point USD value (multiplier) + tick size in price units.
# Numbers verified against CME product specs.
CONTRACT_SPECS = {
    'ES': {'point_value_usd': 50.00, 'tick_size': 0.25},   # e-mini S&P
    'NQ': {'point_value_usd': 20.00, 'tick_size': 0.25},   # e-mini Nasdaq
    'GC': {'point_value_usd': 100.00, 'tick_size': 0.10},  # 100 troy oz gold
}

# Realistic per-contract round-trip commission for a prop-firm eval / IBKR
# (varies by broker; conservative $4/side = $8 RT is typical for ES/NQ,
# $6/side = $12 RT for GC). We charge HALF at entry, HALF at exit.
COMMISSION_PER_SIDE_USD = {'ES': 4.00, 'NQ': 4.00, 'GC': 6.00}

OUT_DIR = Path('/root/.openclaw/agents/lens/data/futures_candles')


def _df_to_bars(df, tick_size: float) -> list[dict]:
    """Convert a yfinance DataFrame → the list-of-dicts shape ict_backtest
    expects. Complete bars only (yfinance's last row can be a still-forming
    bar during live hours; guard by dropping any NaN row).
    """
    import pandas as pd
    if df is None or df.empty:
        return []
    df = df.dropna()
    out = []
    prev_close = None
    for ts, row in df.iterrows():
        try:
            o = float(row['Open']); h = float(row['High'])
            l = float(row['Low']); c = float(row['Close'])
            v = int(row.get('Volume', 0) or 0)
        except (KeyError, ValueError, TypeError):
            continue
        # yfinance timestamps are timezone-aware UTC when interval < 1d
        if hasattr(ts, 'tz_convert') and ts.tz is not None:
            ts_utc = ts.tz_convert('UTC')
        else:
            ts_utc = pd.Timestamp(ts, tz='UTC')
        row_out = {
            't': ts_utc.strftime('%Y-%m-%dT%H:%M:%S'),
            'o': o, 'h': h, 'l': l, 'c': c, 'v': v,
            'spread': float(tick_size),      # conservative 1-tick spread proxy
        }
        out.append(row_out)
        prev_close = c
    return out


def fetch(sym: str, interval: str = '15m', period: str = '60d') -> list[dict]:
    """Fetch candles from yfinance for one instrument."""
    import yfinance as yf
    tk = YF_TICKERS[sym]
    spec = CONTRACT_SPECS[sym]
    df = yf.download(tk, period=period, interval=interval,
                     auto_adjust=False, progress=False)
    # yfinance returns MultiIndex columns when multiple tickers are requested;
    # single ticker still sometimes comes back with a MultiIndex — flatten.
    if hasattr(df.columns, 'levels'):
        df.columns = [c[0] for c in df.columns]
    bars = _df_to_bars(df, spec['tick_size'])
    return bars


def download_all(interval: str = '15m', period: str = '60d') -> dict:
    """Fetch + cache to disk under agents/lens/data/futures_candles/."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for sym in YF_TICKERS:
        bars = fetch(sym, interval, period)
        p = OUT_DIR / f'{sym}_{interval}.json'
        p.write_text(json.dumps({
            'instrument': sym, 'yf_ticker': YF_TICKERS[sym],
            'interval': interval, 'period': period,
            'downloaded_at': datetime.now(timezone.utc).isoformat(),
            'count': len(bars),
            'first': bars[0]['t'] if bars else None,
            'last':  bars[-1]['t'] if bars else None,
            'source': 'yfinance',
            'candles': bars,
        }))
        manifest[sym] = {'bars': len(bars), 'path': str(p),
                         'first': bars[0]['t'] if bars else None,
                         'last':  bars[-1]['t'] if bars else None}
        print(f'  {sym} {interval}: {len(bars):>6,} bars '
              f'{bars[0]["t"][:10] if bars else "-"} → {bars[-1]["t"][:10] if bars else "-"}')
    return manifest


def load_bars(sym: str, interval: str = '15m') -> list[dict]:
    """Load previously-cached bars from disk. Empty list if missing."""
    p = OUT_DIR / f'{sym}_{interval}.json'
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text()).get('candles', [])
    except (json.JSONDecodeError, OSError):
        return []


def _cli() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--download', action='store_true',
                    help='fetch and cache to disk')
    ap.add_argument('--interval', default='15m',
                    choices=('15m', '30m', '1h', '1d'),
                    help='yfinance interval')
    ap.add_argument('--period', default='60d',
                    help='yfinance period (15m/30m max 60d; 1h max 730d; 1d max)')
    ap.add_argument('--status', action='store_true')
    a = ap.parse_args()
    if a.download:
        print(f'downloading interval={a.interval} period={a.period}')
        download_all(a.interval, a.period)
    if a.status or not a.download:
        if not OUT_DIR.exists():
            print('no cache'); return 0
        print(f'{"file":36}{"bars":>8}  range')
        for p in sorted(OUT_DIR.glob('*.json')):
            try:
                d = json.loads(p.read_text())
                print(f'{p.name:36}{d["count"]:>8,}  {(d.get("first") or "")[:10]} → '
                      f'{(d.get("last") or "")[:10]}')
            except Exception as e:
                print(f'{p.name:36}  ERROR {e}')
    return 0


if __name__ == '__main__':
    sys.exit(_cli())
