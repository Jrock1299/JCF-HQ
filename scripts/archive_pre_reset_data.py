#!/usr/bin/env python3
"""Archive and tombstone the corrupted pre-reset trading history.

Jase, 2026-07-27: "archive/wipe the corrupted pre-reset history (Blade's 330
phantom TradeLocker trades, Crisp's 468% drawdown data) so nothing downstream
can read it again. Clean slate from today."

What is corrupt and why:

  dashboard/tradelocker_trades.json
      330 trades, newest close 2026-05-27, from the broker Blade no longer
      uses (Blade migrated to OANDA). The */30 sync kept rewriting `last_sync`
      so the file looked live while the payload sat two months dormant — the
      exact "file mtime is not freshness" trap in CLAUDE.md Rule #9. Norman
      graded these 330 dormant trades as "Blade" for two months, and Victoria
      relayed it to Jase's phone as "BLADE FAIL: 330 trades".
      Its win_rate field was also wrong twice over: stored as the STRING
      "53.3%" (so numeric consumers coerce it to 0.0 — the 0.0% win-rate bug
      Victoria flagged herself), and 53.3 is not 176/(176+139) = 55.87%.

  dashboard/norman_report.json
      Written 2026-07-25 by an agent retired the same day. Holds the phantom
      Blade grade above plus a 468.0% max drawdown for "crisp" — a figure that
      is impossible as a drawdown percentage and signals an equity-accounting
      failure, not a trading result. That 6-trade dataset is Chad's (internal
      id `crisp`, display name Chad) and is 104 days stale.

Neither file is deleted — both move to _archive/ and are replaced by a
tombstone carrying explicit quarantine markers and NO numbers. Consumers
(blade_bot, edge_main, jerry_context, phantom_config, hq_storage_server, the
React app) all read `agent_reports.<agent>.verdict` with an 'UNKNOWN' default
and `monte_carlo.ruin_probability` with a None default, so an empty
`agent_reports` degrades them to UNKNOWN instead of a phantom verdict.

Idempotent: re-running detects an existing tombstone and does nothing.

  --apply   perform the move (default is a dry run)
"""
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

DASHBOARD = Path('/root/.openclaw/dashboard')
ARCHIVE = DASHBOARD / '_archive' / 'pre_reset_2026-07-27'
APPLY = '--apply' in sys.argv
NOW = datetime.now(timezone.utc).isoformat()

TOMBSTONES = {
    'norman_report.json': {
        'date': None,
        'agent_reports': {},
        'portfolio_summary': {},
        'recommendations': [],
        'alerts': [],
        '_QUARANTINED': True,
        '_quarantined_at': NOW,
        '_reason': (
            'Written 2026-07-25 by Norman, retired the same day. Contained a '
            'phantom Blade grade off 330 dormant TradeLocker trades and an '
            'impossible 468.0% max drawdown for Chad (internal id `crisp`). '
            'Quarantined 2026-07-27 at Jase\'s direction.'
        ),
        '_superseded_by': [
            'dashboard/lens_validation.json (Blade, Edge)',
            'dashboard/victoria_validation.json (Jerry, Chad)',
        ],
        '_archived_original': str(ARCHIVE / 'norman_report.json'),
        '_read_this_instead': (
            'Empty agent_reports is deliberate. Consumers default to '
            'verdict=UNKNOWN / ruin_probability=None, which is the correct '
            'state: no current validation exists until the Sunday validators '
            'run. Do not backfill this file.'
        ),
    },
    'tradelocker_trades.json': {
        'balance': None,
        'pnl': None,
        'wins': None,
        'losses': None,
        'win_rate': None,
        'last_sync': None,
        'trades': [],
        '_QUARANTINED': True,
        '_quarantined_at': NOW,
        '_reason': (
            '330 trades from a broker Blade no longer uses; newest close '
            '2026-05-27. The */30 sync refreshed `last_sync` so the file '
            'looked live while the payload sat dormant for two months. '
            'Blade trades on OANDA and writes to agent_trades.json. '
            'Quarantined 2026-07-27 at Jase\'s direction.'
        ),
        '_superseded_by': ['dashboard/agent_trades.json (agent="blade")'],
        '_archived_original': str(ARCHIVE / 'tradelocker_trades.json'),
        '_read_this_instead': (
            'Empty trades + null aggregates are deliberate. Blade has no '
            'gradeable post-reset history; validators must report NO_DATA '
            'rather than grading this feed. The sync cron line is held.'
        ),
    },
}


def main() -> int:
    print(f'{"APPLYING" if APPLY else "DRY RUN"} — pre-reset data quarantine\n')
    planned = []

    for name, tomb in TOMBSTONES.items():
        src = DASHBOARD / name
        if not src.exists():
            print(f'  SKIP    {name} — not present')
            continue
        try:
            current = json.loads(src.read_text())
        except Exception as e:
            print(f'  WARN    {name} — unreadable ({e}); archiving as-is')
            current = None

        if isinstance(current, dict) and current.get('_QUARANTINED'):
            print(f'  SKIP    {name} — already quarantined')
            continue

        if isinstance(current, dict):
            n = len(current.get('trades', []) or current.get('agent_reports', {}) or {})
            detail = f'{n} records'
        else:
            detail = 'unparsed'
        print(f'  ARCHIVE {name} ({detail}) -> _archive/pre_reset_2026-07-27/')
        print(f'  TOMB    {name} -> quarantine tombstone')
        planned.append((src, tomb))

    if not planned:
        print('\nNothing to do.')
        return 0

    if not APPLY:
        print('\n(dry run — re-run with --apply)')
        return 0

    ARCHIVE.mkdir(parents=True, exist_ok=True)
    for src, tomb in planned:
        shutil.copy2(src, ARCHIVE / src.name)
        src.write_text(json.dumps(tomb, indent=2))
        print(f'  done: {src.name}')

    readme = ARCHIVE / 'README.md'
    readme.write_text(f"""# Pre-reset data archive — 2026-07-27

Corrupted trading history, quarantined at Jase's direction. **Read-only
evidence. Nothing in production may read these files.**

Archived {NOW}.

| File | What was wrong |
|---|---|
| `tradelocker_trades.json` | 330 trades from a broker Blade no longer uses (newest close 2026-05-27). The `*/30` sync refreshed `last_sync` so it looked live while the payload sat dormant two months. Graded as "Blade" for two months. `win_rate` stored as the string `"53.3%"` — wrong value (176W/139L = 55.87%) and a string, so numeric consumers coerced it to 0.0. |
| `norman_report.json` | Written 2026-07-25 by an agent retired the same day. Phantom Blade grade off the 330 dormant trades; impossible 468.0% max drawdown for Chad (internal id `crisp`), which signals an equity-accounting failure, not a trading result. |

Both were replaced in `dashboard/` by tombstones carrying `_QUARANTINED: true`
and **no numbers**. Consumers default to `verdict=UNKNOWN` /
`ruin_probability=None`, which is the honest state.

Superseded by:
- `dashboard/lens_validation.json` — Blade, Edge
- `dashboard/victoria_validation.json` — Jerry, Chad

The TradeLocker sync cron line is **held**; un-holding it would repopulate the
quarantined file within 30 minutes.
""")
    print(f'\nArchived to {ARCHIVE}')
    print(f'README written: {readme}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
