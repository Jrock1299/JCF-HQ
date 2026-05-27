#!/usr/bin/env python3
"""
oracle_intel.py — Injury reports + situational context (B2B, rest days, travel)
Uses ESPN hidden APIs — no key required.
"""
import requests
from datetime import datetime, timezone, timedelta

ESPN_SPORT_MAP = {
    'NBA': ('basketball', 'nba'),
    'NFL': ('football', 'nfl'),
    'MLB': ('baseball', 'mlb'),
    'NHL': ('hockey', 'nhl'),
    'NCAAB': ('basketball', 'mens-college-basketball'),
}

def get_injuries(sport_label):
    if sport_label not in ESPN_SPORT_MAP:
        return {}
    sport, league = ESPN_SPORT_MAP[sport_label]
    url = f'https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/injuries'
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return {}
        data = r.json()
        result = {}
        for team_entry in data.get('injuries', []):
            team_name = team_entry.get('team', {}).get('displayName', '')
            players = []
            for inj in team_entry.get('injuries', []):
                athlete = inj.get('athlete', {})
                status = inj.get('status', '')
                detail = inj.get('details', {})
                position = athlete.get('position', {}).get('abbreviation', '')
                players.append({
                    'name': athlete.get('displayName', ''),
                    'position': position,
                    'status': status,
                    'type': detail.get('type', ''),
                })
            if players:
                result[team_name] = players
        return result
    except Exception as e:
        print(f'[intel] injury fetch error ({sport_label}): {e}')
        return {}

def get_schedule(sport_label, days_back=3, days_ahead=1):
    if sport_label not in ESPN_SPORT_MAP:
        return {}
    sport, league = ESPN_SPORT_MAP[sport_label]
    now = datetime.now(timezone.utc)
    team_last_game = {}
    team_next_game = {}
    for offset in range(-days_back, days_ahead + 1):
        day = now + timedelta(days=offset)
        date_str = day.strftime('%Y%m%d')
        url = f'https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard?dates={date_str}'
        try:
            r = requests.get(url, timeout=10)
            if r.status_code != 200:
                continue
            data = r.json()
            for event in data.get('events', []):
                game_time_str = event.get('date', '')
                try:
                    game_time = datetime.fromisoformat(game_time_str.replace('Z', '+00:00'))
                except Exception:
                    continue
                for comp in event.get('competitions', []):
                    for team_data in comp.get('competitors', []):
                        team_name = team_data.get('team', {}).get('displayName', '')
                        if not team_name:
                            continue
                        if game_time < now:
                            if team_name not in team_last_game or game_time > team_last_game[team_name]:
                                team_last_game[team_name] = game_time
                        else:
                            if team_name not in team_next_game or game_time < team_next_game[team_name]:
                                team_next_game[team_name] = game_time
        except Exception as e:
            print(f'[intel] schedule fetch error ({date_str}): {e}')
    result = {}
    all_teams = set(list(team_last_game.keys()) + list(team_next_game.keys()))
    for team in all_teams:
        last = team_last_game.get(team)
        nxt = team_next_game.get(team)
        rest_days = None
        b2b = False
        if last and nxt:
            diff = (nxt - last).total_seconds() / 86400
            rest_days = round(diff, 1)
            b2b = diff < 1.5
        elif last:
            diff = (now - last).total_seconds() / 86400
            rest_days = round(diff, 1)
        result[team] = {
            'last_game': last.isoformat() if last else None,
            'next_game': nxt.isoformat() if nxt else None,
            'rest_days': rest_days,
            'b2b': b2b,
        }
    return result

def get_game_context(sport_label, away_team, home_team):
    injuries = get_injuries(sport_label)
    schedule = get_schedule(sport_label)
    KEY_POSITIONS = {'PG','SG','SF','PF','C','QB','RB','WR','TE','SP','RP','SS'}
    HIGH_STATUS = {'Out','Doubtful','IR','IL','DL'}
    def key_injuries(team):
        return [p for p in injuries.get(team, [])
                if p['status'] in HIGH_STATUS and p['position'] in KEY_POSITIONS]
    def sit(team):
        return schedule.get(team, {})
    away_inj = key_injuries(away_team)
    home_inj = key_injuries(home_team)
    away_sit = sit(away_team)
    home_sit = sit(home_team)
    flags = []
    if away_inj:
        names = ', '.join(p['name'] for p in away_inj[:3])
        flags.append(f'⚠️  {away_team} missing: {names}')
    if home_inj:
        names = ', '.join(p['name'] for p in home_inj[:3])
        flags.append(f'⚠️  {home_team} missing: {names}')
    if away_sit.get('b2b'):
        flags.append(f'😴 {away_team} on B2B (rest: {away_sit["rest_days"]}d)')
    if home_sit.get('b2b'):
        flags.append(f'😴 {home_team} on B2B (rest: {home_sit["rest_days"]}d)')
    away_rest = away_sit.get('rest_days')
    home_rest = home_sit.get('rest_days')
    if away_rest and home_rest:
        diff = abs(away_rest - home_rest)
        if diff >= 1.5:
            rested = home_team if home_rest > away_rest else away_team
            tired = away_team if home_rest > away_rest else home_team
            flags.append(f'📅 Rest edge: {rested} has {diff:.1f}d more rest than {tired}')
    return {
        'away_injuries': away_inj,
        'home_injuries': home_inj,
        'away_situation': away_sit,
        'home_situation': home_sit,
        'flags': flags,
        'has_concerns': len(flags) > 0,
    }

if __name__ == '__main__':
    print('Testing NBA injuries...')
    inj = get_injuries('NBA')
    print(f'  Teams with injuries: {len(inj)}')
    for team, players in list(inj.items())[:3]:
        print(f'  {team}: {[p["name"] + " (" + p["status"] + ")" for p in players[:2]]}')
    print('\nTesting NBA B2B...')
    sched = get_schedule('NBA')
    b2bs = [(t, s) for t, s in sched.items() if s['b2b']]
    print(f'  B2B teams tonight: {len(b2bs)}')
