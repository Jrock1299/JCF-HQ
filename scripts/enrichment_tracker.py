#!/usr/bin/env python3
"""
enrichment_tracker.py — Weekly analysis: did crypto enrichment data improve win rates?

Runs every Saturday at 08:00 UTC (via cron).
Reads:
  /root/.openclaw/agents/crisp/enrichment_log.csv — Crisp breakout divergence log

Computes:
  - Crisp:  trades blocked by divergence; would-have-been outcomes (if logged)
  - Quota used this week (from enrichment_quota.json daily totals)

Writes a weekly summary to:
  /root/.openclaw/logs/enrichment_weekly_YYYY-WW.json

Prints a human-readable summary to stdout (captured by cron → lens.log or a weekly log).
"""

import csv
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

CRISP_LOG   = Path("/root/.openclaw/agents/crisp/enrichment_log.csv")
QUOTA_LOG   = Path("/root/.openclaw/logs/enrichment_quota.json")
REPORTS_DIR = Path("/root/.openclaw/logs")

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        with open(path) as f:
            return list(csv.DictReader(f))
    except Exception as e:
        log.warning("Could not read %s: %s", path, e)
        return []


def _week_window() -> tuple[datetime, datetime]:
    """Return (start, end) for the past 7 days in UTC."""
    now   = datetime.now(timezone.utc)
    start = now - timedelta(days=7)
    return start, now


def analyze_crisp(rows: list[dict], start: datetime, end: datetime) -> dict:
    """
    Summarise Crisp enrichment rows from the past week.

    Columns: timestamp, strategy, direction, binance_price, aggregated_price,
             divergence_pct, base_score, adjusted_score, trade_taken
    """
    week_rows = []
    for r in rows:
        try:
            ts = datetime.fromisoformat(r["timestamp"])
            if start <= ts <= end:
                week_rows.append(r)
        except Exception:
            continue

    total    = len(week_rows)
    blocked  = [r for r in week_rows if r.get("trade_taken", "True") == "False"]
    passed   = [r for r in week_rows if r.get("trade_taken", "True") == "True"]

    # Compute average divergence for blocked vs passed rows
    def _avg_div(subset: list[dict]) -> str:
        vals = []
        for r in subset:
            try:
                vals.append(float(r["divergence_pct"]))
            except Exception:
                pass
        return f"{sum(vals)/len(vals):.4f}%" if vals else "n/a"

    strategies_blocked: dict[str, int] = {}
    for r in blocked:
        s = r.get("strategy", "unknown")
        strategies_blocked[s] = strategies_blocked.get(s, 0) + 1

    return {
        "total_rows":           total,
        "trades_passed":        len(passed),
        "trades_blocked":       len(blocked),
        "avg_divergence_passed":  _avg_div(passed),
        "avg_divergence_blocked": _avg_div(blocked),
        "strategies_blocked":   strategies_blocked,
    }


def read_quota() -> dict:
    try:
        with open(QUOTA_LOG) as f:
            return json.load(f)
    except Exception:
        return {}


def main() -> None:
    start, end = _week_window()
    week_label = start.strftime("%Y-W%V")

    crisp_rows  = _read_csv(CRISP_LOG)

    crisp_summary  = analyze_crisp(crisp_rows, start, end)
    quota          = read_quota()

    report = {
        "week":          week_label,
        "generated_at":  end.isoformat(timespec="seconds"),
        "quota_today":   quota.get("requests", 0),
        "crisp":         crisp_summary,
    }

    # Write JSON report
    out_path = REPORTS_DIR / f"enrichment_weekly_{week_label}.json"
    try:
        with open(out_path, "w") as f:
            json.dump(report, f, indent=2)
    except Exception as e:
        log.error("Could not write report: %s", e)

    # Human-readable stdout summary
    print(f"\n{'='*60}")
    print(f"ENRICHMENT WEEKLY REPORT — {week_label}")
    print(f"{'='*60}")
    print(f"Quota used today: {quota.get('requests', 0)} / 2000 warn threshold")
    print()
    print("CRISP (breakout validation):")
    print(f"  Total checked:     {crisp_summary['total_rows']}")
    print(f"  Passed:            {crisp_summary['trades_passed']}  avg div: {crisp_summary['avg_divergence_passed']}")
    print(f"  Blocked:           {crisp_summary['trades_blocked']} avg div: {crisp_summary['avg_divergence_blocked']}")
    if crisp_summary["strategies_blocked"]:
        print(f"  Blocked by strat:  {crisp_summary['strategies_blocked']}")
    print()
    print(f"Report saved: {out_path}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
