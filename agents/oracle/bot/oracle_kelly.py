#!/usr/bin/env python3
"""oracle_kelly.py — Quarter Kelly Criterion bet sizing."""

def kelly_stake(bankroll, edge_pct, odds_american, fraction=0.25, min_stake=5, max_stake=50):
    try:
        odds = int(str(odds_american).replace('+', '').strip())
    except Exception:
        return {'stake': min_stake, 'kelly_pct': 0, 'reasoning': 'Could not parse odds'}
    decimal_odds = 1 + (100 / abs(odds)) if odds < 0 else 1 + (odds / 100)
    line_prob = abs(odds) / (abs(odds) + 100) if odds < 0 else 100 / (odds + 100)
    est_win_prob = min(line_prob + (edge_pct / 100), 0.95)
    b = decimal_odds - 1
    p = est_win_prob
    q = 1 - p
    kelly_full = (b * p - q) / b
    if kelly_full <= 0:
        return {'stake': min_stake, 'kelly_pct': 0, 'reasoning': f'No Kelly edge (full Kelly: {kelly_full:.3f}). Min stake.'}
    kelly_frac = kelly_full * fraction
    raw_stake = bankroll * kelly_frac
    max_allowed = min(max_stake, bankroll * 0.10)
    stake = round(max(min_stake, min(raw_stake, max_allowed)), 2)
    return {
        'stake': stake,
        'kelly_pct': round(kelly_full * 100, 2),
        'fractional_kelly_pct': round(kelly_frac * 100, 2),
        'est_win_prob': round(est_win_prob * 100, 1),
        'reasoning': f'Full Kelly: {kelly_full*100:.1f}% | Quarter: {kelly_frac*100:.1f}% of ${bankroll:.2f} = ${raw_stake:.2f} → ${stake:.2f}'
    }

def kelly_label(stake, flat_stake=10):
    ratio = stake / flat_stake
    if ratio >= 2.5: return '🔥 MAX'
    elif ratio >= 1.5: return '⬆️ LARGE'
    elif ratio >= 0.8: return '✅ STANDARD'
    else: return '⬇️ SMALL'

if __name__ == '__main__':
    print('Kelly module loaded OK')
    r = kelly_stake(500.0, 5.0, -110)
    print(f'  Test: ${r["stake"]} — {r["reasoning"]}')
