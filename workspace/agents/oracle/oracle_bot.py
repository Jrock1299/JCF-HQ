#!/usr/bin/env python3
import os, json, requests
from datetime import datetime, timezone

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
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

BASE = '/root/.openclaw/agents/oracle/bot'
SPORTS = [
    'basketball_nba',
    'americanfootball_nfl',
    'baseball_mlb',
    'icehockey_nhl',
    'basketball_ncaab'
]

SPORT_LABELS = {
    'basketball_nba': 'NBA',
    'americanfootball_nfl': 'NFL',
    'baseball_mlb': 'MLB',
    'icehockey_nhl': 'NHL',
    'basketball_ncaab': 'NCAAB'
}

def get_odds(sport):
    url = f'https://api.the-odds-api.com/v4/sports/{sport}/odds/'
    params = {
        'apiKey': ODDS_API_KEY,
        'regions': 'us',
        'markets': 'h2h,spreads,totals',
        'oddsFormat': 'american',
        'bookmakers': 'draftkings,fanduel,betmgm,williamhill_us,bovada,mybookieag,betonlineag'
    }
    r = requests.get(url, params=params, timeout=15)
    if r.status_code == 200:
        return r.json()
    return []

def american_to_prob(odds):
    if odds > 0:
        return 100 / (odds + 100)
    else:
        return abs(odds) / (abs(odds) + 100)

def find_edge(game):
    picks = []
    bookmakers = game.get('bookmakers', [])
    if not bookmakers:
        return picks
    # H2H value — compare DraftKings vs FanDuel odds
    dk_h2h = {}
    fd_h2h = {}
    for bm in bookmakers:
        for market in bm.get('markets', []):
            if market['key'] == 'h2h':
                for outcome in market['outcomes']:
                    if bm['key'] == 'draftkings':
                        dk_h2h[outcome['name']] = outcome['price']
                    elif bm['key'] == 'fanduel':
                        fd_h2h[outcome['name']] = outcome['price']
    # Find lines where books disagree by 5%+ — real edge
    for team in dk_h2h:
        if team in fd_h2h:
            dk_prob = american_to_prob(dk_h2h[team])
            fd_prob = american_to_prob(fd_h2h[team])
            edge = abs(dk_prob - fd_prob)
            if edge >= 0.02:
                best_odds = max(dk_h2h[team], fd_h2h[team])
                best_book = 'DraftKings' if dk_h2h[team] >= fd_h2h[team] else 'FanDuel'
                picks.append({
                    'game': f"{game['away_team']} @ {game['home_team']}",
                    'pick': team,
                    'best_odds': f"+{best_odds}" if best_odds > 0 else str(best_odds),
                    'best_book': best_book,
                    'edge': round(edge * 100, 1),
                    'sport': SPORT_LABELS.get(game.get('sport_key', ''), ''),
                    'commence': game.get('commence_time', '')
                })
    # Totals value — look for over/unders where one book is significantly different
    dk_totals = {}
    fd_totals = {}
    for bm in bookmakers:
        for market in bm.get('markets', []):
            if market['key'] == 'totals':
                for outcome in market['outcomes']:
                    key = f"{outcome['name']} {outcome.get('point','')}"
                    if bm['key'] == 'draftkings':
                        dk_totals[key] = outcome['price']
                    elif bm['key'] == 'fanduel':
                        fd_totals[key] = outcome['price']
    for total in dk_totals:
        if total in fd_totals:
            dk_prob = american_to_prob(dk_totals[total])
            fd_prob = american_to_prob(fd_totals[total])
            edge = abs(dk_prob - fd_prob)
            if edge >= 0.03:
                best_odds = max(dk_totals[total], fd_totals[total])
                best_book = 'DraftKings' if dk_totals[total] >= fd_totals[total] else 'FanDuel'
                picks.append({
                    'game': f"{game['away_team']} @ {game['home_team']}",
                    'pick': total,
                    'best_odds': f"+{best_odds}" if best_odds > 0 else str(best_odds),
                    'best_book': best_book,
                    'edge': round(edge * 100, 1),
                    'sport': SPORT_LABELS.get(game.get('sport_key', ''), ''),
                    'commence': game.get('commence_time', '')
                })
    return picks



def write_picks_to_hq(picks):
    import json
    payload = {
        "date": datetime.now(timezone.utc).strftime("%b %d, %Y"),
        "picks": [
            {
                "title": p["game"],
                "side": f"Take {p['pick']} ({p['best_odds']})",
                "prob": round((1 / (1 + abs(int(p['best_odds'].replace('+','')))/100)) * 100 if '+' in p['best_odds'] else (abs(int(p['best_odds'])) / (abs(int(p['best_odds'])) + 100)) * 100, 1),
                "volume": "—",
                "edge": f"{p['edge']}%",
                "odds": p["best_odds"],
                "sport": p.get("sport", ""),
                "date": p.get("commence", "")
            } for p in picks
        ]
    }
    path = "/root/.openclaw/dashboard/oracle_picks.json"
    with open(path, "w") as f:
        json.dump(payload, f)
    print(f"Oracle picks written to {path}")
def build_report():
    all_picks = []
    for sport in SPORTS:
        games = get_odds(sport)
        for game in games:
            game['sport_key'] = sport
            picks = find_edge(game)
            all_picks.extend(picks)
    # Deduplicate — one pick per game, keep highest edge
    seen_games = {}
    for p in all_picks:
        game_key = p['game']
        if game_key not in seen_games or p['edge'] > seen_games[game_key]['edge']:
            seen_games[game_key] = p
    all_picks = list(seen_games.values())
    # Sort by edge descending, take top 8
    all_picks.sort(key=lambda x: x['edge'], reverse=True)
    top_picks = all_picks[:8]
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    lines = [
        '============================================================',
        '🔮 ORACLE SPORTS INTELLIGENCE REPORT',
        f'Generated: {now}',
        '============================================================',
        ''
    ]
    if top_picks:
        lines.append('🏆 TOP PICKS TODAY')
        lines.append('----------------------------------------')
        for i, p in enumerate(top_picks, 1):
            # Parse and format commence time
            try:
                ct = datetime.fromisoformat(p['commence'].replace('Z','+00:00'))
                game_time = ct.strftime('%b %d %I:%M%p ET')
            except Exception:
                game_time = p['commence']
            lines.append(f"{i}. {p['game']}")
            lines.append(f" ✅ Take: {p['pick']} ({p['best_odds']})")
            lines.append(f" 📊 Edge: {p['edge']}% | Best on: {p.get('best_book','—')} | Sport: {p['sport']}")
            lines.append(f" 🕐 {game_time}")
            lines.append('')
    else:
        lines.append('No value picks found today.')
    lines.append('============================================================')
    report = '\n'.join(lines)
    # Save report
    ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')
    path = f'{BASE}/report_{ts}.txt'
    with open(path, 'w') as f:
        f.write(report)
    print(report)
    write_picks_to_hq(top_picks)
    # Send to Telegram
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        msg = f"<pre>{report}</pre>"
        requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={'chat_id': TELEGRAM_CHAT_ID, 'text': msg, 'parse_mode': 'HTML'},
            timeout=10
        )

if __name__ == '__main__':
    build_report()
