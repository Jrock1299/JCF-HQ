#!/usr/bin/env python3
"""ict_data.py — OANDA historical candle fetcher + local cache for ICT research.

Pulls real M15/H1/H4 candles from the OANDA practice API and caches them to
disk so backtests are reproducible and re-runnable without hammering the API.

Bid/ask are fetched alongside mid so spread is measured from the real book
rather than assumed — the backtest charges the actual spread at entry and exit.

    python3 ict_data.py --download          # fetch everything (slow, ~15 min)
    python3 ict_data.py --status            # what is cached
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

AUTH = Path('/root/.openclaw/agents/lens/auth-profiles.json')
CACHE = Path('/root/.openclaw/agents/lens/data/candles')
BASE = 'https://api-fxpractice.oanda.com/v3'

# Blade's book per Jase's brief (SPX500, DE30, XAU). CHF_JPY is included too:
# CLAUDE.md lists it as Blade's third instrument while the brief says XAU, so
# both are tested and the discrepancy is reported rather than silently resolved.
# Edge trades SPX500_USD only.
INSTRUMENTS = ['SPX500_USD', 'DE30_EUR', 'XAU_USD', 'CHF_JPY']
GRANULARITIES = ['M15', 'H1', 'H4']

MAX_PER_REQUEST = 5000
YEARS_BACK = 3


def _key() -> str:
    d = json.loads(AUTH.read_text())['profiles']['oanda:default']
    return d['key']


def _headers() -> dict:
    return {'Authorization': f'Bearer {_key()}'}


def _parse(candles: list) -> list[dict]:
    """OANDA candle -> flat dict. Only COMPLETE candles are kept.

    An incomplete (still-forming) candle is the live equivalent of close[0].
    Including it is how a backtest starts reading the future; it is dropped at
    the source so no downstream code can accidentally use it.
    """
    out = []
    for c in candles:
        if not c.get('complete'):
            continue
        mid = c.get('mid') or {}
        bid = c.get('bid') or {}
        ask = c.get('ask') or {}
        try:
            row = {
                't': c['time'][:19],
                'o': float(mid['o']), 'h': float(mid['h']),
                'l': float(mid['l']), 'c': float(mid['c']),
                'v': int(c.get('volume', 0)),
            }
            if bid and ask:
                row['spread'] = round(float(ask['c']) - float(bid['c']), 6)
            out.append(row)
        except (KeyError, TypeError, ValueError):
            continue
    return out


def fetch(instrument: str, granularity: str, years: int = YEARS_BACK) -> list[dict]:
    """Paginate backwards from now until `years` of history is collected."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=365 * years)
    rows: list[dict] = []
    cursor = start
    H = _headers()

    while cursor < end:
        params = {
            'granularity': granularity,
            'from': cursor.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'count': MAX_PER_REQUEST,
            'price': 'MBA',
        }
        try:
            r = requests.get(f'{BASE}/instruments/{instrument}/candles',
                             headers=H, params=params, timeout=60)
        except Exception as e:
            print(f'    request error: {e}; retrying in 5s')
            time.sleep(5)
            continue
        if r.status_code == 429:
            print('    rate limited; sleeping 20s')
            time.sleep(20)
            continue
        if r.status_code != 200:
            print(f'    HTTP {r.status_code}: {r.text[:140]}')
            break

        batch = _parse(r.json().get('candles', []))
        if not batch:
            break
        rows.extend(batch)
        last = datetime.strptime(batch[-1]['t'], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
        if last <= cursor:
            break
        cursor = last + timedelta(seconds=1)
        time.sleep(0.12)          # be polite to the API

    # de-duplicate on timestamp, keep chronological order
    seen, uniq = set(), []
    for row in rows:
        if row['t'] in seen:
            continue
        seen.add(row['t'])
        uniq.append(row)
    uniq.sort(key=lambda z: z['t'])
    return uniq


def path_for(instrument: str, granularity: str) -> Path:
    return CACHE / f'{instrument}_{granularity}.json'


def load(instrument: str, granularity: str) -> list[dict]:
    p = path_for(instrument, granularity)
    if not p.exists():
        return []
    return json.loads(p.read_text())['candles']


def download_all(instruments=None, granularities=None, years: int = YEARS_BACK) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    for inst in (instruments or INSTRUMENTS):
        for gran in (granularities or GRANULARITIES):
            p = path_for(inst, gran)
            print(f'  {inst} {gran} …', end=' ', flush=True)
            rows = fetch(inst, gran, years)
            if not rows:
                print('NO DATA')
                continue
            p.write_text(json.dumps({
                'instrument': inst, 'granularity': gran,
                'downloaded_at': datetime.now(timezone.utc).isoformat(),
                'source': 'OANDA practice api-fxpractice.oanda.com',
                'count': len(rows),
                'first': rows[0]['t'], 'last': rows[-1]['t'],
                'candles': rows,
            }))
            print(f'{len(rows):,} candles  {rows[0]["t"][:10]} → {rows[-1]["t"][:10]}')


def status() -> None:
    if not CACHE.exists():
        print('no cache')
        return
    print(f'{"file":34}{"candles":>10}  range')
    for p in sorted(CACHE.glob('*.json')):
        d = json.loads(p.read_text())
        print(f'{p.name:34}{d["count"]:>10,}  {d["first"][:10]} → {d["last"][:10]}')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--download', action='store_true')
    ap.add_argument('--status', action='store_true')
    ap.add_argument('--years', type=int, default=YEARS_BACK)
    ap.add_argument('--instrument')
    ap.add_argument('--granularity')
    a = ap.parse_args()
    if a.download:
        download_all([a.instrument] if a.instrument else None,
                     [a.granularity] if a.granularity else None,
                     a.years)
    if a.status or not a.download:
        status()
    return 0


if __name__ == '__main__':
    sys.exit(main())
