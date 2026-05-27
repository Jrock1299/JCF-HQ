#!/usr/bin/env python3
"""oracle_record.py — CLV tracking, record by sport/bet type, bad spot detection."""
import json, os
from datetime import datetime, timezone
from collections import defaultdict

RECORD_PATH = '/root/.openclaw/agents/oracle/bot/oracle_record.json'

def load_record():
    if not os.path.exists(RECORD_PATH):
        return {'picks': [], 'version': 1}
    try:
        with open(RECORD_PATH) as f:
            return json.load(f)
    except Exception:
        return {'picks': [], 'version': 1}

def save_record(data):
    with open(RECORD_PATH, 'w') as f:
        json.dump(data, f, indent=2)

def log_pick(pick_id, sport, bet_type, pick, odds_at_log, game_time, commence, stake=0.0):
    rec = load_record()
    # Don't duplicate
    if any(p['id'] == pick_id for p in rec['picks']):
        return
    rec['picks'].append({
        'id': pick_id, 'sport': sport, 'bet_type': bet_type, 'pick': pick,
        'odds_at_log': odds_at_log, 'closing_odds': None, 'clv': None,
        'result': 'pending', 'pnl': None, 'stake': round(float(stake), 2),
        'logged_at': datetime.now(timezone.utc).isoformat(),
        'game_time': game_time, 'commence': commence,
    })
    save_record(rec)

def resolve_pick(pick_id, result, pnl):
    rec = load_record()
    for p in rec['picks']:
        if p['id'] == pick_id:
            p['result'] = result
            p['pnl'] = pnl
            break
    save_record(rec)

def get_stats():
    rec = load_record()
    resolved = [p for p in rec['picks'] if p['result'] in ('win', 'loss', 'push')]
    def calc(picks):
        wins = sum(1 for p in picks if p['result'] == 'win')
        losses = sum(1 for p in picks if p['result'] == 'loss')
        pushes = sum(1 for p in picks if p['result'] == 'push')
        total = wins + losses
        pnl = sum((p['pnl'] or 0) for p in picks if p['result'] == 'win') - \
              sum(abs(p['pnl'] or 0) for p in picks if p['result'] == 'loss')
        wr = round(wins / total * 100, 1) if total else 0
        clvs = [p['clv'] for p in picks if p['clv'] is not None]
        return {'wins': wins, 'losses': losses, 'pushes': pushes, 'win_rate': wr,
                'pnl': round(pnl, 2), 'avg_clv': round(sum(clvs)/len(clvs), 2) if clvs else None}
    by_sport = defaultdict(list)
    by_type = defaultdict(list)
    for p in resolved:
        by_sport[p['sport']].append(p)
        by_type[p['bet_type']].append(p)
    return {
        'overall': calc(resolved),
        'by_sport': {s: calc(ps) for s, ps in by_sport.items()},
        'by_type': {t: calc(ps) for t, ps in by_type.items()},
        'total_picks': len(rec['picks']),
        'pending': len([p for p in rec['picks'] if p['result'] == 'pending']),
    }

def get_bad_spots():
    stats = get_stats()
    warnings = []
    for sport, s in stats['by_sport'].items():
        total = s['wins'] + s['losses']
        if total >= 5 and s['win_rate'] < 45:
            warnings.append(f'⛔ Fade Oracle {sport} — {s["win_rate"]}% WR ({total} bets, {s["pnl"]:+.2f} P&L)')
    for bt, s in stats['by_type'].items():
        total = s['wins'] + s['losses']
        if total >= 5 and s['win_rate'] < 45:
            warnings.append(f'⛔ Fade Oracle {bt} bets — {s["win_rate"]}% WR ({total} bets)')
    return warnings

if __name__ == '__main__':
    print('Record module loaded OK')
    stats = get_stats()
    print(f'  Picks: {stats["total_picks"]}, Pending: {stats["pending"]}')
