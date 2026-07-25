"""
Shared data-freshness / staleness detection.

THE PATTERN THIS EXISTS TO KILL
-------------------------------
A data source fails or freezes. The caller catches the exception and
substitutes a last-known value. Every downstream consumer then renders that
value as current, with no indicator that it is months old.

Two real instances that motivated this module:

  * tao_compounder.check_emissions() caught the bittensor API error and
    returned `stored_root` — so "Root Stake 0.000000" (an April 15 snapshot)
    printed in the weekly report as a live number.
  * norman_brain graded 330 TradeLocker trades whose newest record closed
    2026-05-27, presenting a two-month-old dead broker feed as Blade's
    current performance.

THE RULE
--------
A value that could not be refreshed is returned WITH its provenance, never
bare. Renderers mark it. Graders refuse it.

CRITICAL: file mtime is NOT freshness.
--------------------------------------
`tao_portfolio.json` is rewritten every run (mtime = today) while its
`updated` field still reads 2026-04-15. A mtime check would call it fresh.
`from_file()` therefore prefers an embedded timestamp field and only falls
back to mtime when no such field exists — and says which it used.

Usage
-----
    from data_freshness import Freshness, from_file, from_records, call_failed

    fr = from_file('/path/portfolio.json', ts_fields=('updated',))
    if fr.stale:
        print(fr.marker())          # "⚠️ STALE — last updated Apr 15, 2026 (101d ago)"
    print(fr.annotate("0.000000 τ"))  # value + marker, one call
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Default tolerance. Callers with a known cadence should pass their own:
# a 3x-daily collector is stale after hours, not weeks.
DEFAULT_STALE_AFTER_DAYS = 14

# Timestamp field names seen across JCF HQ data files, in preference order.
COMMON_TS_FIELDS = (
    "updated", "last_updated", "updated_at",
    "last_sync", "synced_at", "scored_at",
    "generated_at", "timestamp", "date",
)

# Per-record timestamp keys, in preference order (close before open: we care
# when the record reached its final state).
COMMON_RECORD_TS_FIELDS = (
    "close_date", "closed_at", "exit_time",
    "timestamp", "date", "open_date", "entry_time",
)


def _parse_ts(value) -> datetime | None:
    """Best-effort parse of the timestamp shapes used across HQ data files."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        # Heuristic: ms epochs are ~1e12, s epochs ~1e9.
        try:
            seconds = value / 1000.0 if value > 1e11 else float(value)
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%d %b %Y"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


@dataclass
class Freshness:
    """Provenance for a single value or data source.

    `ok` means: we have a timestamp and it is within tolerance. Anything
    else — missing file, unparseable, live call failed, too old — is not ok
    and must be surfaced, not silently substituted.
    """

    source: str
    ok: bool
    reason: str                       # fresh|stale|missing|unreadable|no_timestamp|call_failed|empty
    as_of: datetime | None = None
    stale_after_days: float = DEFAULT_STALE_AFTER_DAYS
    detail: str = ""
    basis: str = ""                   # which field/mechanism produced as_of
    meta: dict = field(default_factory=dict)

    # ---- derived -----------------------------------------------------------

    @property
    def stale(self) -> bool:
        return not self.ok

    @property
    def age_days(self) -> float | None:
        if self.as_of is None:
            return None
        return (datetime.now(timezone.utc) - self.as_of).total_seconds() / 86400.0

    def as_of_str(self) -> str:
        if self.as_of is None:
            return "unknown"
        return self.as_of.strftime("%b %-d, %Y")

    # ---- rendering ---------------------------------------------------------

    def marker(self) -> str:
        """Short inline marker. Empty string when fresh — safe to concatenate."""
        if self.ok:
            return ""
        if self.reason == "missing":
            return "⚠️ NO DATA — source missing"
        if self.reason == "unreadable":
            return "⚠️ NO DATA — source unreadable"
        if self.reason == "empty":
            return "⚠️ NO DATA — source empty"
        if self.reason == "no_timestamp":
            return "⚠️ UNKNOWN AGE — source carries no timestamp"
        if self.reason == "call_failed":
            base = "⚠️ STALE — live call failed"
            if self.as_of is not None:
                base += f", last updated {self.as_of_str()} ({self.age_days:.0f}d ago)"
            return base
        if self.reason == "contradicted":
            return "⚠️ UNVERIFIED — live source contradicts recorded history"
        age = f" ({self.age_days:.0f}d ago)" if self.age_days is not None else ""
        return f"⚠️ STALE — last updated {self.as_of_str()}{age}"

    def annotate(self, value: str) -> str:
        """Render a value with its staleness marker appended when not fresh."""
        m = self.marker()
        return f"{value}  {m}" if m else str(value)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "ok": self.ok,
            "reason": self.reason,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "age_days": round(self.age_days, 2) if self.age_days is not None else None,
            "stale_after_days": self.stale_after_days,
            "basis": self.basis,
            "detail": self.detail,
            "marker": self.marker(),
        }


# ---------------------------------------------------------------------------
# Constructors
# ---------------------------------------------------------------------------

def from_timestamp(source: str, ts, stale_after_days: float = DEFAULT_STALE_AFTER_DAYS,
                   basis: str = "timestamp") -> Freshness:
    dt = _parse_ts(ts)
    if dt is None:
        return Freshness(source=source, ok=False, reason="no_timestamp",
                         stale_after_days=stale_after_days, basis=basis)
    age = (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
    return Freshness(source=source, ok=age <= stale_after_days,
                     reason="fresh" if age <= stale_after_days else "stale",
                     as_of=dt, stale_after_days=stale_after_days, basis=basis)


def from_file(path, stale_after_days: float = DEFAULT_STALE_AFTER_DAYS,
              ts_fields: tuple = COMMON_TS_FIELDS,
              allow_mtime_fallback: bool = True) -> Freshness:
    """Freshness of a JSON data file.

    Prefers an embedded timestamp field over mtime, because a file can be
    rewritten every run while its payload stays frozen (tao_portfolio.json
    does exactly this). Falls back to mtime only when no field is found, and
    records which basis was used so the caller can tell the difference.
    """
    p = Path(path)
    if not p.exists():
        return Freshness(source=str(p), ok=False, reason="missing",
                         stale_after_days=stale_after_days)
    try:
        with open(p) as f:
            data = json.load(f)
    except Exception as e:
        return Freshness(source=str(p), ok=False, reason="unreadable",
                         stale_after_days=stale_after_days, detail=str(e))

    if isinstance(data, dict):
        for fname in ts_fields:
            if fname in data:
                fr = from_timestamp(str(p), data[fname], stale_after_days,
                                    basis=f"field:{fname}")
                if fr.as_of is not None:
                    return fr

    if not allow_mtime_fallback:
        return Freshness(source=str(p), ok=False, reason="no_timestamp",
                         stale_after_days=stale_after_days)

    mtime = datetime.fromtimestamp(os.path.getmtime(p), tz=timezone.utc)
    fr = from_timestamp(str(p), mtime, stale_after_days, basis="file_mtime")
    fr.detail = "no embedded timestamp field; used file mtime"
    return fr


def from_records(source: str, records: list, stale_after_days: float = DEFAULT_STALE_AFTER_DAYS,
                 ts_fields: tuple = COMMON_RECORD_TS_FIELDS) -> Freshness:
    """Freshness of a record collection, judged by its NEWEST record.

    This is the right check for trade histories: the file may be rewritten
    constantly by a sync job while no new trades have actually arrived.
    """
    if not records:
        return Freshness(source=source, ok=False, reason="empty",
                         stale_after_days=stale_after_days,
                         meta={"record_count": 0})

    newest = None
    used_field = None
    for rec in records:
        if not isinstance(rec, dict):
            continue
        for fname in ts_fields:
            dt = _parse_ts(rec.get(fname))
            if dt is not None:
                if newest is None or dt > newest:
                    newest, used_field = dt, fname
                break

    if newest is None:
        return Freshness(source=source, ok=False, reason="no_timestamp",
                         stale_after_days=stale_after_days,
                         meta={"record_count": len(records)})

    fr = from_timestamp(source, newest, stale_after_days,
                        basis=f"newest_record:{used_field}")
    fr.meta = {"record_count": len(records)}
    return fr


def call_failed(source: str, error: Exception | str,
                fallback_as_of=None,
                stale_after_days: float = DEFAULT_STALE_AFTER_DAYS) -> Freshness:
    """A live call threw and the caller is falling back to a stored value.

    Always not-ok, regardless of how recent the fallback is: the point is
    that we did NOT refresh, and the consumer must be told.
    """
    return Freshness(source=source, ok=False, reason="call_failed",
                     as_of=_parse_ts(fallback_as_of),
                     stale_after_days=stale_after_days,
                     detail=str(error), basis="fallback_to_stored")


def contradicted(source: str, detail: str,
                 stale_after_days: float = DEFAULT_STALE_AFTER_DAYS) -> Freshness:
    """A live call succeeded but returned something recorded history disproves.

    The distinct case from `call_failed`: nothing threw, so a naive caller
    would treat the result as authoritative. An empty stake list from a wallet
    whose own history records stake is not a verified zero — it is an unknown,
    and must render as one.
    """
    return Freshness(source=source, ok=False, reason="contradicted",
                     stale_after_days=stale_after_days,
                     detail=detail, basis="live_call_contradicted")


def summarize(freshnesses: dict) -> dict:
    """Roll up a {label: Freshness} map for report headers/JSON payloads."""
    stale = {k: v for k, v in freshnesses.items() if v.stale}
    return {
        "all_fresh": not stale,
        "stale_count": len(stale),
        "total": len(freshnesses),
        "stale_labels": sorted(stale.keys()),
        "detail": {k: v.to_dict() for k, v in freshnesses.items()},
    }


def banner(freshnesses: dict, title: str = "DATA FRESHNESS") -> str:
    """Multi-line warning block listing every stale source. '' when all fresh."""
    stale = {k: v for k, v in freshnesses.items() if v.stale}
    if not stale:
        return ""
    lines = [f"⚠️  {title} — {len(stale)} of {len(freshnesses)} sources not current:"]
    for label, fr in sorted(stale.items()):
        lines.append(f"   • {label}: {fr.marker()}")
    return "\n".join(lines)
