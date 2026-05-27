#!/usr/bin/env python3
"""
intel_schedule.py — Layer 2: Rest & schedule edge scoring.
Uses ESPN APIs (no key required) via oracle_intel.py.
Returns rest_edge: float (-1.0 to 1.0).
Positive = rest advantage favors our pick. Negative = fatigue works against us.
"""
import sys
sys.path.insert(0, '/root/.openclaw/agents/oracle/bot')

try:
    from oracle_intel import get_schedule as _get_schedule
    _INTEL_AVAILABLE = True
except ImportError:
    _INTEL_AVAILABLE = False

# Per-run cache: sport → schedule dict
_cache: dict = {}


def _fetch_schedule(sport: str) -> dict:
    if sport in _cache:
        return _cache[sport]
    if not _INTEL_AVAILABLE:
        return {}
    try:
        data = _get_schedule(sport)
        _cache[sport] = data
        return data
    except Exception as e:
        print(f'[intel_schedule] fetch error ({sport}): {e}')
        _cache[sport] = {}
        return {}


def _fatigue_score(sit: dict) -> float:
    """
    Returns a fatigue score 0.0–1.0 for a team's schedule situation.
    1.0 = very tired, 0.0 = well rested.
    """
    if not sit:
        return 0.0
    if sit.get('b2b'):
        return 0.8
    rest = sit.get('rest_days')
    if rest is None:
        return 0.1  # unknown → assume slight fatigue
    # 0 days rest → 0.6, 1 day → 0.3, 2+ days → ~0.1, 3+ days → 0.0
    return max(0.0, min(0.6, 0.6 - (rest * 0.2)))


def get_rest_edge(sport: str, away_team: str, home_team: str,
                  pick_team: str | None = None) -> float:
    """
    Returns rest_edge for a bet.

    pick_team: team we are backing (ML / spread). Pass None for totals.
    For totals: fatigue on either side pushes toward Under (less scoring).
    """
    schedule = _fetch_schedule(sport)
    away_sit = schedule.get(away_team, {})
    home_sit = schedule.get(home_team, {})

    away_fatigue = _fatigue_score(away_sit)
    home_fatigue = _fatigue_score(home_sit)

    if pick_team is None:
        # Totals: any fatigue → less offense → lean Under
        combined = (away_fatigue + home_fatigue) / 2.0
        return round(-combined * 0.7, 3)

    if pick_team == away_team:
        # Backing away: hurt by own fatigue, helped by home fatigue
        raw = home_fatigue - away_fatigue
    elif pick_team == home_team:
        # Backing home: hurt by own fatigue, helped by away fatigue
        raw = away_fatigue - home_fatigue
    else:
        return 0.0

    # Rest differential bonus — if one team has significantly more rest
    away_rest = away_sit.get('rest_days') or 2.0
    home_rest = home_sit.get('rest_days') or 2.0
    rest_diff = home_rest - away_rest  # positive = home more rested

    if pick_team == away_team:
        rest_bonus = min(0.3, max(-0.3, -rest_diff / 5.0))
    else:
        rest_bonus = min(0.3, max(-0.3, rest_diff / 5.0))

    edge = raw + rest_bonus
    return round(max(-1.0, min(1.0, edge)), 3)


def clear_cache():
    """Call between runs to reset the per-run schedule cache."""
    _cache.clear()


if __name__ == '__main__':
    edge = get_rest_edge('NBA', 'Los Angeles Lakers', 'Boston Celtics', 'Boston Celtics')
    print(f'NBA rest edge (backing Celtics): {edge}')
    edge_total = get_rest_edge('MLB', 'Detroit Tigers', 'New York Yankees')
    print(f'MLB total rest edge: {edge_total}')
