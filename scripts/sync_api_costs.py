#!/usr/bin/env python3
"""
sync_api_costs.py — aggregate per-agent API cost logs into dashboard/api_costs.json.

Reads /root/.openclaw/logs/<agent>_api_costs.json (entries: {date, timestamp,
input_tokens, output_tokens, cost_usd, ...}) and emits one JSON the HQ React
app renders in the API Usage & Cost card.

Honesty rules (per the card spec):
- month_usd sums are REAL logged dollars only — Codex-routed runs log
  cost_usd 0.0 and therefore contribute nothing. Nothing is fabricated.
- Agents with no LLM calls at all (Blade/Edge/Tao) are billing "none", so the
  UI can say "No AI cost" instead of a misleading $0.
- ceiling_usd is user-editable in the UI (universal /hq/edit pattern) and is
  PRESERVED across rewrites of this file.

Cron: hourly. Manual: python3 scripts/sync_api_costs.py
"""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOGS = Path('/root/.openclaw/logs')
OUT = Path('/root/.openclaw/dashboard/api_costs.json')
DEFAULT_CEILING = 50.0
TREND_DAYS = 30

# Fleet roster: app agent id -> (cost-log stem or None, billing route today).
# billing: "metered" = real per-call dollars (Anthropic SDK) ·
#          "codex"   = included in the Codex subscription ($0 marginal) ·
#          "none"    = no LLM calls at runtime (pure algorithmic / scripts).
# Routing source of truth: CLAUDE.md §4d (Lens is the only Anthropic-billed
# cron agent since the 2026-07-24 Codex migration).
ROSTER = {
    'huncho':   (None,       'codex'),
    'lens':     ('lens',     'metered'),
    'blade':    (None,       'none'),
    'jerry':    ('jerry',    'codex'),
    'jarvis':   (None,       'codex'),
    'victoria': ('victoria', 'codex'),
    'norman':   ('norman',   'codex'),
    'lucy':     ('lucy',     'codex'),
    'tao':      (None,       'none'),
    'edge':     (None,       'none'),
    'phantom':  ('phantom',  'codex'),
    'crisp':    ('crisp',    'codex'),
}

# Shown under the name when an agent has real in-month spend but is now
# subscription-covered (they were Anthropic-billed until the migration).
MIGRATION_NOTE = 'Anthropic-billed until Jul 24'
MIGRATED = {'jerry', 'victoria', 'norman', 'lucy'}


def load_log(stem):
    p = LOGS / f'{stem}_api_costs.json'
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def main():
    now = datetime.now(timezone.utc)
    this_month = now.strftime('%Y-%m')
    prev_month = (now.replace(day=1) - timedelta(days=1)).strftime('%Y-%m')

    # Preserve the user-edited ceiling across rewrites.
    ceiling = DEFAULT_CEILING
    try:
        prev = json.loads(OUT.read_text())
        c = prev.get('ceiling_usd')
        if isinstance(c, (int, float)) and c > 0:
            ceiling = float(c)
    except Exception:
        pass

    daily = {}  # date -> usd (all real spend, fleet-wide)
    agents = []
    for aid, (stem, billing) in ROSTER.items():
        entries = load_log(stem) if stem else []
        month_usd = prev_usd = total_usd = 0.0
        last_activity = None
        for e in entries:
            cost = float(e.get('cost_usd') or 0)
            d = str(e.get('date') or '')[:10]
            total_usd += cost
            if d[:7] == this_month:
                month_usd += cost
            elif d[:7] == prev_month:
                prev_usd += cost
            if cost > 0 and d:
                daily[d] = daily.get(d, 0.0) + cost
            ts = e.get('timestamp') or d
            if ts and (last_activity is None or ts > last_activity):
                last_activity = ts
        agents.append({
            'id': aid,
            'billing': billing,
            'month_usd': round(month_usd, 4),
            'prev_month_usd': round(prev_usd, 4),
            'total_usd': round(total_usd, 4),
            'last_activity': last_activity,
            'has_log': bool(entries),
            'note': MIGRATION_NOTE if (aid in MIGRATED and month_usd > 0) else None,
        })

    # 30-day daily trend, zero-filled so the sparkline has an honest baseline.
    trend = []
    for i in range(TREND_DAYS - 1, -1, -1):
        d = (now - timedelta(days=i)).strftime('%Y-%m-%d')
        trend.append({'date': d, 'usd': round(daily.get(d, 0.0), 4)})

    month_total = round(sum(a['month_usd'] for a in agents), 4)
    prev_total = round(sum(a['prev_month_usd'] for a in agents), 4)

    payload = {
        'updated': now.isoformat(),
        'month': this_month,
        'ceiling_usd': ceiling,
        'month_total_usd': month_total,
        'prev_month_total_usd': prev_total,
        'daily': trend,
        'agents': agents,
    }
    OUT.write_text(json.dumps(payload, indent=2))
    print(f'[api-costs] {this_month} total ${month_total} '
          f'(prev ${prev_total}) ceiling ${ceiling} -> {OUT}')


if __name__ == '__main__':
    main()
