#!/usr/bin/env python3
"""
oracle_bot.py — Daily Oracle pick generator (rebuild v3, 2026-05-18).

CORE RULES (non-negotiable)
  - Straight bets only. ZERO parlays.
  - NBA + MLB only (NFL auto-added in September).
  - Max 3 bets per day. "No bet" is always valid and preferred.
  - EV filter: devigged consensus across ≥8 books minus implied prob from
    best available odds must be ≥ 3.0%.
  - Odds range: −150 to +250 hard cap (any bet type).
  - Moneyline: only allowed within −150 to +200. NEVER heavier than −150.
  - Bet-type priority (only relevant for ranking ties): SPREADS > TOTALS > ML.
  - Flat $10 stake. $5 floor if Kelly would suggest <$10 (data-collection floor).
  - Logs every candidate evaluation (fired and skipped) with reason.

Pipeline:
  1. Discover active sport keys (NBA, MLB; NFL after Sep 1).
  2. Per sport: fetch /odds with markets h2h, spreads, totals.
  3. Build candidates per (game, market, side). Devig across ≥8 books.
  4. Filter: odds-range, ML-range, edge ≥3%.
  5. Rank by edge_pct (with priority tiebreaker), take ≤3.
  6. Stake flat $10 (or $5 if Kelly fraction suggests <$10).
  7. Write oracle_picks.json + append to oracle_resolved.json (status='pending').

Cron: 0 9 * * *
"""

import json
import os
import sys
import requests
import sys
sys.path.insert(0, "/root/.openclaw/scripts")
from telegram_personalities import wrap_message

from datetime import datetime, timezone

sys.path.insert(0, '/root/.openclaw/scripts')
sys.path.insert(0, '/root/.openclaw/agents/oracle/bot')

from odds_api_keys import make_odds_request, refresh_quotas, BASE_URL
from hub_post import add_hub_message as hub_post
from oracle_kelly import kelly_stake


PICKS_PATH    = '/root/.openclaw/dashboard/oracle_picks.json'
RESOLVED_PATH = '/root/.openclaw/dashboard/oracle_resolved.json'
BANKROLL_PATH = '/root/.openclaw/dashboard/oracle_bankroll.json'
LOG_PATH      = '/root/.openclaw/agents/oracle/bot/oracle.log'

# ── Filters ──────────────────────────────────────────────────────────────────
EDGE_THRESHOLD_PCT     = 3.0     # devigged true_prob minus implied_prob from best odds
MIN_BOOKS_REQUIRED     = 8       # devig requires ≥ this many books PER SIDE

# Odds caps (American)
ODDS_RANGE_MIN         = -150    # never bet anything stronger than -150
ODDS_RANGE_MAX         =  250    # never bet anything longer than +250
MONEYLINE_RANGE_MAX    =  200    # ML upper bound stricter than other markets

# Selection
MAX_PICKS_PER_DAY      = 3

# Sizing
FLAT_STAKE             = 10.0
FLOOR_STAKE            =  5.0    # used when Kelly would suggest < FLAT_STAKE

# Bet-type priority for tiebreakers only (higher = preferred)
BET_TYPE_PRIORITY = {'spreads': 3, 'totals': 2, 'h2h': 1}

# Books we'll consider for devigging (US books with broad coverage)
PREFERRED_BOOKS = [
    'fanduel', 'draftkings', 'betmgm', 'caesars', 'pointsbetus',
    'williamhill_us', 'betrivers', 'unibet_us', 'bovada', 'wynnbet',
    'twinspires', 'foxbet', 'mybookieag', 'betonlineag', 'lowvig',
    'betus', 'superbook', 'wynnbet_michigan', 'gtbets',
]


# ─── Env / logging / telegram ────────────────────────────────────────────────
def load_env():
    try:
        with open('/etc/environment') as f:
            for line in f:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except Exception:
        pass


load_env()
TELEGRAM_TOKEN   = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_ALERT_CHAT_ID') or os.getenv('TELEGRAM_CHAT_ID')


def log(msg: str):
    line = f'{datetime.now(timezone.utc).isoformat()} {msg}'
    print(line)
    try:
        with open(LOG_PATH, 'a') as f:
            f.write(line + '\n')
    except Exception:
        pass


def send_telegram(msg: str):
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT_ID):
        return
    try:
        requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={'chat_id': TELEGRAM_CHAT_ID, 'text': msg},
            timeout=10,
        )
    except Exception as e:
        log(f'[telegram] {e}')


# ─── Odds math ───────────────────────────────────────────────────────────────
def american_to_decimal(odds) -> float:
    o = int(str(odds).replace('+', '').strip())
    return 1 + (100 / abs(o)) if o < 0 else 1 + (o / 100)


def american_to_implied(odds) -> float:
    o = int(str(odds).replace('+', '').strip())
    return abs(o) / (abs(o) + 100) if o < 0 else 100 / (o + 100)


def odds_to_int(odds) -> int:
    return int(str(odds).replace('+', '').strip())


# ─── Sport discovery ─────────────────────────────────────────────────────────
def active_sport_keys() -> list:
    """NBA + MLB always; NFL added Sep–Feb."""
    keys = ['basketball_nba', 'baseball_mlb']
    month = datetime.now(timezone.utc).month
    if month >= 9 or month <= 2:
        keys.append('americanfootball_nfl')
    return keys


SPORT_LABELS = {
    'basketball_nba':       'NBA',
    'baseball_mlb':         'MLB',
    'americanfootball_nfl': 'NFL',
}


# ─── Odds fetch + market quote collection ────────────────────────────────────
def fetch_odds(sport_key: str) -> list:
    url = f'{BASE_URL}/sports/{sport_key}/odds/'
    data, _ = make_odds_request(url, {
        'regions':    'us',
        'markets':    'h2h,spreads,totals',
        'oddsFormat': 'american',
        'dateFormat': 'iso',
    })
    return data or []


def collect_market_quotes(game: dict, market_key: str) -> dict:
    """
    Return outcome_key → list of (book, price, point).
    h2h:       outcome_key = 'home' | 'away'
    spreads:   outcome_key = ('home', point) | ('away', point)
    totals:    outcome_key = ('over', point) | ('under', point)
    """
    home = game.get('home_team', '')
    quotes: dict = {}
    for bk in game.get('bookmakers') or []:
        bkey = bk.get('key', '')
        if PREFERRED_BOOKS and bkey not in PREFERRED_BOOKS:
            continue
        for mk in bk.get('markets') or []:
            if mk.get('key') != market_key:
                continue
            for oc in mk.get('outcomes') or []:
                name  = oc.get('name', '')
                price = oc.get('price')
                point = oc.get('point')
                if price is None:
                    continue
                if market_key == 'h2h':
                    side = 'home' if name == home else 'away'
                    quotes.setdefault(side, []).append((bkey, price, None))
                elif market_key == 'spreads':
                    side = 'home' if name == home else 'away'
                    quotes.setdefault((side, point), []).append((bkey, price, point))
                elif market_key == 'totals':
                    side = name.lower()  # "Over" / "Under"
                    quotes.setdefault((side, point), []).append((bkey, price, point))
    return quotes


def devig_pair(quotes_a: list, quotes_b: list):
    """
    Devig two opposite-side quote lists. Returns
        (best_a_odds_int, true_prob_a, best_book_a, book_count_a, implied_from_best_a)
    or None tuple components if either side has < MIN_BOOKS_REQUIRED books.
    """
    if len(quotes_a) < MIN_BOOKS_REQUIRED or len(quotes_b) < MIN_BOOKS_REQUIRED:
        return None, None, None, len(quotes_a), None
    imp_a = sum(american_to_implied(p) for _, p, _ in quotes_a) / len(quotes_a)
    imp_b = sum(american_to_implied(p) for _, p, _ in quotes_b) / len(quotes_b)
    total = imp_a + imp_b
    if total <= 0:
        return None, None, None, len(quotes_a), None
    true_prob = imp_a / total
    best = max(quotes_a, key=lambda q: american_to_decimal(q[1]))
    implied_from_best = american_to_implied(best[1])
    return odds_to_int(best[1]), true_prob, best[0], len(quotes_a), implied_from_best


# ─── Candidate builder ───────────────────────────────────────────────────────
def build_candidates_for_game(game: dict, sport_label: str) -> list:
    """Return list of candidate dicts — every (market, side) tried."""
    out  = []
    home = game.get('home_team', '')
    away = game.get('away_team', '')
    commence = game.get('commence_time', '')

    # ── h2h ────────────────────────────────────────────────────────────────
    h2h = collect_market_quotes(game, 'h2h')
    if 'home' in h2h and 'away' in h2h:
        for side, opp in (('home', 'away'), ('away', 'home')):
            best, tp, book, n, impl = devig_pair(h2h[side], h2h[opp])
            team_pick = home if side == 'home' else away
            out.append({
                'sport':         sport_label,
                'sport_key':     game.get('_sport_key', ''),
                'home_team':     home,
                'away_team':     away,
                'commence_time': commence,
                'market':        'h2h',
                'side':          side,
                'line':          None,
                'best_odds':     best,
                'best_book':     book,
                'true_prob':     tp,
                'implied_prob':  impl,
                'book_consensus': n,
                'label':         f'{team_pick} ML',
            })

    # ── spreads ────────────────────────────────────────────────────────────
    spreads = collect_market_quotes(game, 'spreads')
    points  = sorted({k[1] for k in spreads if k[0] == 'home' and k[1] is not None})
    for pt in points:
        a_q = spreads.get(('home',  pt), [])
        b_q = spreads.get(('away', -pt), [])
        if not a_q or not b_q:
            continue
        for side, my_pt, my_q, opp_q in (
            ('home',  pt, a_q, b_q),
            ('away', -pt, b_q, a_q),
        ):
            best, tp, book, n, impl = devig_pair(my_q, opp_q)
            team_pick = home if side == 'home' else away
            sign = '+' if my_pt > 0 else ''
            out.append({
                'sport':         sport_label,
                'sport_key':     game.get('_sport_key', ''),
                'home_team':     home,
                'away_team':     away,
                'commence_time': commence,
                'market':        'spreads',
                'side':          side,
                'line':          my_pt,
                'best_odds':     best,
                'best_book':     book,
                'true_prob':     tp,
                'implied_prob':  impl,
                'book_consensus': n,
                'label':         f'{team_pick} {sign}{my_pt}',
            })

    # ── totals ─────────────────────────────────────────────────────────────
    totals = collect_market_quotes(game, 'totals')
    pts    = sorted({k[1] for k in totals if k[0] == 'over' and k[1] is not None})
    for pt in pts:
        ov = totals.get(('over',  pt), [])
        un = totals.get(('under', pt), [])
        if not ov or not un:
            continue
        for side, my_q, opp_q in (('over', ov, un), ('under', un, ov)):
            best, tp, book, n, impl = devig_pair(my_q, opp_q)
            out.append({
                'sport':         sport_label,
                'sport_key':     game.get('_sport_key', ''),
                'home_team':     home,
                'away_team':     away,
                'commence_time': commence,
                'market':        'totals',
                'side':          side,
                'line':          pt,
                'best_odds':     best,
                'best_book':     book,
                'true_prob':     tp,
                'implied_prob':  impl,
                'book_consensus': n,
                'label':         f'{side.upper()} {pt}',
            })

    return out


# ─── Filters ─────────────────────────────────────────────────────────────────
def candidate_reject_reason(c: dict) -> str | None:
    """Return None if candidate passes; reason string otherwise."""
    if c.get('best_odds') is None or c.get('true_prob') is None:
        return f'insufficient_books ({c.get("book_consensus", 0)} of {MIN_BOOKS_REQUIRED})'
    odds = c['best_odds']
    if odds < ODDS_RANGE_MIN or odds > ODDS_RANGE_MAX:
        return f'odds_out_of_range ({odds:+d} not in [{ODDS_RANGE_MIN},{ODDS_RANGE_MAX}])'
    if c['market'] == 'h2h' and odds < ODDS_RANGE_MIN:
        # already covered above, but explicit
        return f'ml_too_heavy ({odds:+d} < {ODDS_RANGE_MIN})'
    if c['market'] == 'h2h' and odds > MONEYLINE_RANGE_MAX:
        return f'ml_too_long ({odds:+d} > {MONEYLINE_RANGE_MAX})'
    edge_pct = (c['true_prob'] - c['implied_prob']) * 100
    if edge_pct < EDGE_THRESHOLD_PCT:
        return f'edge_too_small ({edge_pct:.2f}% < {EDGE_THRESHOLD_PCT}%)'
    return None


def annotate_edge(c: dict):
    edge_pct = (c['true_prob'] - c['implied_prob']) * 100
    ev_unit  = (american_to_decimal(c['best_odds']) - 1) * c['true_prob'] \
               - (1 - c['true_prob'])   # EV in units of stake
    c['edge_pct']    = round(edge_pct, 2)
    c['ev_per_unit'] = round(ev_unit, 4)
    c['ev_pct']      = round(ev_unit * 100, 2)


# ─── Sizing ─────────────────────────────────────────────────────────────────
def size_pick(bankroll: float, edge_pct: float, american_odds) -> dict:
    """
    Flat $10 by default. Drop to $5 if Kelly fraction suggests stake <$10
    (Kelly is consulted purely as a floor signal during validation).
    """
    k = kelly_stake(bankroll, edge_pct, american_odds, fraction=0.25,
                    min_stake=0.01, max_stake=10_000)
    kelly_raw = k.get('stake', 0)
    if kelly_raw < FLAT_STAKE:
        stake = FLOOR_STAKE
        rationale = f'Kelly raw ${kelly_raw:.2f} < ${FLAT_STAKE:.0f} → floor ${FLOOR_STAKE:.0f}'
    else:
        stake = FLAT_STAKE
        rationale = f'Flat ${FLAT_STAKE:.0f} (Kelly raw ${kelly_raw:.2f})'
    return {
        'stake':         stake,
        'kelly_raw':     round(kelly_raw, 2),
        'sizing_method': rationale,
    }


# ─── Reasoning ───────────────────────────────────────────────────────────────
def build_reasoning(c: dict) -> str:
    return (f'{c["book_consensus"]}-book consensus puts true_prob at '
            f'{c["true_prob"]*100:.1f}% vs {c["implied_prob"]*100:.1f}% implied '
            f'at best odds {c["best_odds"]:+d} ({c["best_book"]}). '
            f'Edge {c["edge_pct"]:.2f}% / EV {c["ev_pct"]:+.2f}%.')


# ─── Output records ──────────────────────────────────────────────────────────
def candidate_to_pick(c: dict, stake_info: dict, now_iso: str) -> dict:
    odds = c['best_odds']
    odds_str = f'+{odds}' if odds > 0 else str(odds)
    return {
        'date':            now_iso,
        'sport':           c['sport'],
        'sport_key':       c['sport_key'],
        'bet_type':        c['market'].upper(),  # H2H / SPREADS / TOTALS
        'pick':            f'{c["label"]} ({c["away_team"]} @ {c["home_team"]})',
        'home_team':       c['home_team'],
        'away_team':       c['away_team'],
        'teams':           f'{c["away_team"]} @ {c["home_team"]}',
        'commence_time':   c['commence_time'],
        'market':          c['market'],
        'side':            c['side'],
        'line':            c['line'],
        'best_odds':       odds,
        'odds':            odds_str,
        'best_book':       c['best_book'],
        'true_prob':       round(c['true_prob'], 4),
        'implied_prob':    round(c['implied_prob'], 4),
        'edge_pct':        c['edge_pct'],
        'ev_pct':          c['ev_pct'],
        'ev_per_unit':     c['ev_per_unit'],
        'book_consensus':  c['book_consensus'],
        'line_movement':   'N/A',          # placeholder until historical-odds plumbing exists
        'reasoning':       build_reasoning(c),
        'stake':           stake_info['stake'],
        'sizing_method':   stake_info['sizing_method'],
        'kelly_raw':       stake_info['kelly_raw'],
        'status':          'pending',
        'result':          'pending',
        'type':            'straight',
    }


# ─── Persistence ─────────────────────────────────────────────────────────────
def load_bankroll() -> float:
    try:
        with open(BANKROLL_PATH) as f:
            return float(json.load(f).get('balance', 500.0))
    except Exception:
        return 500.0


def write_picks_json(slate: list, reason: str | None, now_iso: str):
    with open(PICKS_PATH, 'w') as f:
        json.dump({
            'date':          now_iso,
            'generated_at':  now_iso,
            'pick_count':    len(slate),
            'picks':         slate,
            'no_bet_reason': reason,
        }, f, indent=2)


def append_to_resolved(slate: list):
    try:
        with open(RESOLVED_PATH) as f:
            ledger = json.load(f)
    except Exception:
        ledger = {'picks': [], 'schema_version': 3}
    ledger.setdefault('picks', []).extend(slate)
    ledger['updated']        = datetime.now(timezone.utc).isoformat()
    ledger['schema_version'] = 3
    with open(RESOLVED_PATH, 'w') as f:
        json.dump(ledger, f, indent=2)


# ─── Ranking ─────────────────────────────────────────────────────────────────
def rank_candidates(qualifying: list) -> list:
    """Sort by (edge_pct DESC, bet-type priority DESC)."""
    return sorted(
        qualifying,
        key=lambda c: (c['edge_pct'], BET_TYPE_PRIORITY.get(c['market'], 0)),
        reverse=True,
    )


# ─── Main ────────────────────────────────────────────────────────────────────
def main():
    log('=== Oracle bot run start ===')
    refresh_quotas()

    bankroll = load_bankroll()
    log(f'[bankroll] balance=${bankroll:.2f}')

    sports = active_sport_keys()
    log(f'[discovery] active sport keys: {sports}')

    candidates: list = []
    for sk in sports:
        label = SPORT_LABELS.get(sk, sk.upper())
        games = fetch_odds(sk)
        log(f'[odds] {sk}: {len(games)} games')
        for g in games:
            g['_sport_key'] = sk
            candidates.extend(build_candidates_for_game(g, label))

    log(f'[candidates] {len(candidates)} total across all (game,market,side) tuples')

    qualifying = []
    for c in candidates:
        reason = candidate_reject_reason(c)
        subject = (f'{c.get("sport","?")} {c.get("label","?")} '
                   f'({c.get("away_team","?")} @ {c.get("home_team","?")})')
        if reason:
            log(f'[skip] {subject}: {reason}')
            continue
        annotate_edge(c)
        qualifying.append(c)
        log(f'[pass] {subject}: best_odds={c["best_odds"]:+d} '
            f'true_prob={c["true_prob"]*100:.1f}% implied={c["implied_prob"]*100:.1f}% '
            f'edge={c["edge_pct"]:+.2f}% EV={c["ev_pct"]:+.2f}% books={c["book_consensus"]}')

    log(f'[filter] {len(qualifying)} candidate(s) cleared all filters '
        f'(edge≥{EDGE_THRESHOLD_PCT}%, odds∈[{ODDS_RANGE_MIN},{ODDS_RANGE_MAX}])')

    now_iso = datetime.now(timezone.utc).isoformat()

    if not qualifying:
        reason = (f'No candidate met edge ≥ {EDGE_THRESHOLD_PCT}%. '
                  f'Scanned {len(candidates)} (game,market,side) tuples.')
        write_picks_json([], reason, now_iso)
        send_telegram(f'🔮 Oracle: No bets today — {reason}')
        hub_post('oracle', 'status', reason, tags=['betting'])
        log('=== Oracle bot run complete (no picks) ===')
        return

    # Rank + dedupe games (one pick per game), take MAX_PICKS_PER_DAY
    ranked = rank_candidates(qualifying)
    slate: list = []
    used_games: set = set()
    for c in ranked:
        game_key = (c['home_team'], c['away_team'], c['commence_time'])
        if game_key in used_games:
            log(f'[skip] {c["label"]} ({c["away_team"]} @ {c["home_team"]}): '
                f'game already chosen for higher-EV pick')
            continue
        stake_info = size_pick(bankroll, c['edge_pct'], c['best_odds'])
        slate.append(candidate_to_pick(c, stake_info, now_iso))
        used_games.add(game_key)
        if len(slate) >= MAX_PICKS_PER_DAY:
            break

    write_picks_json(slate, None, now_iso)
    append_to_resolved(slate)
    log(f'[slate] wrote {len(slate)} pick(s)')

    # Telegram
    lines = [f'🔮 Oracle slate — {now_iso[:10]}',
             f'Bankroll: ${bankroll:.2f}  •  picks: {len(slate)}/{MAX_PICKS_PER_DAY}']
    for rec in slate:
        lines.append(f'• {rec["pick"]} @ {rec["odds"]} '
                     f'[{rec["bet_type"]}, edge {rec["edge_pct"]:+.2f}%, '
                     f'EV {rec["ev_pct"]:+.2f}%, ${rec["stake"]:.2f}]')
        lines.append(f'    {rec["reasoning"]}')
    send_telegram(wrap_message('oracle', '\n'.join(lines)))
    hub_post('oracle', 'picks', f'Posted {len(slate)} straight pick(s).',
             tags=['betting', 'picks'])
    log('=== Oracle bot run complete ===')


if __name__ == '__main__':
    main()
