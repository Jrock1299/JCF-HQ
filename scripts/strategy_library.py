#!/usr/bin/env python3
"""strategy_library.py — the one shared reader for dashboard/strategy_library.json.

Written 2026-07-28 as the distribution surface between Lens/Victoria (writers)
and Blade/Edge/Jerry/Chad (readers). Design principles, in order of importance:

1. **One reader, many consumers.** No agent parses the JSON directly. Any
   change to library schema is a single edit here, and every consumer picks it
   up. Same anti-drift principle as `risk_validation.py`.

2. **Read-only from a consumer.** The methods here return copies, never
   references into the loaded dict. A consumer cannot silently mutate the
   library and have it re-serialised. Writers (`ict_research.py`,
   `victoria_validator.py`) build the dict and call `write_library()`.

3. **Deployable is the only gate.** A consumer that iterates results MUST
   filter by `entry['deployable']` — the not_validated list exists for the
   record, not for trading. `iter_deployable(...)` is the safe accessor.

4. **Change detection via content_hash.** Every entry carries a
   `content_hash` over the decision-surface fields (rules, execution,
   params, verdict). A consumer can persist the last hash it saw for a given
   `id` and detect updates without diff-ing the whole entry. `subscribe_to()`
   returns a change record.

5. **A missing library is not a crash.** `load()` returns an empty index if
   the file is missing or malformed. Consumers see zero deployable entries
   and idle rather than trading blindly on a stale in-memory copy.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional


DEFAULT_PATH = Path('/root/.openclaw/dashboard/strategy_library.json')

# Where consumers persist their last-seen content_hash per entry id. Kept
# per-agent so two agents subscribing to the same strategy don't clobber
# each other's cursor.
CURSOR_DIR = Path('/root/.openclaw/dashboard/_library_cursors')

# Which asset_class ↔ agent mapping. A consumer passes its own agent_name
# and gets back only entries relevant to it. Deliberately conservative —
# an unknown asset_class won't be routed to any agent until it's added here.
AGENT_ASSET_CLASSES = {
    'blade':   {'cfd_index_metal_fx'},
    'edge':    {'cfd_index_metal_fx'},
    'jerry':   {'equity', 'options', 'crypto_spot'},
    'chad':    {'crypto_meme'},
}


def load(path: Path | str = DEFAULT_PATH) -> dict:
    """Load the library. Empty structured dict on any read failure — no
    consumer should ever crash because the writer had a bad day."""
    p = Path(path)
    empty = {
        'schema': 'jcf.strategy_library/v1',
        'updated_at': None,
        'validated': [],
        'not_validated': [],
        '_load_status': 'missing',
    }
    if not p.exists():
        return empty
    try:
        d = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        empty['_load_status'] = 'unreadable'
        return empty
    d.setdefault('_load_status', 'ok')
    return d


def iter_deployable(path: Path | str = DEFAULT_PATH,
                    agent: Optional[str] = None,
                    instrument: Optional[str] = None,
                    strategy: Optional[str] = None) -> Iterator[dict]:
    """Yield deep-copies of every validated + deployable entry, optionally
    filtered by agent (via AGENT_ASSET_CLASSES), instrument, or strategy.

    Deep-copies: a consumer that mutates the returned dict cannot corrupt
    a cached load elsewhere in the process.
    """
    d = load(path)
    allowed_classes = AGENT_ASSET_CLASSES.get(agent) if agent else None
    for e in d.get('validated', []):
        if not e.get('deployable'):
            continue
        if allowed_classes is not None and e.get('asset_class') not in allowed_classes:
            continue
        if instrument and e.get('instrument') != instrument:
            continue
        if strategy and e.get('strategy') != strategy:
            continue
        yield copy.deepcopy(e)


def get_for_instrument(instrument: str,
                       agent: Optional[str] = None,
                       path: Path | str = DEFAULT_PATH) -> Optional[dict]:
    """Return the single deployable entry for an instrument, or None. If more
    than one deployable strategy exists for the same instrument (a future
    reality once we add the plain sweep-fade baseline as its own entry), the
    caller must be explicit — this helper is intentionally not smart about
    picking one for you."""
    hits = list(iter_deployable(path, agent=agent, instrument=instrument))
    if len(hits) > 1:
        ids = [h['id'] for h in hits]
        raise ValueError(
            f'multiple deployable strategies for {instrument} ({ids}); '
            f'caller must pick one explicitly via strategy= filter.'
        )
    return hits[0] if hits else None


def instruments_covered(agent: Optional[str] = None,
                        path: Path | str = DEFAULT_PATH) -> list:
    """List of instruments that have at least one deployable strategy for a
    given agent. Useful for an agent to know 'am I trading anything?'"""
    seen = set()
    for e in iter_deployable(path, agent=agent):
        seen.add(e['instrument'])
    return sorted(seen)


def cursor_path(agent: str) -> Path:
    return CURSOR_DIR / f'{agent}.json'


def _load_cursor(agent: str) -> dict:
    p = cursor_path(agent)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cursor(agent: str, cursor: dict) -> None:
    CURSOR_DIR.mkdir(parents=True, exist_ok=True)
    tmp = cursor_path(agent).with_suffix('.tmp')
    tmp.write_text(json.dumps(cursor, indent=2, default=str))
    os.replace(tmp, cursor_path(agent))


def subscribe_to(agent: str,
                 path: Path | str = DEFAULT_PATH,
                 mark_seen: bool = True) -> dict:
    """Return the CHANGE SET since this agent last called subscribe_to().

    Returns:
        {
          'new':        [entry, ...]     # entries not in agent's cursor
          'updated':    [{'id', 'old_hash', 'new_hash', 'entry'}, ...]
          'unchanged':  [entry, ...]     # id + hash match
          'gone':       [id, ...]        # were in cursor, now missing/undeployable
        }

    If mark_seen is True (default), the cursor is updated so the next call
    only surfaces the delta. A subscriber that wants to peek without
    committing passes mark_seen=False.

    Why bother: "Versioned — updates propagate to consumers, logged, never
    silently mutate a running strategy" from the deploy brief. A consumer
    reads the delta, decides whether to hot-swap or defer to the next
    session boundary, and logs the transition. No consumer silently picks
    up a mutated params dict mid-position.
    """
    cursor = _load_cursor(agent)
    seen_hashes = {eid: c.get('content_hash') for eid, c in cursor.items()}
    seen_ids = set(seen_hashes)

    new, updated, unchanged = [], [], []
    current_ids = set()
    for e in iter_deployable(path, agent=agent):
        eid = e['id']; h = e.get('content_hash')
        current_ids.add(eid)
        if eid not in seen_ids:
            new.append(e)
        elif seen_hashes.get(eid) != h:
            updated.append({'id': eid, 'old_hash': seen_hashes.get(eid),
                            'new_hash': h, 'entry': e})
        else:
            unchanged.append(e)

    gone = sorted(seen_ids - current_ids)

    if mark_seen:
        new_cursor = {e['id']: {
            'content_hash': e.get('content_hash'),
            'seen_at': datetime.now(timezone.utc).isoformat(),
            'version': e.get('version'),
        } for e in (new + updated_entries(updated) + unchanged)}
        # Note: entries in `gone` are dropped from the cursor. A consumer
        # tracking exit-only positions on a de-listed strategy is expected
        # to close them, not carry a phantom cursor entry.
        _save_cursor(agent, new_cursor)
        logging.info(f'[library] {agent} subscribed: new={len(new)} updated={len(updated)} '
                     f'unchanged={len(unchanged)} gone={len(gone)}')

    return {'new': new, 'updated': updated, 'unchanged': unchanged, 'gone': gone}


def updated_entries(updated: list) -> list:
    return [u['entry'] for u in updated]


def compute_content_hash(entry: dict) -> str:
    """Recompute the content_hash for an entry. Used by writers that assemble
    the entry outside ict_research.py — same recipe so hashes are comparable
    across writers."""
    surface = {
        'rules':      entry.get('rules'),
        'execution':  entry.get('execution'),
        'params':     entry.get('params'),
        'verdict':    entry.get('verdict'),
        'deployable': entry.get('deployable'),
        'strategy':   entry.get('strategy'),
        'instrument': entry.get('instrument'),
    }
    return hashlib.sha1(
        json.dumps(surface, sort_keys=True, default=str).encode()
    ).hexdigest()[:12]


# ── CLI ─────────────────────────────────────────────────────────────────────

def _cli() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--agent', help='filter by agent (blade/edge/jerry/chad)')
    ap.add_argument('--instrument')
    ap.add_argument('--strategy')
    ap.add_argument('--list', action='store_true', help='list deployable entries')
    ap.add_argument('--covered', action='store_true',
                    help='list instruments with at least one deployable strategy')
    ap.add_argument('--subscribe', metavar='AGENT',
                    help='dry-run: peek at change set for AGENT (does not mark seen)')
    args = ap.parse_args()

    if args.covered:
        for i in instruments_covered(agent=args.agent):
            print(i)
        return 0

    if args.subscribe:
        chg = subscribe_to(args.subscribe, mark_seen=False)
        print(f'new={len(chg["new"])}  updated={len(chg["updated"])}  '
              f'unchanged={len(chg["unchanged"])}  gone={len(chg["gone"])}')
        for e in chg['new']: print(f'  NEW      {e["id"]:40} hash={e.get("content_hash")}')
        for u in chg['updated']:
            print(f'  UPDATED  {u["id"]:40} {u["old_hash"]} -> {u["new_hash"]}')
        for gid in chg['gone']: print(f'  GONE     {gid}')
        return 0

    if args.list or not any([args.covered, args.subscribe]):
        for e in iter_deployable(agent=args.agent,
                                 instrument=args.instrument,
                                 strategy=args.strategy):
            s = e.get('stats', {}) or {}
            print(f'{e["id"]:40}  {e["asset_class"]:20}  {e["timeframe"]:>4}  '
                  f'PF={s.get("profit_factor"):>6}  Sh_ann={s.get("sharpe_annualised"):>6}  '
                  f'n={e["n_trades"]:>5}  hash={e.get("content_hash")}')
            if e.get('mechanism_label'):
                print(f'    -> {e["mechanism_label"]}')
        return 0

    ap.print_help()
    return 1


if __name__ == '__main__':
    import sys
    sys.exit(_cli())
