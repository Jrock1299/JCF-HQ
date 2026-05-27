#!/usr/bin/env python3
import os
import sys
import json
import requests
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, '/root/.openclaw/scripts')


def load_env():
    try:
        with open('/etc/environment') as f:
            for line in f:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass


load_env()
from odds_api_keys import make_odds_request, BASE_URL

SPORTS = {
    'basketball_nba': 'NBA',
    'icehockey_nhl': 'NHL',
    'basketball_ncaab': 'NCAAB'
}


def get_odds(sport):
    url = f"{BASE_URL}/sports/{sport}/odds/"
    params = {
        "regions": "us",
        "markets": "h2h,spreads",
        "oddsFormat": "american",
        "bookmakers": "draftkings,fanduel"
    }
    data, _ = make_odds_request(url, params)
    return data if data is not None else []


def format_time(iso_time):
    try:
        dt = datetime.fromisoformat(iso_time.replace('Z', '+00:00')).astimezone(ZoneInfo('America/New_York'))
        return dt.strftime('%b %d · %I:%M%p ET')
    except Exception:
        return iso_time


def best_h2h(bookmakers, team_name):
    best = None
    for bm in bookmakers:
        for market in bm.get('markets', []):
            if market.get('key') == 'h2h':
                for outcome in market.get('outcomes', []):
                    if outcome.get('name') == team_name:
                        price = outcome.get('price')
                        if best is None or price > best:
                            best = price
    return best


def find_spread(bookmakers, away_team, home_team):
    for bm in bookmakers:
        for market in bm.get('markets', []):
            if market.get('key') == 'spreads':
                for outcome in market.get('outcomes', []):
                    if outcome.get('name') == away_team:
                        return f"{away_team} {outcome.get('point','')}"
                    if outcome.get('name') == home_team:
                        return f"{home_team} {outcome.get('point','')}"
    return ''


def fmt_odds(val):
    if val is None:
        return ''
    return f"+{val}" if val > 0 else str(val)


def main():
    results = []
    for sport_key, sport_label in SPORTS.items():
        games = get_odds(sport_key)
        for g in games:
            bookmakers = g.get('bookmakers', [])
            away = g.get('away_team', '')
            home = g.get('home_team', '')
            results.append({
                "game": f"{away} @ {home}",
                "sport": sport_label,
                "time": format_time(g.get('commence_time', '')),
                "away": away,
                "home": home,
                "away_odds": fmt_odds(best_h2h(bookmakers, away)),
                "home_odds": fmt_odds(best_h2h(bookmakers, home)),
                "spread": find_spread(bookmakers, away, home)
            })

    path = "/root/.openclaw/dashboard/sports_intel.json"
    with open(path, "w") as f:
        json.dump(results, f)
    print(f"Wrote {len(results)} games to {path}")


if __name__ == '__main__':
    main()
