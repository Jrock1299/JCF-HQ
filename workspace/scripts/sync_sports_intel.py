#!/usr/bin/env python3
import os
import json
import requests
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


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
ODDS_API_KEY = os.getenv('ODDS_API_KEY')

SPORTS = {
    'basketball_nba': 'NBA',
    'icehockey_nhl': 'NHL',
    'basketball_ncaab': 'NCAAB'
}


def get_odds(sport):
    url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": "h2h,spreads",
        "oddsFormat": "american",
        "bookmakers": "draftkings,fanduel"
    }
    r = requests.get(url, params=params, timeout=15)
    if r.status_code == 200:
        return r.json()
    return []


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
