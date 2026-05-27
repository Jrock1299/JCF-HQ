#!/usr/bin/env python3
"""
oracle_migrate.py — One-shot migration to the new Oracle schema.

Adds `status` field to every pick in oracle_resolved.json:
  - status='pending' for picks within 7 days that are still 'pending'
  - status='stale'   for picks >7 days old still 'pending'
  - status='resolved' for picks already graded (win/loss/push, W/L/P)

Normalises legacy result vocabulary to the new uppercase WIN/LOSS/PUSH and
preserves all original fields. Idempotent — re-runnable.
"""

import json
from datetime import datetime, timezone, timedelta

PATH = '/root/.openclaw/dashboard/oracle_resolved.json'
STALE_THRESHOLD_DAYS = 7

RESULT_NORMALISE = {
    'win':  'WIN',  'W': 'WIN',
    'loss': 'LOSS', 'L': 'LOSS',
    'push': 'PUSH', 'P': 'PUSH',
}


def parse_pick_date(p):
    """Best-effort UTC datetime from a pick's date/commence/logged_at."""
    for k in ('date', 'commence', 'logged_at', 'created_at'):
        v = p.get(k)
        if not v:
            continue
        try:
            return datetime.fromisoformat(str(v).replace('Z', '+00:00')).astimezone(timezone.utc)
        except Exception:
            continue
    return None


def main():
    with open(PATH) as f:
        data = json.load(f)

    picks = data.get('picks', [])
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=STALE_THRESHOLD_DAYS)

    counts = {'stale_marked': 0, 'pending_kept': 0, 'resolved_normalised': 0,
              'no_date_stale': 0, 'unchanged': 0, 'total': len(picks)}

    for p in picks:
        legacy_result = (p.get('result') or '').strip()
        existing_status = p.get('status')

        if legacy_result.lower() == 'pending' or legacy_result.upper() == 'PENDING' or not legacy_result:
            dt = parse_pick_date(p)
            if dt is None:
                p['status'] = 'stale'
                counts['no_date_stale'] += 1
            elif dt < cutoff:
                p['status'] = 'stale'
                counts['stale_marked'] += 1
            else:
                p['status'] = 'pending'
                counts['pending_kept'] += 1
        elif legacy_result in RESULT_NORMALISE:
            p['status'] = 'resolved'
            p['result'] = RESULT_NORMALISE[legacy_result]
            counts['resolved_normalised'] += 1
        else:
            counts['unchanged'] += 1
            if existing_status is None:
                p['status'] = 'unknown'

    data['picks'] = picks
    data['migrated_at'] = now.isoformat()
    data['schema_version'] = 2

    with open(PATH, 'w') as f:
        json.dump(data, f, indent=2)

    print('=== Oracle migration complete ===')
    for k, v in counts.items():
        print(f'  {k:22s}: {v}')


if __name__ == '__main__':
    main()
