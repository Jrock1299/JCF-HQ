#!/usr/bin/env python3
"""
blade_learning_analyzer.py — PHASE 1 PLACEHOLDER (NOT ACTIVE)

This script is a stub for future analysis of blade_learning_log.json.

PHASE 1 (current): Observation only. Blade logs every trade's team context
                   (regime, lens bias, alignment, ORB structure) without
                   acting on it. This script is NOT yet wired into cron.

PHASE 2 (future, gated by Norman validation):
  - Compute win-rate / R-multiple / expectancy split by:
      * regime_at_entry (trending/ranging/compressed/volatile)
      * strategist_aligned (True/False)
      * lens_bias_at_entry vs trade direction
      * orb_range_pts (tight vs wide ORB)
      * breakout_distance_pts (clean vs marginal break)
      * session × instrument
  - Output a structured JSON report Norman can consume to validate that
    any observed edge is statistically real (≥ 30 closed trades per
    bucket, Monte Carlo p5 > 0) before any self-gating is enabled.
  - Only after Norman returns PASS on a candidate pattern does a separate
    PR enable that pattern as a soft filter or sizing modifier in Blade.

USAGE WHEN PHASE 2 ACTIVATES:
  python3 blade_learning_analyzer.py            # full report to stdout
  python3 blade_learning_analyzer.py --json     # JSON output for Norman
  python3 blade_learning_analyzer.py --min-n 30 # bucket-size threshold

For now, running this script just reports how many records are accumulated
so we can track when there is enough data to begin Phase 2 analysis.
"""

import json
import sys
from pathlib import Path

LEARNING_LOG = Path('/root/.openclaw/dashboard/blade_learning_log.json')
PHASE_2_MIN_RECORDS = 100  # absolute floor before any analysis is even meaningful


def main():
    if not LEARNING_LOG.exists():
        print(f"[blade-learning] log not yet created: {LEARNING_LOG}")
        print("                 Blade writes to this file as trades close. Phase 1 ongoing.")
        return 0

    try:
        with open(LEARNING_LOG) as f:
            store = json.load(f)
    except Exception as e:
        print(f"[blade-learning] could not read log: {e}")
        return 1

    records = store.get('records', [])
    n = len(records)
    print(f"[blade-learning] records: {n}")
    print(f"                 Phase 2 minimum: {PHASE_2_MIN_RECORDS}")

    if n < PHASE_2_MIN_RECORDS:
        print(f"                 Not enough data yet — Phase 1 (observation) continues.")
        return 0

    # ── Phase 2 analysis is gated by an explicit flag we have not set yet ────
    print(f"                 Threshold met. Phase 2 analysis is GATED behind an")
    print(f"                 explicit enable flag and Norman validation. No analysis")
    print(f"                 will run from this stub. To proceed:")
    print(f"                   1. Replace this stub with the analysis implementation.")
    print(f"                   2. Run Norman on the resulting buckets.")
    print(f"                   3. Open a PR that wires accepted patterns into Blade")
    print(f"                      as soft filters or sizing modifiers.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
