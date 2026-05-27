#!/usr/bin/env python3
"""
intel_injuries.py — Layer 1: Injury edge scoring.
Uses ESPN APIs (no key required) via oracle_intel.py.
Returns injury_edge: float (-1.0 to 1.0).
Positive = edge favors our pick. Negative = edge against our pick.
"""
import sys
sys.path.insert(0, '/root/.openclaw/agents/oracle/bot')

try:
    from oracle_intel import get_injuries as _get_injuries
    _INTEL_AVAILABLE = True
except ImportError:
    _INTEL_AVAILABLE = False

# Positions that qualify as "key players"
KEY_POSITIONS = {
    'PG', 'SG', 'SF', 'PF', 'C',          # NBA
    'QB', 'RB', 'WR', 'TE', 'K',           # NFL
    'SP', 'RP', 'SS', 'P',                 # MLB pitching
    '1B', '2B', '3B', 'LF', 'CF', 'RF',   # MLB position
    'G', 'D', 'LW', 'RW', 'C',            # NHL
}
# Star positions get extra weight
STAR_POSITIONS = {'PG', 'SG', 'SF', 'QB', 'SP'}
HIGH_STATUS = {'Out', 'Doubtful', 'IR', 'IL', 'DL'}

# Per-run cache: sport → injuries dict
_cache: dict = {}


def _fetch_injuries(sport: str) -> dict:
    if sport in _cache:
        return _cache[sport]
    if not _INTEL_AVAILABLE:
        return {}
    try:
        data = _get_injuries(sport)
        _cache[sport] = data
        return data
    except Exception as e:
        print(f'[intel_injuries] fetch error ({sport}): {e}')
        _cache[sport] = {}
        return {}


def _injury_weight(team: str, injuries: dict) -> float:
    """Sum weighted key injuries for a team. Capped at 3.0."""
    weight = 0.0
    for p in injuries.get(team, []):
        if p.get('status') in HIGH_STATUS and p.get('position') in KEY_POSITIONS:
            weight += 1.5 if p.get('position') in STAR_POSITIONS else 1.0
    return min(weight, 3.0)


def get_injury_edge(sport: str, away_team: str, home_team: str,
                    pick_team: str | None = None) -> float:
    """
    Returns injury_edge for a bet.

    pick_team: the team we are backing (ML / spread). Pass None for totals.
    For totals, injuries on either side push toward Under (negative edge).
    """
    injuries = _fetch_injuries(sport)
    away_w = _injury_weight(away_team, injuries)
    home_w = _injury_weight(home_team, injuries)

    # Normalize weights to 0–1
    away_edge = away_w / 3.0   # high → away team is hurt
    home_edge = home_w / 3.0   # high → home team is hurt

    if pick_team is None:
        # Totals: team injuries → less offense → lean Under
        combined = (away_edge + home_edge) / 2.0
        return round(-combined * 0.6, 3)

    if pick_team == away_team:
        # Backing away: good if home hurt, bad if away hurt
        return round(home_edge - away_edge, 3)
    if pick_team == home_team:
        # Backing home: good if away hurt, bad if home hurt
        return round(away_edge - home_edge, 3)

    return 0.0


def clear_cache():
    """Call between runs to reset the per-run injury cache."""
    _cache.clear()


if __name__ == '__main__':
    edge = get_injury_edge('NBA', 'Los Angeles Lakers', 'Boston Celtics', 'Boston Celtics')
    print(f'NBA injury edge (backing Celtics): {edge}')
    edge_total = get_injury_edge('MLB', 'Detroit Tigers', 'New York Yankees')
    print(f'MLB total injury edge: {edge_total}')
