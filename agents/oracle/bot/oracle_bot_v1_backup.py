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





def calc_profit(odds, stake=10):
    try:
        o = int(str(odds).replace('+','').strip())
    except Exception:
        return 0
    if o < 0:
        return round(stake / (abs(o) / 100), 2)
    return round(stake * (o / 100), 2)


def write_picks_to_hq(picks):
    import json
    # Load bankroll if available
    bankroll = 0
    try:
        with open('/root/.openclaw/dashboard/oracle_bankroll.json') as f:
            b = json.load(f)
            bankroll = b.get('balance', b.get('bankroll', 0))
    except Exception:
        bankroll = 0

    normalized_picks = []
    for p in picks:
        odds = p["best_odds"]
        stake = 10
        pnl_val = calc_profit(odds, stake)
        normalized_picks.append({
            "date": p.get("commence", ""),
            "sport": p.get("sport", ""),
            "pick": f"{p['pick']} ({odds})",
            "odds": odds,
            "stake": str(stake),
            "result": "pending",
            "pnl": pnl_val
        })

    # Compute record/pnl if any resolved
    wins = 0
    losses = 0
    total_pnl = 0
    for p in normalized_picks:
        res = str(p.get('result','')).lower()
        pnl_val = p.get('pnl', 0) or 0
        if res == 'win':
            wins += 1
            total_pnl += pnl_val
        elif res == 'loss':
            losses += 1
            total_pnl -= abs(pnl_val) if pnl_val is not None else 0

    total_bets = wins + losses
    win_rate = f"{round((wins / total_bets) * 100, 1) if total_bets else 0}%"

    payload = {
        "bankroll": bankroll,
        "record": f"{wins}W – {losses}L",
        "win_rate": win_rate,
        "total_pnl": round(total_pnl, 2),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "picks": normalized_picks
    }

    path = "/root/.openclaw/dashboard/oracle_picks.json"
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
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
