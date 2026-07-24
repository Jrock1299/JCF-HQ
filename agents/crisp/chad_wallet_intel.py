#!/usr/bin/env python3
"""
chad_wallet_intel.py — Chad's wallet intelligence (Phase 2, SIMULATION ONLY).

Reads REAL Solana on-chain data via the Helius Enhanced Transactions API to:
  1. Seed / maintain a tracked-wallet list (Helius has NO "top traders" endpoint,
     so we seed from real recent pump.fun SWAP feePayers — reported transparently).
  2. Detect recent buy/sell (SWAP) activity on tracked wallets.
  3. Simulate copy-trades — PAPER ONLY, logged to Chad's sim engine.
  4. Maintain a wallet scoreboard (sparse at first — flagged, never fabricated).

ARCHITECTURAL GUARANTEE — NO EXECUTION: this module only performs HTTP GETs
against Helius (a read-only data/RPC key) and writes local JSON. It holds no
private key, no signer, no wallet, and calls no order/transaction-send path.
Copy-trading is impossible here by construction, not by policy.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HELIUS_KEY = os.getenv('HELIUS_API_KEY', '').strip()
BASE       = 'https://api.helius.xyz/v0'
PUMP_FUN   = '6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P'   # discovery source

CRISP = Path('/root/.openclaw/agents/crisp')
DATA  = CRISP / 'data'
TRACKED = DATA / 'tracked_wallets.json'
SIMLOG  = DATA / 'sim_copy_trades.json'
SCORE   = Path('/root/.openclaw/dashboard/chad_wallet_scoreboard.json')
SEED_N  = 12          # wallets to seed
LOOKBACK = 5          # recent txns to scan per wallet


def _get(url: str, timeout: int = 25):
    # Helius' WAF 403s the default Python-urllib User-Agent — send a real one.
    req = urllib.request.Request(url, headers={'User-Agent': 'jcf-hq-chad/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f'[chad] helius GET error: {e}')
        return None


def _txns(address: str, limit: int = 10, tx_type: str = None):
    q = {'api-key': HELIUS_KEY, 'limit': limit}
    if tx_type:
        q['type'] = tx_type
    url = f'{BASE}/addresses/{address}/transactions?' + urllib.parse.urlencode(q)
    d = _get(url)
    return d if isinstance(d, list) else []


def _load(p, default):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def _save(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2))


def seed_wallets():
    """Seed tracked wallets from real recent pump.fun SWAP feePayers."""
    swaps = _txns(PUMP_FUN, limit=40, tx_type='SWAP')
    seen, wallets = set(), []
    for t in swaps:
        w = t.get('feePayer')
        if w and w not in seen:
            seen.add(w)
            wallets.append(w)
        if len(wallets) >= SEED_N:
            break
    rec = {'seeded_at': datetime.now(timezone.utc).isoformat(),
           'source': 'helius enhanced-txns: recent pump.fun SWAP feePayers '
                     '(no native "top traders" endpoint exists)',
           'wallets': wallets}
    _save(TRACKED, rec)
    return rec


def classify(txn: dict, wallet: str):
    """Return ('buy'|'sell'|None, mint, sol_delta) for `wallet` in a SWAP txn.

    Heuristic: a token the wallet RECEIVES while native SOL leaves = BUY;
    a token the wallet SENDS while SOL comes in = SELL.
    """
    got_token = sent_token = None
    for tt in txn.get('tokenTransfers', []):
        if tt.get('toUserAccount') == wallet:
            got_token = tt.get('mint')
        if tt.get('fromUserAccount') == wallet:
            sent_token = tt.get('mint')
    sol_out = sol_in = 0
    for nt in txn.get('nativeTransfers', []):
        amt = (nt.get('amount') or 0) / 1e9
        if nt.get('fromUserAccount') == wallet:
            sol_out += amt
        if nt.get('toUserAccount') == wallet:
            sol_in += amt
    if got_token and sol_out > 0:
        return ('buy', got_token, -sol_out)
    if sent_token and sol_in > 0:
        return ('sell', sent_token, sol_in)
    return (None, None, 0)


def detect_and_simulate(wallets):
    sim = _load(SIMLOG, [])
    known_sigs = {e['signature'] for e in sim}
    activity = []
    for w in wallets:
        for t in _txns(w, limit=LOOKBACK, tx_type='SWAP'):
            side, mint, sol = classify(t, w)
            if not side:
                continue
            evt = {'wallet': w, 'side': side, 'mint': mint,
                   'sol_delta': round(sol, 4), 'ts': t.get('timestamp'),
                   'signature': t.get('signature'), 'source': t.get('source')}
            activity.append(evt)
            if t.get('signature') not in known_sigs:      # simulate the copy (paper)
                sim.append({**evt, 'mode': 'SIMULATION',
                            'copied_at': datetime.now(timezone.utc).isoformat(),
                            'sim_notional_sol': 0.5})       # fixed paper size
        time.sleep(0.2)                                     # gentle pacing
    _save(SIMLOG, sim)
    return activity, sim


def build_scoreboard(sim):
    """Per-wallet activity counts. Real P&L needs price resolution over time —
    it is intentionally left as pending rather than fabricated."""
    board = {}
    for e in sim:
        b = board.setdefault(e['wallet'], {'buys': 0, 'sells': 0, 'events': 0})
        b['events'] += 1
        b['buys' if e['side'] == 'buy' else 'sells'] += 1
    ranked = sorted(board.items(), key=lambda kv: -kv[1]['events'])
    out = {'generated_at': datetime.now(timezone.utc).isoformat(),
           'note': 'SPARSE — activity counts only. Simulated-performance scoring '
                   'needs multiple runs + price resolution; not enough history yet '
                   'to rank wallets by profitability. Not fabricating early conviction.',
           'wallets': [{'wallet': w, **s, 'sim_pnl': 'pending (insufficient history)'}
                       for w, s in ranked]}
    _save(SCORE, out)
    return out


def chad_report(tracked, activity, board):
    n_w = len(tracked['wallets'])
    n_a = len(activity)
    lines = ['🏎️ CHAD — WALLET INTEL (SIM)',
             datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'), '']
    if n_a:
        lines.append(f"Tracking {n_w} wallets. Caught {n_a} live moves — logged every "
                     "one to the sim, copied none with real money. That's the discipline "
                     "under the flash.")
        for e in activity[:6]:
            short = e['wallet'][:4] + '…' + e['wallet'][-4:]
            mint = (e['mint'] or '?')[:4] + '…'
            lines.append(f"  {short} {e['side'].upper()} {mint} "
                         f"({abs(e['sol_delta'])} SOL) [{e['source']}]")
        lines.append('')
        lines.append("I don't chase these blind. I log 'em, score 'em, and let the sim "
                     "tell me who's smart and who's just lucky.")
    else:
        lines.append(f"Tracking {n_w} fresh wallets — quiet window, no swaps in range "
                     "right now. I show up early and wait; the room always moves eventually.")
    lines.append('')
    lines.append(f"Scoreboard: {len(board['wallets'])} wallets logged. "
                 "Performance ranking is still thin — not enough runs to crown anybody. "
                 "I'll flex numbers when the numbers are real, not before.")
    lines.append('— Chad (simulation only, no execution)')
    return '\n'.join(lines)


def main():
    if not HELIUS_KEY:
        sys.exit('[chad] HELIUS_API_KEY not set')
    tracked = _load(TRACKED, None)
    if not tracked or not tracked.get('wallets'):
        print('[chad] no tracked list — seeding from real pump.fun activity...')
        tracked = seed_wallets()
    print(f"[chad] {len(tracked['wallets'])} tracked wallets ({tracked['source']})")
    activity, sim = detect_and_simulate(tracked['wallets'])
    board = build_scoreboard(sim)
    report = chad_report(tracked, activity, board)
    print('\n' + report)
    return report


if __name__ == '__main__':
    main()
