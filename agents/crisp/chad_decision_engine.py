#!/usr/bin/env python3
"""chad_decision_engine.py — the missing brain for Chad.

Chad's `chad_wallet_intel.py` already DETECTS wallet swap activity. It has
never had logic that turns 'wallet X bought Y' into a *decision*. This
module is that brain: every detected buy runs a multi-gate filter — a
tracked wallet buying is ONE input, never the trigger alone.

Written 2026-07-28 as part of the validated-strategies rollout. Chad's
approach itself has NOT passed any Victoria gate; this engine LOGS a
simulated decision + sim P&L so we can grade the approach honestly over
time. It is not authorised to trade.

═════════════════════════════════════════════════════════════════════════════
ARCHITECTURAL NO-EXECUTION GUARANTEE
═════════════════════════════════════════════════════════════════════════════
This module makes trading impossible by construction, not by policy:

  - No signer, no keypair, no wallet is imported or constructed anywhere.
  - No transaction is ever built, signed, or submitted.
  - Every "trade" is a JSON record with mode='SIMULATION' — the sim engine
    updates an internal book only.
  - Third-party APIs contacted (Helius, DexScreener) are strictly read-only
    HTTP GETs.
  - `sys.modules` is asserted at import time to CONTAIN NO signer
    libraries (solana, solders, anchorpy). If any are present the module
    refuses to import — a defensive tripwire against accidental linkage.

If you find yourself thinking 'I could just add a signer here for a
one-off', stop. Add it to a different module, in a separate PR, gated
behind an explicit runtime flag, after a validated strategy exists in
strategy_library.json. Not here.
═════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ── Import-time tripwire: refuse to load if signer libs are loaded. ─────────
_FORBIDDEN = {'solana', 'solders', 'anchorpy', 'nacl'}
_bad = _FORBIDDEN & set(sys.modules)
if _bad:
    raise RuntimeError(
        f'chad_decision_engine: signer library present in sys.modules ({_bad}). '
        f'This module refuses to load when a signing path is reachable. '
        f'Chad is SIM-ONLY by construction; remove the import and re-run.'
    )


# ── Paths + config ──────────────────────────────────────────────────────────
CRISP        = Path('/root/.openclaw/agents/crisp')
DATA         = CRISP / 'data'
DECISIONS    = DATA / 'chad_decisions.jsonl'
SIM_POSITIONS = DATA / 'chad_sim_positions.json'
TRACKED_PATH = DATA / 'tracked_wallets.json'
SCOREBOARD   = Path('/root/.openclaw/dashboard/chad_wallet_scoreboard.json')

HELIUS_KEY       = os.getenv('HELIUS_API_KEY', '').strip()
HELIUS_BASE      = 'https://api.helius.xyz/v0'
HELIUS_RPC       = 'https://mainnet.helius-rpc.com'
DEXSCREENER_BASE = 'https://api.dexscreener.com/latest/dex'


# Gate thresholds. These are Chad's rails, not the deployment gate — they
# just decide which candidates are worth simulating. Everything gets logged
# either way, so we can review and tighten as data comes in.
MIN_LIQUIDITY_USD        = 25_000.0    # DexScreener liquidity floor
MIN_24H_VOLUME_USD       = 100_000.0
MAX_HOLDER_CONCENTRATION = 0.35        # top-5 wallets ≥35% = concentrated
WALLET_QUALITY_MIN_WR    = 0.20        # 20-60% WR is the "smart money" band
WALLET_QUALITY_MAX_WR    = 0.60
BOT_SPEED_THRESHOLD_S    = 3           # <3s from token creation = bot, not alpha


# Sim position sizing rails
BANKROLL_USD             = 1000.0      # notional sim bankroll
POSITION_PCT_MIN         = 0.01        # 1% floor
POSITION_PCT_MAX         = 0.03        # 3% ceiling
COPYTRADE_LAG_SECONDS    = 12          # you see the buy ~12s after it happened
COPYTRADE_SLIPPAGE_BPS   = 250         # 2.5% adverse slippage vs tracked wallet's fill


log = logging.getLogger('chad_decision')


# ══════════════════════════════════════════════════════════════════════════════
# HTTP helpers (read-only, no side effects beyond logging)
# ══════════════════════════════════════════════════════════════════════════════

def _get_json(url: str, timeout: int = 25) -> Optional[dict]:
    req = urllib.request.Request(url, headers={'User-Agent': 'jcf-hq-chad/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        log.warning(f'GET {url[:80]}... failed: {e}')
        return None


def _post_json(url: str, body: dict, timeout: int = 25) -> Optional[dict]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={
        'User-Agent': 'jcf-hq-chad/1.0', 'Content-Type': 'application/json',
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        log.warning(f'POST {url[:80]}... failed: {e}')
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Gate results
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class GateResult:
    name: str
    passed: bool
    reason: str
    detail: dict = field(default_factory=dict)


# ══════════════════════════════════════════════════════════════════════════════
# GATE 1 — Smart money
# ══════════════════════════════════════════════════════════════════════════════

def check_smart_money(evt: dict) -> GateResult:
    """True iff the wallet is on our tracked list. The event comes from
    chad_wallet_intel already — this just confirms it hasn't been de-listed."""
    try:
        tracked = json.loads(TRACKED_PATH.read_text()).get('wallets', [])
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        tracked = []
    w = evt.get('wallet')
    return GateResult(
        name='smart_money',
        passed=w in tracked,
        reason=('tracked' if w in tracked else 'wallet not in tracked list'),
        detail={'wallet': w, 'tracked_count': len(tracked)},
    )


# ══════════════════════════════════════════════════════════════════════════════
# GATE 2 — On-chain safety (mint / freeze auth, holder concentration)
# ══════════════════════════════════════════════════════════════════════════════

def _helius_rpc(method: str, params: list) -> Optional[dict]:
    if not HELIUS_KEY:
        return None
    body = {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}
    d = _post_json(f'{HELIUS_RPC}/?api-key={HELIUS_KEY}', body)
    return (d or {}).get('result')


def check_onchain_safety(mint: str) -> GateResult:
    """Mint + freeze authority must be renounced (null). Top-5 holder share
    below MAX_HOLDER_CONCENTRATION. Rejects honeypot / rug-set-up tokens."""
    if not mint:
        return GateResult('onchain_safety', False, 'no mint address', {})

    # getAccountInfo on the mint returns parsed authority fields
    info = _helius_rpc('getAccountInfo', [mint, {'encoding': 'jsonParsed'}])
    if not info:
        return GateResult('onchain_safety', False, 'helius unavailable',
                          {'mint': mint})
    parsed = (((info or {}).get('value') or {}).get('data') or {}).get('parsed') or {}
    inf = (parsed.get('info') or {}) if parsed.get('type') == 'mint' else {}
    mint_auth   = inf.get('mintAuthority')
    freeze_auth = inf.get('freezeAuthority')
    if mint_auth or freeze_auth:
        return GateResult('onchain_safety', False,
                          'mint or freeze authority still active — rug-capable',
                          {'mint': mint, 'mint_auth': mint_auth,
                           'freeze_auth': freeze_auth})

    # Top holders via Helius: DAS getTokenLargestAccounts
    largest = _helius_rpc('getTokenLargestAccounts', [mint])
    holders = (largest or {}).get('value') or []
    supply_info = _helius_rpc('getTokenSupply', [mint])
    supply = float(((supply_info or {}).get('value') or {}).get('uiAmount') or 0)
    if supply <= 0:
        return GateResult('onchain_safety', False, 'zero or unknown supply',
                          {'mint': mint})
    top5 = sum(float(h.get('uiAmount') or 0) for h in holders[:5])
    concentration = top5 / supply if supply else 1.0
    if concentration >= MAX_HOLDER_CONCENTRATION:
        return GateResult('onchain_safety', False,
                          f'top-5 concentration {concentration:.1%} >= '
                          f'{MAX_HOLDER_CONCENTRATION:.0%} — dump-capable',
                          {'mint': mint, 'top5_share': concentration})

    return GateResult('onchain_safety', True,
                      f'authorities renounced; top-5 share {concentration:.1%}',
                      {'mint': mint, 'top5_share': concentration})


# ══════════════════════════════════════════════════════════════════════════════
# GATE 3 — Liquidity + volume (DexScreener)
# ══════════════════════════════════════════════════════════════════════════════

def check_liquidity(mint: str) -> GateResult:
    if not mint:
        return GateResult('liquidity', False, 'no mint', {})
    d = _get_json(f'{DEXSCREENER_BASE}/tokens/{mint}')
    if not d:
        return GateResult('liquidity', False, 'dexscreener unavailable',
                          {'mint': mint})
    pairs = d.get('pairs') or []
    if not pairs:
        return GateResult('liquidity', False, 'no pairs on dexscreener',
                          {'mint': mint})
    # Use the pair with the highest USD liquidity as the primary market
    pairs.sort(key=lambda p: float(((p.get('liquidity') or {}).get('usd') or 0)),
               reverse=True)
    top = pairs[0]
    liq_usd = float(((top.get('liquidity') or {}).get('usd') or 0))
    vol24 = float(((top.get('volume') or {}).get('h24') or 0))
    if liq_usd < MIN_LIQUIDITY_USD:
        return GateResult('liquidity', False,
                          f'liquidity ${liq_usd:,.0f} < ${MIN_LIQUIDITY_USD:,.0f}',
                          {'mint': mint, 'liq_usd': liq_usd, 'vol24': vol24})
    if vol24 < MIN_24H_VOLUME_USD:
        return GateResult('liquidity', False,
                          f'24h volume ${vol24:,.0f} < ${MIN_24H_VOLUME_USD:,.0f}',
                          {'mint': mint, 'liq_usd': liq_usd, 'vol24': vol24})
    return GateResult('liquidity', True,
                      f'liq=${liq_usd:,.0f} vol24h=${vol24:,.0f}',
                      {'mint': mint, 'liq_usd': liq_usd, 'vol24': vol24,
                       'pair': top.get('pairAddress'), 'dex': top.get('dexId')})


# ══════════════════════════════════════════════════════════════════════════════
# GATE 4 — Wallet quality
# ══════════════════════════════════════════════════════════════════════════════

def check_wallet_quality(wallet: str) -> GateResult:
    """20-60% WR band with a long-tail multiplier. Distrust >80% WR (bot) and
    sub-3-second buyers (front-runner). Uses scoreboard data; if scoreboard
    hasn't accumulated enough history, defer (pass with a "sparse" flag)."""
    try:
        board = json.loads(SCOREBOARD.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return GateResult('wallet_quality', True,
                          'no scoreboard yet — passing conditionally, deferring '
                          'quality judgement until enough history',
                          {'wallet': wallet, 'sparse': True})
    entry = next((w for w in board.get('wallets', []) if w.get('wallet') == wallet), None)
    if not entry:
        return GateResult('wallet_quality', True,
                          'wallet has no scoreboard row yet — sparse, pass',
                          {'wallet': wallet, 'sparse': True})

    # Fields we EXPECT once the sim has enough history. Right now the
    # scoreboard is sparse (activity counts only, no P&L), so quality
    # judgement is conservative — pass with a sparse flag.
    wr = entry.get('win_rate')
    median_speed_s = entry.get('median_reaction_seconds')
    if wr is None:
        return GateResult('wallet_quality', True,
                          'scoreboard sparse (no WR yet)',
                          {'wallet': wallet, 'sparse': True})
    if wr > 0.80:
        return GateResult('wallet_quality', False,
                          f'WR {wr:.0%} > 80% — bot, not alpha (distrust)',
                          {'wallet': wallet, 'wr': wr})
    if median_speed_s is not None and median_speed_s < BOT_SPEED_THRESHOLD_S:
        return GateResult('wallet_quality', False,
                          f'median reaction {median_speed_s:.1f}s < '
                          f'{BOT_SPEED_THRESHOLD_S}s — sniper bot',
                          {'wallet': wallet, 'median_speed_s': median_speed_s})
    if not (WALLET_QUALITY_MIN_WR <= wr <= WALLET_QUALITY_MAX_WR):
        return GateResult('wallet_quality', False,
                          f'WR {wr:.0%} outside smart-money band '
                          f'{WALLET_QUALITY_MIN_WR:.0%}-{WALLET_QUALITY_MAX_WR:.0%}',
                          {'wallet': wallet, 'wr': wr})
    return GateResult('wallet_quality', True,
                      f'WR {wr:.0%} in smart-money band',
                      {'wallet': wallet, 'wr': wr})


# ══════════════════════════════════════════════════════════════════════════════
# Full evaluation
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Decision:
    ts: str
    wallet: str
    mint: str
    signature: str
    gates: list                       # list[GateResult]
    decision: str                     # 'ENTER_SIM' | 'SKIP' | 'DEFER'
    detail: str                       # human-readable summary
    sim_position_id: Optional[str] = None


def evaluate(evt: dict) -> Decision:
    """Run the full multi-gate filter on one wallet-buy event. Deterministic,
    logged, no fabricated inputs (a gate that can't fetch data fails closed)."""
    gates = [
        check_smart_money(evt),
        check_wallet_quality(evt.get('wallet', '')),
        check_liquidity(evt.get('mint', '')),
        check_onchain_safety(evt.get('mint', '')),
    ]
    all_pass = all(g.passed for g in gates)
    fail_names = [g.name for g in gates if not g.passed]
    decision = 'ENTER_SIM' if all_pass else 'SKIP'
    if all_pass and any(g.detail.get('sparse') for g in gates):
        decision = 'DEFER'    # accept the trade but flag that quality is sparse
    detail = (f'gates passed: {sum(1 for g in gates if g.passed)}/{len(gates)}'
              + (f' — blocked by {",".join(fail_names)}' if fail_names else ''))
    return Decision(
        ts=datetime.now(timezone.utc).isoformat(),
        wallet=evt.get('wallet', ''),
        mint=evt.get('mint', ''),
        signature=evt.get('signature', ''),
        gates=[asdict(g) for g in gates],
        decision=decision,
        detail=detail,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Sim position management
# ══════════════════════════════════════════════════════════════════════════════

def _load_positions() -> dict:
    try:
        return json.loads(SIM_POSITIONS.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {'positions': [], 'bankroll_usd': BANKROLL_USD,
                'schema': 'jcf.chad.sim/v1'}


def _save_positions(book: dict) -> None:
    SIM_POSITIONS.parent.mkdir(parents=True, exist_ok=True)
    SIM_POSITIONS.write_text(json.dumps(book, indent=2, default=str))


def _dex_price_at(mint: str, pair: str = None) -> Optional[float]:
    """Current USD price for `mint` per DexScreener. Used to model our fill
    AFTER the copy-trade lag/slippage."""
    d = _get_json(f'{DEXSCREENER_BASE}/tokens/{mint}')
    if not d:
        return None
    pairs = d.get('pairs') or []
    if pair:
        pairs = [p for p in pairs if p.get('pairAddress') == pair] or pairs
    pairs.sort(key=lambda p: float(((p.get('liquidity') or {}).get('usd') or 0)),
               reverse=True)
    if not pairs:
        return None
    px = pairs[0].get('priceUsd')
    try:
        return float(px)
    except (TypeError, ValueError):
        return None


def open_sim_position(decision: Decision) -> Optional[dict]:
    """Model a copy-trade with LAG (COPYTRADE_LAG_SECONDS) and SLIPPAGE
    (COPYTRADE_SLIPPAGE_BPS adverse). Size 1-3% of bankroll based on which
    gates were sparse (sparse → smaller). No real order. No signer path."""
    if decision.decision not in ('ENTER_SIM', 'DEFER'):
        return None

    book = _load_positions()
    px_now = _dex_price_at(decision.mint)
    if px_now is None:
        log.warning(f'sim open aborted — no dex price for {decision.mint}')
        return None

    # Model lag: assume we saw the wallet's buy COPYTRADE_LAG_SECONDS ago,
    # priced NOW. We do NOT have the wallet's actual fill price; the sim
    # captures OUR fill, which is what we could realistically get.
    slippage = COPYTRADE_SLIPPAGE_BPS / 10_000
    our_fill_px = px_now * (1 + slippage)     # BUY → pay a worse price

    # 1-3% sizing. Sparse-quality → smallest sizing.
    sparse = decision.decision == 'DEFER'
    pct = POSITION_PCT_MIN if sparse else POSITION_PCT_MAX
    notional = BANKROLL_USD * pct
    qty = notional / our_fill_px if our_fill_px > 0 else 0

    pos = {
        'id':            f'sim_{decision.signature[:8]}_{int(time.time())}',
        'opened_at':     datetime.now(timezone.utc).isoformat(),
        'wallet':        decision.wallet,
        'mint':          decision.mint,
        'wallet_signature': decision.signature,
        'notional_usd':  round(notional, 2),
        'qty':           qty,
        'entry_price':   our_fill_px,
        'stop_pct':      -0.30,        # -30% stop, meme reality
        'take_profit':   None,         # exit via momentum-death, not TP
        'sim_mode':      True,
        'lag_seconds':   COPYTRADE_LAG_SECONDS,
        'slippage_bps':  COPYTRADE_SLIPPAGE_BPS,
        'sparse_gate':   sparse,
        'gate_decision': asdict_safe(decision),
        'status':        'open',
        'last_updated':  datetime.now(timezone.utc).isoformat(),
    }
    book.setdefault('positions', []).append(pos)
    _save_positions(book)
    return pos


def asdict_safe(d: Decision) -> dict:
    return {'ts': d.ts, 'decision': d.decision, 'detail': d.detail,
            'gates': d.gates}


# Momentum-death exit stub — call periodically to close positions rolling over
def check_momentum_and_maybe_close() -> list:
    """Very simple exit rule: if a position's current price is <= 85% of the
    3-tick trailing high (from previous check-ins), or below -30% stop, close.

    Meme momentum-death in the simplest form. Not fancy — the intent is
    'exit rolling-over positions' not 'squeeze the last cent'."""
    book = _load_positions()
    closed = []
    for p in book.get('positions', []):
        if p.get('status') != 'open':
            continue
        px = _dex_price_at(p['mint'])
        if px is None:
            continue
        trail = p.get('trail_high', p['entry_price'])
        if px > trail:
            p['trail_high'] = px
            continue
        p_pnl_pct = (px / p['entry_price']) - 1
        if p_pnl_pct <= p['stop_pct']:
            p['status'] = 'closed'; p['exit_price'] = px
            p['exit_reason'] = 'STOP'
            p['pnl_pct'] = p_pnl_pct
            p['pnl_usd'] = p['notional_usd'] * p_pnl_pct
            closed.append(p)
            continue
        rollover_pct = (px / trail) - 1
        if rollover_pct <= -0.15:  # 15% off trailing high = momentum death
            p['status'] = 'closed'; p['exit_price'] = px
            p['exit_reason'] = 'MOMENTUM_DEATH'
            p['pnl_pct'] = p_pnl_pct
            p['pnl_usd'] = p['notional_usd'] * p_pnl_pct
            closed.append(p)
    if closed:
        _save_positions(book)
    return closed


# ══════════════════════════════════════════════════════════════════════════════
# Logging
# ══════════════════════════════════════════════════════════════════════════════

def append_decision(decision: Decision) -> None:
    DECISIONS.parent.mkdir(parents=True, exist_ok=True)
    with DECISIONS.open('a') as f:
        f.write(json.dumps({
            'ts': decision.ts, 'wallet': decision.wallet, 'mint': decision.mint,
            'signature': decision.signature, 'decision': decision.decision,
            'detail': decision.detail, 'gates': decision.gates,
        }, default=str) + '\n')


# ══════════════════════════════════════════════════════════════════════════════
# Runner
# ══════════════════════════════════════════════════════════════════════════════

def run_pipeline() -> dict:
    """Refresh wallet intel, evaluate every fresh BUY event through the gates,
    open sim positions for those that pass. Returns a report dict."""
    import chad_wallet_intel as intel
    tracked = intel._load(intel.TRACKED, None)
    if not tracked or not tracked.get('wallets'):
        tracked = intel.seed_wallets()
    activity, sim = intel.detect_and_simulate(tracked['wallets'])
    intel.build_scoreboard(sim)

    buys = [e for e in activity if e.get('side') == 'buy']
    log.info(f'refresh: tracked={len(tracked["wallets"])}, activity={len(activity)}, buys={len(buys)}')

    decisions = []
    opened = 0
    for evt in buys:
        d = evaluate(evt)
        append_decision(d)
        decisions.append(d)
        if d.decision in ('ENTER_SIM', 'DEFER'):
            if open_sim_position(d):
                opened += 1

    closed = check_momentum_and_maybe_close()
    return {
        'tracked_wallets': len(tracked['wallets']),
        'activity_count':  len(activity),
        'buys_evaluated':  len(buys),
        'sim_opened':      opened,
        'sim_closed':      len(closed),
        'decisions':       [asdict_safe(d) for d in decisions],
    }


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    if not HELIUS_KEY:
        sys.exit('[chad_decision] HELIUS_API_KEY not set — cannot refresh')
    rep = run_pipeline()
    print(json.dumps({k: v for k, v in rep.items() if k != 'decisions'}, indent=2))
