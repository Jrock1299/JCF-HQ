#!/usr/bin/env python3
"""
intel_line_movement.py — Layer 4: Line movement detection.
Saves a snapshot of odds after each Oracle run.
On the next run, loads the previous snapshot and compares.
Returns line_movement_edge: float (-1.0 to 1.0).
Positive = movement suggests sharps agree with our pick.
Negative = movement working against our pick.
"""
import json
import os
from datetime import datetime, timezone

SNAPSHOT_PATH = '/root/.openclaw/dashboard/odds_snapshot.json'


def _american_to_prob(odds: int) -> float:
    if odds > 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)


def save_odds_snapshot(all_raw_games: list) -> None:
    """
    Save current odds for all games to disk.
    Call this AFTER fetching odds each run (becomes "previous" for tomorrow's run).
    The snapshot is keyed by game_id → market:outcome:point → best price.
    """
    snapshot: dict = {
        'date':      datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'games':     {},
    }

    for game in all_raw_games:
        game_id = game.get('id', '')
        if not game_id:
            continue

        game_snap: dict = {
            'away_team': game.get('away_team', ''),
            'home_team': game.get('home_team', ''),
            'odds':      {},
        }

        for bm in game.get('bookmakers', []):
            for market in bm.get('markets', []):
                mk = market.get('key', '')
                for outcome in market.get('outcomes', []):
                    name  = outcome.get('name', '')
                    point = outcome.get('point')
                    price = outcome.get('price')
                    if price is None:
                        continue

                    snap_key = f"{mk}:{name}:{point}"
                    existing = game_snap['odds'].get(snap_key, {})
                    # Keep the best (highest) price across all books
                    if not existing or int(price) > int(existing.get('price', -9999)):
                        game_snap['odds'][snap_key] = {
                            'price': int(price),
                            'book':  bm.get('key', ''),
                        }

        snapshot['games'][game_id] = game_snap

    try:
        with open(SNAPSHOT_PATH, 'w') as f:
            json.dump(snapshot, f, indent=2)
    except Exception as e:
        print(f'[intel_line_movement] could not save snapshot: {e}')


def load_previous_snapshot() -> dict | None:
    """Load the most recently saved odds snapshot (from the prior run)."""
    try:
        with open(SNAPSHOT_PATH) as f:
            return json.load(f)
    except Exception:
        return None


def get_line_movement_edge(
    game_id: str,
    pick_name: str,
    market_key: str,
    current_best_odds: int,
    point: float | None = None,
    previous_snapshot: dict | None = None,
) -> float:
    """
    Returns line_movement_edge for a specific pick.

    pick_name:          outcome name as stored in the snapshot
                        (e.g. "Detroit Tigers", "Over", "Under")
    market_key:         odds-api market key (h2h / spreads / totals / team_totals)
    current_best_odds:  today's best american odds (int)
    point:              line value for spread/total outcomes (float or None)
    previous_snapshot:  pass in a pre-loaded snapshot to avoid repeated disk reads;
                        if None, loads from disk automatically.
    """
    if previous_snapshot is None:
        previous_snapshot = load_previous_snapshot()

    if not previous_snapshot:
        return 0.0   # No baseline yet — first run

    prev_game = previous_snapshot.get('games', {}).get(game_id)
    if not prev_game:
        return 0.0   # Game wasn't in yesterday's snapshot

    # Build the same key used during save
    snap_key = f"{market_key}:{pick_name}:{point}"
    prev_entry = prev_game.get('odds', {}).get(snap_key)
    if not prev_entry:
        return 0.0   # Outcome not found in previous snapshot

    try:
        prev_odds = int(prev_entry['price'])
    except (ValueError, TypeError):
        return 0.0

    if prev_odds == current_best_odds:
        return 0.0   # No movement

    prev_prob = _american_to_prob(prev_odds)
    curr_prob = _american_to_prob(current_best_odds)
    prob_shift = curr_prob - prev_prob   # positive = line shortened (outcome more favored)

    abs_shift = abs(prob_shift)
    if abs_shift < 0.02:   # < 2% shift — noise, ignore
        return 0.0

    # prob_shift > 0 → line shortened on our pick (could be sharp or public money)
    #   — mild positive signal: market moved our way
    # prob_shift < 0 → line drifted on our pick
    #   — mild negative signal: market moved against us
    # Significant moves (> 4%) weighted more heavily
    if prob_shift > 0:
        edge = min(0.6, abs_shift * 8)
    else:
        edge = -min(0.4, abs_shift * 6)

    return round(max(-1.0, min(1.0, edge)), 3)


if __name__ == '__main__':
    snap = load_previous_snapshot()
    if snap:
        print(f"Previous snapshot from: {snap.get('date')} | {len(snap.get('games', {}))} games")
    else:
        print('No previous snapshot found (first run).')
