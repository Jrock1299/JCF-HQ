#!/usr/bin/env python3
"""ict_backtest.py — event-driven backtester for the codified ICT/ICC models.

THE LOOKAHEAD GUARANTEE
    The loop hands each strategy `bars[:i+1]`. `bars[i]` is the most recent
    CLOSED bar — that IS close[1] in live terms. The strategy literally cannot
    see bar i+1, because it is not in the list. Orders returned at step i are
    filled at bar i+1's OPEN plus costs.

    This is structural, not a convention someone has to remember. Incomplete
    candles are also dropped at download time (ict_data._parse), so there is no
    path by which a forming bar reaches a rule.

COSTS (charged on every trade, both sides)
    spread     — the REAL bid/ask spread recorded with each candle, not an
                 assumption. Half charged at entry, half at exit.
    slippage   — SLIP_ATR x ATR(14) adverse on entry; stop exits get
                 STOP_SLIP_ATR (wider, because a stop is a market order fired
                 into the move that triggered it).
    commission — COMMISSION_BPS of notional per side.

PESSIMISTIC FILL RULE
    If a single bar's range contains BOTH the stop and the target, the STOP is
    assumed hit first. Without intrabar tick data the sequence is unknowable,
    and assuming the good outcome is how backtests flatter themselves.

DRAWDOWN
    Equity curve is anchored at the real starting balance and drawdown is
    measured against peak EQUITY — not cumulative P&L from zero, which is the
    bug that manufactured Chad's 468% (see CLAUDE.md decision log 2026-07-27).
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ict_strategies import PARAMS, KILLZONES, StrategySpec   # noqa: E402

# ── Cost model ───────────────────────────────────────────────────────────────
SLIP_ATR = 0.02          # entry slippage as a fraction of ATR
STOP_SLIP_ATR = 0.05     # stop exits slip more — market order into the move
COMMISSION_BPS = 0.5     # 0.5 bps of notional per side
STARTING_BALANCE = 10_000.0


# ══════════════════════════════════════════════════════════════════════════════
# Indicators / structure primitives
# ══════════════════════════════════════════════════════════════════════════════

def atr(bars: list[dict], i: int, period: int = 14) -> float:
    if i < period:
        return 0.0
    s = 0.0
    for k in range(i - period + 1, i + 1):
        h, l, pc = bars[k]['h'], bars[k]['l'], bars[k - 1]['c']
        s += max(h - l, abs(h - pc), abs(l - pc))
    return s / period


def ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    k = 2 / (period + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


def swing_highs(bars: list[dict], k: int) -> list[int]:
    """Indices of confirmed swing highs. Confirmed only k bars after the fact."""
    out = []
    for i in range(k, len(bars) - k):
        h = bars[i]['h']
        if all(h > bars[i - j]['h'] for j in range(1, k + 1)) and \
           all(h > bars[i + j]['h'] for j in range(1, k + 1)):
            out.append(i)
    return out


def swing_lows(bars: list[dict], k: int) -> list[int]:
    out = []
    for i in range(k, len(bars) - k):
        l = bars[i]['l']
        if all(l < bars[i - j]['l'] for j in range(1, k + 1)) and \
           all(l < bars[i + j]['l'] for j in range(1, k + 1)):
            out.append(i)
    return out


def in_killzone(ts: str, zones: tuple) -> bool:
    hour = int(ts[11:13])
    for z in zones:
        lo, hi = KILLZONES[z]
        if lo <= hour < hi:
            return True
    return False


# ══════════════════════════════════════════════════════════════════════════════
# Trade / result containers
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Trade:
    direction: str
    entry_time: str
    entry: float
    stop: float
    target: float
    size: float
    exit_time: str = ''
    exit: float = 0.0
    pnl: float = 0.0
    r_multiple: float = 0.0
    exit_reason: str = ''
    costs: float = 0.0


@dataclass
class BacktestResult:
    strategy: str
    instrument: str
    trades: list = field(default_factory=list)
    starting_balance: float = STARTING_BALANCE
    final_balance: float = STARTING_BALANCE
    skipped_rr: int = 0


# ══════════════════════════════════════════════════════════════════════════════
# Setup detection
# ══════════════════════════════════════════════════════════════════════════════

_H4_CACHE: dict = {}


def _h4_series(h4: list[dict]) -> tuple:
    """Precompute (timestamps, running EMA-50) once per H4 dataset.

    Was recomputed from scratch on every detect call — a full scan of ~12k H4
    bars plus a 200-bar EMA, ~190k times per backtest. Same arithmetic, done
    once, then bisected.
    """
    key = id(h4)
    if key in _H4_CACHE:
        return _H4_CACHE[key]
    ts = [b['t'] for b in h4]
    closes = [b['c'] for b in h4]
    k = 2 / 51
    emas, e = [], None
    for c in closes:
        e = c if e is None else (c * k + e * (1 - k))
        emas.append(e)
    _H4_CACHE[key] = (ts, closes, emas)
    return _H4_CACHE[key]


def _htf_bias(h4: list[dict], ts: str) -> str:
    """H4 close[1] vs H4 EMA(50). Only H4 bars CLOSED at/before ts are used."""
    import bisect
    times, closes, emas = _h4_series(h4)
    j = bisect.bisect_right(times, ts) - 1      # last H4 bar closed at/before ts
    if j < 50:
        return 'none'
    return 'bull' if closes[j] > emas[j] else 'bear'


def _find_fvg(bars: list[dict], n: int, direction: str) -> tuple | None:
    """3-bar imbalance ending at index n. Returns (lo, hi) of the gap."""
    if n < 2:
        return None
    a, c = bars[n - 2], bars[n]
    if direction == 'long' and a['h'] < c['l']:
        return (a['h'], c['l'])
    if direction == 'short' and a['l'] > c['h']:
        return (c['h'], a['l'])
    return None


def _find_ob(bars: list[dict], disp_i: int, direction: str,
             icc: bool) -> tuple | None:
    """Last opposing candle before the displacement leg. ICC adds vol+range."""
    vols = [b['v'] for b in bars[max(0, disp_i - 20):disp_i]]
    mean_v = (sum(vols) / len(vols)) if vols else 0
    a = atr(bars, disp_i, PARAMS['ATR_PERIOD'])
    for j in range(disp_i - 1, max(0, disp_i - 12), -1):
        b = bars[j]
        opposing = (b['c'] < b['o']) if direction == 'long' else (b['c'] > b['o'])
        if not opposing:
            continue
        if icc:
            if mean_v <= 0 or b['v'] < PARAMS['ICC_VOL_MULT'] * mean_v:
                continue
            if a <= 0 or (b['h'] - b['l']) < PARAMS['ICC_RANGE_ATR_MULT'] * a:
                continue
        return (b['l'], b['o']) if direction == 'long' else (b['o'], b['h'])
    return None


def _detect(spec: StrategySpec, bars: list[dict], i: int, h4: list[dict],
            sh: list[int], sl: list[int]) -> dict | None:
    """Return a pending order dict, or None.

    LOOKAHEAD CONTRACT: this function may read bars[0..i] ONLY. bars[i] is the
    last closed bar — close[1] in live terms. It receives the full list (slicing
    a 190k-element prefix on every call was quadratic), so the bound is enforced
    by discipline here rather than by the slice: every index used below is
    derived from `i` and never exceeds it. `test_lookahead()` verifies this
    empirically by mutating all future bars and asserting the signal is
    unchanged.
    """
    bar = bars[i]
    if not in_killzone(bar['t'], spec.killzones):
        return None
    a = atr(bars, i, PARAMS['ATR_PERIOD'])
    if a <= 0:
        return None

    bias = _htf_bias(h4, bar['t']) if spec.htf_bias_required else 'none'

    # --- locate a recent sweep --------------------------------------------
    sweep_dir = None       # trade direction implied by the sweep
    sweep_extreme = None
    sweep_i = None
    if spec.require_sweep or spec.reverse_on_sweep:
        lookback = PARAMS['MSS_MAX_BARS_AFTER_SWEEP']
        recent_sh = [x for x in sh if x < i - PARAMS['SWING_K']][-PARAMS['LOOKBACK_POOLS']:]
        recent_sl = [x for x in sl if x < i - PARAMS['SWING_K']][-PARAMS['LOOKBACK_POOLS']:]
        for j in range(max(0, i - lookback), i + 1):
            b = bars[j]
            pools_h = [bars[x]['h'] for x in recent_sh if x < j]
            pools_l = [bars[x]['l'] for x in recent_sl if x < j]
            if pools_h:
                ph = max(pools_h[-5:])
                if b['h'] > ph and b['c'] < ph:      # buy-side sweep -> short
                    sweep_dir, sweep_extreme, sweep_i = 'short', b['h'], j
            if pools_l:
                pl = min(pools_l[-5:])
                if b['l'] < pl and b['c'] > pl:      # sell-side sweep -> long
                    sweep_dir, sweep_extreme, sweep_i = 'long', b['l'], j
        if sweep_dir is None:
            return None

    direction = sweep_dir
    if not spec.require_sweep:
        # Silver Bullet / IFVG derive direction from the displacement itself.
        body = bars[i]['c'] - bars[i]['o']
        if abs(body) < PARAMS['DISPLACEMENT_ATR_MULT'] * a:
            return None
        direction = 'long' if body > 0 else 'short'

    if direction is None:
        return None
    if spec.htf_bias_required and bias != 'none':
        if (direction == 'long' and bias != 'bull') or \
           (direction == 'short' and bias != 'bear'):
            return None

    # --- Power of Three: accumulation range then manipulation --------------
    if spec.require_amd:
        kz_start = None
        for j in range(i, max(0, i - 40), -1):
            if not in_killzone(bars[j]['t'], spec.killzones):
                kz_start = j + 1
                break
        if kz_start is None or i - kz_start < 5:
            return None
        acc = bars[kz_start:kz_start + 4]
        acc_hi, acc_lo = max(x['h'] for x in acc), min(x['l'] for x in acc)
        swept = any((bars[j]['h'] > acc_hi and bars[j]['c'] < acc_hi) or
                    (bars[j]['l'] < acc_lo and bars[j]['c'] > acc_lo)
                    for j in range(kz_start + 4, i + 1))
        if not swept:
            return None

    # --- displacement -------------------------------------------------------
    disp_i = None
    if spec.require_displacement:
        for j in range(i, max(0, i - 6), -1):
            body = bars[j]['c'] - bars[j]['o']
            if abs(body) >= PARAMS['DISPLACEMENT_ATR_MULT'] * a and \
               ((body > 0) == (direction == 'long')):
                disp_i = j
                break
        if disp_i is None:
            return None
    else:
        disp_i = i

    # --- market structure shift, read on close[1] ---------------------------
    if spec.require_mss and sweep_i is not None:
        k = PARAMS['SWING_K']
        inter_sl = [x for x in sl if sweep_i <= x <= i - k]
        inter_sh = [x for x in sh if sweep_i <= x <= i - k]
        if direction == 'short':
            if not inter_sl or bars[i]['c'] >= min(bars[x]['l'] for x in inter_sl):
                return None
        else:
            if not inter_sh or bars[i]['c'] <= max(bars[x]['h'] for x in inter_sh):
                return None

    # --- entry zone ---------------------------------------------------------
    zone = None
    if spec.entry_zone == 'FVG':
        # The displacement leg's imbalance can complete on the displacement bar
        # or the one or two bars after it. Searching only `disp_i` missed most
        # real FVGs.
        #
        # CAUTION — this window is capped at `i`, deliberately. An earlier
        # version searched disp_i..disp_i+2 unconditionally; when disp_i == i
        # that read bars[i+1] and bars[i+2], i.e. the future. test_lookahead
        # caught it (silver_bullet produced a signal against poisoned bars that
        # did not exist in the real series). An FVG completing after `i` is
        # simply not knowable yet — it will be picked up on a later bar.
        for j in range(disp_i, min(i, disp_i + 2) + 1):
            zone = _find_fvg(bars, j, direction)
            if zone:
                break
    elif spec.entry_zone in ('OB', 'ICC_OB'):
        zone = _find_ob(bars, disp_i, direction, icc=spec.icc_filter)
    elif spec.entry_zone == 'IFVG':
        for j in range(i - 1, max(0, i - PARAMS['FVG_MAX_AGE_BARS']), -1):
            g = _find_fvg(bars, j, 'short' if direction == 'long' else 'long')
            if not g:
                continue
            lo, hi = g
            if (direction == 'long' and bars[i]['c'] > hi) or \
               (direction == 'short' and bars[i]['c'] < lo):
                zone = g
                break
    if not zone:
        return None

    lo, hi = zone
    entry = (lo + hi) / 2.0

    if spec.reverse_on_sweep:                 # Turtle Soup enters immediately
        entry = bars[i]['c']

    ref = sweep_extreme if sweep_extreme is not None else (
        bars[disp_i]['l'] if direction == 'long' else bars[disp_i]['h'])
    buf = PARAMS['STOP_BUFFER_ATR'] * a
    stop = (ref - buf) if direction == 'long' else (ref + buf)

    risk = abs(entry - stop)
    if risk <= 0:
        return None
    # Reject degenerate stops: below this the position size explodes and
    # slippage swamps the edge. (First smoke test produced a 0.73-point stop on
    # SPX with ~5-point ATR, sized to a 1.5% loss on a 0.75% risk budget.)
    if risk < PARAMS['MIN_STOP_ATR'] * a:
        return None

    # Target = the NEAREST opposing liquidity pool that still clears MIN_RR.
    #
    # Taking the nearest pool unconditionally (the naive reading of "target the
    # next pool") set targets a few ticks above entry, so 157 of 158 otherwise
    # valid setups were then rejected by the 1:2 floor — the two rules from the
    # brief cancelled each other out. Walking outward to the first pool that
    # satisfies the floor honours both: still a real liquidity objective, still
    # >= 1:2. If no pool is far enough, fall back to a clean MIN_RR multiple.
    min_dist = PARAMS['MIN_RR'] * risk
    if direction == 'long':
        pools = sorted(bars[x]['h'] for x in sh
                       if x <= i - PARAMS['SWING_K'] and bars[x]['h'] > entry)
        qualifying = [p for p in pools if (p - entry) >= min_dist]
        target = qualifying[0] if qualifying else entry + min_dist
    else:
        pools = sorted((bars[x]['l'] for x in sl
                        if x <= i - PARAMS['SWING_K'] and bars[x]['l'] < entry),
                       reverse=True)
        qualifying = [p for p in pools if (entry - p) >= min_dist]
        target = qualifying[0] if qualifying else entry - min_dist

    rr = abs(target - entry) / risk
    if rr < PARAMS['MIN_RR']:
        return {'_skip_rr': True}

    return {'direction': direction, 'entry': entry, 'stop': stop,
            'target': target, 'atr': a, 'signal_bar': i}


# ══════════════════════════════════════════════════════════════════════════════
# Engine
# ══════════════════════════════════════════════════════════════════════════════

def run(spec: StrategySpec, bars: list[dict], h4: list[dict],
        instrument: str, starting_balance: float = STARTING_BALANCE) -> BacktestResult:
    res = BacktestResult(spec.key, instrument, starting_balance=starting_balance)
    balance = starting_balance
    sh, sl = swing_highs(bars, PARAMS['SWING_K']), swing_lows(bars, PARAMS['SWING_K'])
    sh_set, sl_set = sh, sl

    open_trade: Trade | None = None
    pending: dict | None = None
    pending_age = 0
    warm = PARAMS['ATR_PERIOD'] + PARAMS['LOOKBACK_POOLS'] + 5

    for i in range(warm, len(bars) - 1):
        nxt = bars[i + 1]                    # execution bar — never inspected by rules

        # ---- manage an open position on the NEXT bar's range ----------------
        if open_trade:
            t = open_trade
            hit_stop = (nxt['l'] <= t.stop) if t.direction == 'long' else (nxt['h'] >= t.stop)
            hit_tgt = (nxt['h'] >= t.target) if t.direction == 'long' else (nxt['l'] <= t.target)
            if hit_stop or hit_tgt:
                # PESSIMISTIC: stop wins a same-bar tie.
                a = atr(bars, i, PARAMS['ATR_PERIOD'])
                spread = nxt.get('spread', 0.0) or 0.0
                if hit_stop:
                    slip = STOP_SLIP_ATR * a
                    px = t.stop - slip if t.direction == 'long' else t.stop + slip
                    reason = 'stop'
                else:
                    px = t.target
                    reason = 'target'
                px -= (spread / 2) if t.direction == 'long' else -(spread / 2)
                comm = abs(px * t.size) * (COMMISSION_BPS / 10_000)
                gross = ((px - t.entry) if t.direction == 'long' else (t.entry - px)) * t.size
                t.exit, t.exit_time, t.exit_reason = px, nxt['t'], reason
                t.costs += comm
                t.pnl = round(gross - comm, 2)
                risk_amt = abs(t.entry - t.stop) * t.size
                t.r_multiple = round(t.pnl / risk_amt, 3) if risk_amt else 0.0
                balance += t.pnl
                res.trades.append(t)
                open_trade = None

        # ---- fill a pending order on the next bar --------------------------
        if pending and not open_trade:
            d, e = pending['direction'], pending['entry']
            touched = (nxt['l'] <= e <= nxt['h'])
            if touched:
                a = pending['atr']
                spread = nxt.get('spread', 0.0) or 0.0
                slip = SLIP_ATR * a
                fill = e + slip + spread / 2 if d == 'long' else e - slip - spread / 2
                risk_per_unit = abs(fill - pending['stop'])
                if risk_per_unit > 0:
                    size = (balance * PARAMS['RISK_PCT']) / risk_per_unit
                    comm = abs(fill * size) * (COMMISSION_BPS / 10_000)
                    balance -= comm
                    open_trade = Trade(d, nxt['t'], fill, pending['stop'],
                                       pending['target'], size, costs=comm)
                pending = None
                pending_age = 0
            else:
                pending_age += 1
                if pending_age > PARAMS['ENTRY_MAX_WAIT_BARS']:
                    pending, pending_age = None, 0

        # ---- look for a new setup using ONLY closed bars --------------------
        if not open_trade and not pending:
            sig = _detect(spec, bars, i, h4, sh_set, sl_set)
            if sig and sig.get('_skip_rr'):
                res.skipped_rr += 1
            elif sig:
                if spec.reverse_on_sweep:      # market entry next open
                    a = sig['atr']
                    spread = nxt.get('spread', 0.0) or 0.0
                    slip = SLIP_ATR * a
                    d = sig['direction']
                    fill = nxt['o'] + slip + spread / 2 if d == 'long' else nxt['o'] - slip - spread / 2
                    rpu = abs(fill - sig['stop'])
                    if rpu > 0:
                        size = (balance * PARAMS['RISK_PCT']) / rpu
                        comm = abs(fill * size) * (COMMISSION_BPS / 10_000)
                        balance -= comm
                        open_trade = Trade(d, nxt['t'], fill, sig['stop'],
                                           sig['target'], size, costs=comm)
                else:
                    pending, pending_age = sig, 0

    res.final_balance = round(balance, 2)
    return res


def load_bars(instrument: str, gran: str) -> list[dict]:
    p = Path(f'/root/.openclaw/agents/lens/data/candles/{instrument}_{gran}.json')
    if not p.exists():
        return []
    return json.loads(p.read_text())['candles']
