#!/usr/bin/env python3
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path("/root/.openclaw/workspace")
LOG_PATH = WORKSPACE / "memory" / "weekly_innovation_log.jsonl"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_entries():
    if not LOG_PATH.exists():
        return []
    rows = []
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def append_entry(entry):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=True) + "\n")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Track weekly workflow improvements and ideas."
    )
    parser.add_argument("--status", choices=["completed", "idea"], required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--action", required=True)
    parser.add_argument("--impact", required=True)
    parser.add_argument("--source", default="local")
    parser.add_argument("--owner", default="Huncho")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    entries = load_entries()
    duplicate = any(
        entry.get("title", "").strip().lower() == args.title.strip().lower()
        for entry in entries
    )

    entry = {
        "timestamp_utc": now_iso(),
        "status": args.status,
        "title": args.title.strip(),
        "action": args.action.strip(),
        "impact": args.impact.strip(),
        "source": args.source.strip(),
        "owner": args.owner.strip(),
        "duplicate_title": duplicate,
    }

    if not args.dry_run:
        append_entry(entry)

    print(f"status={entry['status']}")
    print(f"title={entry['title']}")
    print(f"duplicate_title={str(duplicate).lower()}")
    print(f"action={entry['action']}")
    print(f"impact={entry['impact']}")
    print(f"log={LOG_PATH}")


if __name__ == "__main__":
    main()
