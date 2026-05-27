#!/usr/bin/env python3
"""
oracle_resolver.py — Unified Oracle pick resolver.

Walks oracle_resolved.json. Retries any pick with status in {'pending','stale'}
and result='pending':
  1. For each leg, fetch the final score:
     a. If the game is within the Odds API window (≤3 days old) try Odds API first.
     b. Otherwise (or on Odds API miss) fall back to Claude web_search.
     A per-leg cache prevents re-calling Claude for legs shared across picks.
  2. Grade the pick: straight → WIN|LOSS|PUSH; parlay → WIN iff every leg WIN.
  3. Successful resolution sets status='resolved', result, actual_score,
     resolved_at, resolved_by, realized_pnl (and pnl_realized for legacy
     consumers).
  4. Legs that even Claude can't return mark the whole pick
     status='unresolvable' (terminal — never retried) with unresolvable_reason.
  5. Update bankroll, send Telegram, hub post.

Run manually:
    python3 /root/.openclaw/scripts/oracle_resolver.py
    python3 /root/.openclaw/scripts/oracle_resolver.py --backfill   # process all
    python3 /root/.openclaw/scripts/oracle_resolver.py --limit 50   # cap calls

Cron: 0 */2 * * *
"""

import json
import os
import re
import sys
import time
import requests

from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher

sys.path.insert(0, '/root/.openclaw/scripts')
from telegram_personalities import wrap_message
from odds_api_keys import make_odds_request, refresh_quotas, BASE_URL
from hub_post import add_hub_message as hub_post

RESOLVED_PATH  = '/root/.openclaw/dashboard/oracle_resolved.json'
PICKS_PATH     = '/root/.openclaw/dashboard/oracle_picks.json'
BANKROLL_PATH  = '/root/.openclaw/dashboard/oracle_bankroll.json'

STALE_DAYS     = 7
SIM_THRESHOLD  = 0.62      # team-name fuzzy-match threshold


# ─── Env loader ────────────────────────────────────────────────────────────────
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


# ─── Telegram ──────────────────────────────────────────────────────────────────
def send_telegram(msg):
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT_ID):
        return
    try:
        requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={'chat_id': TELEGRAM_CHAT_ID, 'text': msg},
            timeout=10,
        )
    except Exception as e:
        print(f'[telegram] {e}')


# ─── Name matching ─────────────────────────────────────────────────────────────
def name_sim(a, b):
    a, b = (a or '').lower().strip(), (b or '').lower().strip()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    a_words = a.split()
    b_words = b.split()
    if a_words and b_words and a_words[-1] == b_words[-1]:
        return 0.92
    return SequenceMatcher(None, a, b).ratio()


# ─── Odds API: scores fetch ────────────────────────────────────────────────────
def fetch_scores_for_sports(sport_keys):
    """Returns dict: {sport_key: [completed_game_dicts]}. daysFrom=3 max."""
    out = {}
    for sk in sport_keys:
        url = f'{BASE_URL}/sports/{sk}/scores/'
        data, _ = make_odds_request(url, {'daysFrom': 3, 'dateFormat': 'iso'})
        if data is None:
            out[sk] = []
        else:
            out[sk] = [g for g in data if g.get('completed')]
    return out


def find_game(home_team, away_team, commence_iso, candidates):
    """Match a leg to a completed game in candidates (within 18h, both teams >= SIM_THRESHOLD)."""
    try:
        target_dt = datetime.fromisoformat((commence_iso or '').replace('Z', '+00:00'))
    except Exception:
        target_dt = None

    best_score = 0.0
    best_game  = None
    for g in candidates:
        try:
            g_dt = datetime.fromisoformat((g.get('commence_time') or '').replace('Z', '+00:00'))
        except Exception:
            continue
        if target_dt and abs((g_dt - target_dt).total_seconds()) > 64800:  # 18h
            continue
        h_sim = name_sim(home_team, g.get('home_team', ''))
        a_sim = name_sim(away_team, g.get('away_team', ''))
        # both teams must reasonably match — guards against same-day cross-game mismatches
        if h_sim < SIM_THRESHOLD or a_sim < SIM_THRESHOLD:
            continue
        score = h_sim + a_sim
        if score > best_score:
            best_score = score
            best_game  = g
    return best_game


def parse_scores(game):
    """Return (home_score, away_score) ints from a completed game dict, or (None, None)."""
    scores = game.get('scores') or []
    home_team = game.get('home_team', '')
    home_s, away_s = None, None
    for entry in scores:
        try:
            n  = entry.get('name', '')
            sc = int(float(entry.get('score', 0)))
        except Exception:
            continue
        if name_sim(n, home_team) >= 0.9:
            home_s = sc
        else:
            away_s = sc
    return home_s, away_s


# ─── Codex web-search fallback ─────────────────────────────────────────────────
import subprocess

_PRIMARY_MODEL  = 'openai/gpt-5.3-codex'
_FALLBACK_MODEL = 'openai/gpt-5.5'


def _run_agent(prompt, model=_PRIMARY_MODEL, timeout=60):
    """Run a prompt through the openclaw gateway agent. Returns response text or None."""
    cmd = [
        'openclaw', 'agent',
        '--agent', 'oracle',
        '--model', model,
        '--message', prompt,
        '--json',
        '--timeout', str(timeout),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 15)
        if proc.returncode != 0:
            return None
        result = json.loads(proc.stdout)
        payloads = result.get('result', {}).get('payloads', [])
        return payloads[0].get('text', '') if payloads else None
    except Exception:
        return None


def claude_get_score(home_team, away_team, commence_iso):
    """
    Ask Codex to web_search the final score. Returns (home_score, away_score, source_note)
    or (None, None, error_note).
    """
    date_str = (commence_iso or '')[:10]
    prompt = (
        f'Find the final score of {away_team} at {home_team} on {date_str}. '
        f'Use web_search. Reply with ONLY a JSON object on one line: '
        f'{{"home_score": <int>, "away_score": <int>, "source": "<short citation>"}}. '
        f'If you cannot find the result with confidence, reply: '
        f'{{"home_score": null, "away_score": null, "source": "not_found"}}.'
    )
    for model in (_PRIMARY_MODEL, _FALLBACK_MODEL):
        text = _run_agent(prompt, model=model)
        if text is None:
            continue
        try:
            m = re.search(r'\{[^{}]*\}', text)
            if not m:
                continue
            parsed = json.loads(m.group(0))
            h = parsed.get('home_score')
            a = parsed.get('away_score')
            if isinstance(h, int) and isinstance(a, int):
                return h, a, parsed.get('source', 'codex_web')
            return None, None, parsed.get('source', 'unknown')
        except Exception:
            continue
    return None, None, 'codex_exhausted'


# ─── Grading ───────────────────────────────────────────────────────────────────
def grade_leg(leg, home_score, away_score):
    """
    leg has fields: market ('h2h' | 'spreads' | 'totals'),
                    side  ('home' | 'away' | 'over' | 'under'),
                    line  (float, optional for h2h).
    Returns 'WIN' | 'LOSS' | 'PUSH'.
    """
    market = leg.get('market', 'h2h').lower()
    side   = leg.get('side', '').lower()
    line   = leg.get('line')

    if market == 'h2h':
        if home_score == away_score:
            return 'PUSH'
        winner = 'home' if home_score > away_score else 'away'
        return 'WIN' if side == winner else 'LOSS'

    if market == 'spreads':
        try:
            line = float(line)
        except Exception:
            return 'LOSS'
        # 'home' picked at +/-line: home covers if (home + line) > away
        margin = (home_score + line) - away_score if side == 'home' else (away_score + line) - home_score
        if margin > 0:
            return 'WIN'
        if margin == 0:
            return 'PUSH'
        return 'LOSS'

    if market == 'totals':
        try:
            line = float(line)
        except Exception:
            return 'LOSS'
        total = home_score + away_score
        if total == line:
            return 'PUSH'
        if side == 'over':
            return 'WIN' if total > line else 'LOSS'
        return 'WIN' if total < line else 'LOSS'

    return 'LOSS'


# ─── PnL ───────────────────────────────────────────────────────────────────────
def calc_payout(stake, american_odds):
    """Profit (not including stake) for a winning bet at the given American odds."""
    try:
        o = int(str(american_odds).replace('+', '').strip())
    except Exception:
        return 0.0
    if o > 0:
        return round(stake * o / 100.0, 2)
    return round(stake * 100.0 / abs(o), 2)


# ─── Bankroll ──────────────────────────────────────────────────────────────────
def load_bankroll():
    try:
        with open(BANKROLL_PATH) as f:
            d = json.load(f)
        return float(d.get('balance', 500.0)), float(d.get('starting', 500.0))
    except Exception:
        return 500.0, 500.0


def save_bankroll(balance, starting):
    with open(BANKROLL_PATH, 'w') as f:
        json.dump({
            'balance':  round(balance, 2),
            'starting': round(starting, 2),
            'updated':  datetime.now(timezone.utc).isoformat(),
        }, f, indent=2)


# ─── Sport key helpers ─────────────────────────────────────────────────────────
def sport_keys_from_pick(pick):
    """Return list of Odds API sport keys to search for the pick's games."""
    sport = (pick.get('sport') or '').upper()
    mapping = {
        'NBA':    ['basketball_nba'],
        'NFL':    ['americanfootball_nfl'],
        'MLB':    ['baseball_mlb'],
        'NHL':    ['icehockey_nhl'],
        'NCAAB':  ['basketball_ncaab'],
        'TENNIS': [],   # filled at runtime via active sports
    }
    if sport in mapping:
        return mapping[sport]
    # Parlay or unknown → try everything
    return ['basketball_nba', 'baseball_mlb', 'icehockey_nhl', 'americanfootball_nfl', 'basketball_ncaab']


# ─── Pick → list of legs (uniform shape) ───────────────────────────────────────
def parse_legacy_leg(leg):
    """
    Parse a legacy leg (no structured home_team/away_team) into the same
    shape as the new schema. Expects:
      - game:    "AWAY @ HOME"
      - pick:    "Team (ML)" | "Team +1.5 (SPREAD)" | "OVER 8.5 (TOTAL)" | "UNDER 220.5 (TOTAL)"
      - bet_type: ML | SPREAD | TOTAL
      - odds:    int (american)
      - commence: iso str
    Returns the leg dict or None if unparseable.
    """
    game_str = leg.get('game') or ''
    if ' @ ' not in game_str:
        return None
    away, home = game_str.split(' @ ', 1)
    away, home = away.strip(), home.strip()
    bet_type = (leg.get('bet_type') or '').upper()
    pick_str = (leg.get('pick') or '').strip()

    market, side, line = None, None, None
    if bet_type == 'ML':
        market = 'h2h'
        # pick looks like "Team Name (ML)"
        team_in_pick = re.sub(r'\s*\(ML\)\s*$', '', pick_str).strip()
        if name_sim(team_in_pick, home) >= name_sim(team_in_pick, away):
            side = 'home'
        else:
            side = 'away'
    elif bet_type == 'SPREAD':
        market = 'spreads'
        # pick: "Team +1.5 (SPREAD)" or "Team -3.5 (SPREAD)"
        m = re.match(r'^(.*?)\s+([+-]?\d+(?:\.\d+)?)\s*\(SPREAD\)\s*$', pick_str)
        if not m:
            return None
        team_in_pick, line_str = m.group(1).strip(), m.group(2)
        try:
            line = float(line_str)
        except ValueError:
            return None
        if name_sim(team_in_pick, home) >= name_sim(team_in_pick, away):
            side = 'home'
        else:
            side = 'away'
    elif bet_type in ('TOTAL', 'TOTALS'):
        market = 'totals'
        m = re.match(r'^(OVER|UNDER)\s+(\d+(?:\.\d+)?)\s*\(TOTAL\)?\s*$', pick_str, re.I)
        if not m:
            return None
        side = m.group(1).lower()
        try:
            line = float(m.group(2))
        except ValueError:
            return None
    else:
        return None

    return {
        'home_team':     home,
        'away_team':     away,
        'commence':      leg.get('commence_time') or leg.get('commence'),
        'market':        market,
        'side':          side,
        'line':          line,
        'american_odds': leg.get('odds'),
        'label':         pick_str or f'{home} vs {away}',
    }


def normalise_legs(pick):
    """
    Returns list of leg dicts each with keys:
      home_team, away_team, commence, market, side, line, american_odds, label.
    Straight pick → 1 leg. Parlay → N legs.
    Falls back to legacy "game"/"pick"/"bet_type" parsing for pre-rebuild picks.
    Returns [] if pick has no resolvable structure.
    """
    if pick.get('type') == 'parlay' and pick.get('legs'):
        out = []
        for leg in pick['legs']:
            ht = leg.get('home_team')
            at = leg.get('away_team')
            if ht and at:
                out.append({
                    'home_team':   ht,
                    'away_team':   at,
                    'commence':    leg.get('commence_time') or leg.get('commence'),
                    'market':      leg.get('market', 'h2h'),
                    'side':        leg.get('side'),
                    'line':        leg.get('line'),
                    'american_odds': leg.get('odds'),
                    'label':       leg.get('pick', f'{ht} vs {at}'),
                })
            else:
                legacy = parse_legacy_leg(leg)
                if legacy is None:
                    return []
                out.append(legacy)
        return out
    # Straight — new schema first
    ht = pick.get('home_team')
    at = pick.get('away_team')
    if ht and at:
        return [{
            'home_team':   ht,
            'away_team':   at,
            'commence':    pick.get('commence_time') or pick.get('commence'),
            'market':      pick.get('market', 'h2h'),
            'side':        pick.get('side'),
            'line':        pick.get('line'),
            'american_odds': pick.get('best_odds') or pick.get('odds'),
            'label':       pick.get('pick', f'{ht} vs {at}'),
        }]
    # Straight — legacy schema fallback
    legacy = parse_legacy_leg(pick)
    return [legacy] if legacy else []


# ─── Per-leg resolution ────────────────────────────────────────────────────────
ODDS_API_WINDOW_DAYS = 3   # Odds API /scores endpoint only returns daysFrom≤3


def _leg_age_days(leg, now_utc):
    try:
        gdt = datetime.fromisoformat((leg.get('commence') or '').replace('Z', '+00:00'))
    except Exception:
        return None
    return (now_utc - gdt).total_seconds() / 86400.0


def resolve_leg(leg, sports_cache, score_cache, now_utc):
    """
    Returns (result_str, actual_score_str, source) where result_str in
    {'WIN','LOSS','PUSH','UNRESOLVED'}.

    Per-leg score cache (keyed by lowercased team names + commence date) keeps
    Claude calls cheap when many picks share a leg.
    """
    home = (leg.get('home_team') or '').strip()
    away = (leg.get('away_team') or '').strip()
    cache_key = (home.lower(), away.lower(), (leg.get('commence') or '')[:10])

    if cache_key in score_cache:
        h, a, src = score_cache[cache_key]
    else:
        age_days = _leg_age_days(leg, now_utc)
        odds_api_eligible = age_days is None or age_days <= ODDS_API_WINDOW_DAYS

        h, a, src = None, None, None
        if odds_api_eligible:
            for sk in sports_cache.keys():
                game = find_game(home, away, leg.get('commence'), sports_cache[sk])
                if not game:
                    continue
                gh, ga = parse_scores(game)
                if gh is None or ga is None:
                    continue
                h, a, src = gh, ga, 'odds_api'
                break

        # Fall back to Claude for old games or Odds API misses
        if h is None:
            ch, ca, note = claude_get_score(home, away, leg.get('commence'))
            if ch is not None:
                h, a, src = ch, ca, 'claude_web_search'
            else:
                src = f'claude:{note}'

        score_cache[cache_key] = (h, a, src)

    if h is None:
        return ('UNRESOLVED', '', src or 'no_source')
    result = grade_leg(leg, h, a)
    return (result, f'{home} {h} {away} {a}', src)


# ─── Main ──────────────────────────────────────────────────────────────────────
def main():
    # CLI: --backfill (no Telegram per-pick) | --limit N (cap calls this run)
    backfill = '--backfill' in sys.argv
    limit    = None
    for i, a in enumerate(sys.argv):
        if a == '--limit' and i + 1 < len(sys.argv):
            try: limit = int(sys.argv[i + 1])
            except ValueError: pass

    refresh_quotas()
    with open(RESOLVED_PATH) as f:
        ledger = json.load(f)

    picks = ledger.get('picks', [])

    # Retry both pending and previously-stale picks. result must still be 'pending'
    # — once a pick is graded (WIN/LOSS/PUSH) we never touch it again.
    candidates = [
        p for p in picks
        if p.get('status') in ('pending', 'stale')
        and p.get('result') == 'pending'
    ]
    if not candidates:
        print('[resolver] No pending or stale picks. Nothing to do.')
        return

    if limit is not None:
        candidates = candidates[:limit]
    print(f'[resolver] {len(candidates)} candidate(s) (backfill={backfill}, limit={limit})')

    # Pre-fetch Odds API scores only for sports we'll actually need
    needed_sports = set()
    for p in candidates:
        for sk in sport_keys_from_pick(p):
            needed_sports.add(sk)
    sports_cache = fetch_scores_for_sports(sorted(needed_sports))
    for sk, games in sports_cache.items():
        print(f'[scores] {sk}: {len(games)} completed games (≤3d window)')

    balance, starting = load_bankroll()
    now = datetime.now(timezone.utc)
    score_cache: dict = {}   # (home_lc, away_lc, date10) -> (h, a, source)

    resolved_count    = 0
    unresolvable_count= 0
    summary_lines     = []

    for pick in candidates:
        legs = normalise_legs(pick)
        if not legs:
            # No structured legs and no legacy parseable shape — terminal.
            pick['status']               = 'unresolvable'
            pick['unresolvable_reason']  = 'no_structured_legs'
            pick['resolved_at']          = now.isoformat()
            # Clean up legacy stale markers
            pick.pop('stale_reason', None)
            unresolvable_count += 1
            continue

        # Resolve every leg
        leg_results, actual_scores, sources = [], [], []
        for leg in legs:
            res, score, src = resolve_leg(leg, sports_cache, score_cache, now)
            leg_results.append(res)
            actual_scores.append(score)
            sources.append(src)

        # If any leg is still UNRESOLVED, mark terminal — never retry.
        if 'UNRESOLVED' in leg_results:
            pick['status']              = 'unresolvable'
            pick['unresolvable_reason'] = 'leg_unresolvable'
            pick['unresolved_legs']     = [
                legs[i].get('label', '') for i, r in enumerate(leg_results) if r == 'UNRESOLVED'
            ]
            pick['unresolved_sources']  = sources
            pick['resolved_at']         = now.isoformat()
            pick.pop('stale_reason', None)
            unresolvable_count += 1
            if not backfill:
                send_telegram(f'⚠️ Could not resolve {pick.get("pick","")} — marked unresolvable')
            continue

        # Grade overall pick
        if pick.get('type') == 'parlay':
            if any(r == 'LOSS' for r in leg_results):
                final_result = 'LOSS'
            elif all(r == 'PUSH' for r in leg_results):
                final_result = 'PUSH'
            else:
                final_result = 'WIN'
            odds_for_pnl = pick.get('combined_odds') or pick.get('odds') or '+100'
        else:
            final_result = leg_results[0]
            odds_for_pnl = pick.get('best_odds') or pick.get('odds') or '+100'

        stake = float(pick.get('stake') or 10)
        if final_result == 'WIN':
            pnl = calc_payout(stake, odds_for_pnl)
        elif final_result == 'LOSS':
            pnl = -stake
        else:
            pnl = 0.0

        balance += pnl
        pick['status']        = 'resolved'
        pick['result']        = final_result
        pick['actual_score']  = ' | '.join(actual_scores)
        pick['legs_result']   = leg_results if pick.get('type') == 'parlay' else None
        pick['resolved_at']   = now.isoformat()
        pick['resolved_by']   = sources[0] if len(set(sources)) == 1 else 'mixed'
        pick['realized_pnl']  = round(pnl, 2)   # new canonical field
        pick['pnl_realized']  = round(pnl, 2)   # legacy alias
        # Clean any stale markers from previous runs
        pick.pop('stale_reason', None)
        pick.pop('unresolved_legs', None)
        resolved_count += 1

        icon = '✅ WIN' if final_result == 'WIN' else ('❌ LOSS' if final_result == 'LOSS' else '➡️ PUSH')
        sign = '+' if pnl >= 0 else '-'
        line = f'{icon}: {pick.get("pick","")} {sign}${abs(pnl):.2f} (bankroll: ${balance:.2f})'
        summary_lines.append(line)
        if not backfill:
            send_telegram(wrap_message('oracle', line))
        print(f'[resolver] {line}')

        time.sleep(0.2)   # be polite

    # Persist
    ledger['picks']   = picks
    ledger['updated'] = now.isoformat()
    with open(RESOLVED_PATH, 'w') as f:
        json.dump(ledger, f, indent=2)

    if resolved_count > 0 or unresolvable_count > 0:
        save_bankroll(balance, starting)
        msg = (f'🔮 Oracle resolver: {resolved_count} graded, '
               f'{unresolvable_count} unresolvable. Bankroll: ${balance:.2f}')
        if summary_lines and not backfill:
            msg += '\n' + '\n'.join(summary_lines[:10])
        if not backfill:
            hub_post('oracle', 'status', msg, tags=['betting', 'resolution'])
        print(msg)
    else:
        print('[resolver] No state changes this run.')


if __name__ == '__main__':
    main()
