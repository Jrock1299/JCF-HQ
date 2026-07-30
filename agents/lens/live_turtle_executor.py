#!/usr/bin/env python3
"""live_turtle_executor.py — LIVE (paper) executor for the validated
turtle_soup / mean-reversion strategy.

Written 2026-07-28 as the trading arm that turns dashboard/strategy_library.json
into actual paper orders on OANDA. Design:

  ONE STATELESS TICK, EVERY 15 MINUTES DURING KILLZONES.
  Each tick, per covered instrument:
    1. Confirm the instrument is in a killzone declared by the library entry.
    2. Skip if this instrument already has an open OANDA position tagged as
       ours (idempotency — a re-fire of the same 15m bar can't double up).
    3. Fetch the last 60 M15 bars + 100 H4 bars from OANDA.
    4. Run ict_backtest._detect against the last CLOSED bar (close[1]).
    5. If a signal fires, place a MARKET ORDER with server-side SL + TP.
       The bracket lives on OANDA's side, so exit management does not
       require this process to stay running.
    6. Log every decision to dashboard/live_turtle_trades.json.

  NO CONTINUOUS LOOP. That's Blade's old ORB design; it broke a lot when
  the process died mid-session. A stateless tick fires from cron, does one
  thing, exits — the way jerry_main runs.

  NO POSITION MONITOR LOOP. OANDA's bracket orders enforce SL and TP on
  their side. `sync_tradelocker.py` / `sync_agent_pnl.py` reconcile fills.

  RAILS PRESERVED.
    - Max risk per trade: 0.75% of account equity (from library params.RISK_PCT).
    - Daily-DD circuit breaker: -4% of session-start balance halts new
      entries for the rest of the UTC day. Scoped PER OANDA ACCOUNT — Blade
      and Edge trade separate books on the same cron minute, and a shared
      rail anchored one agent's breaker to the other's balance (see
      `_book_key()`).
    - Min account balance: refuse to trade below $100 (Blade's floor).
    - Order tagging: every order carries a clientExtensions.id starting with
      `lens_turtle_` so we can filter our own positions in the account.

Not-in-scope for this MVP:
  - Trailing stops (turtle_soup exits at target or stop; no scale-out).
  - Partial fills / re-quotes (OANDA practice fills clean on liquid
    instruments; log the fill event and move on).
  - Multi-strategy dispatch — this executor runs ONE strategy family
    (turtle_soup and its future baseline sibling). A different strategy
    (e.g. a new momentum model) goes in its own executor per the
    "one behaviour, one edit surface" rule.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta, time as dtime
from pathlib import Path
from typing import Optional

sys.path.insert(0, '/root/.openclaw/scripts')
sys.path.insert(0, '/root/.openclaw/agents/lens')

from strategy_library import iter_deployable, load as load_library  # noqa: E402
from ict_backtest import _detect, atr, swing_highs, swing_lows      # noqa: E402
from ict_strategies import BY_KEY, PARAMS, KILLZONES                # noqa: E402
from oanda_retry import request_with_retry                          # noqa: E402


# ── Paths ─────────────────────────────────────────────────────────────────────
LOG_PATH        = Path('/root/.openclaw/agents/lens/live_turtle.log')
TRADES_PATH     = Path('/root/.openclaw/dashboard/live_turtle_trades.json')
# Both of these are PER-BOOK, not global — the filename carries the OANDA
# account id. See _book_key() for why sharing them across Blade and Edge halted
# all trading for two days.
BALANCE_PATH    = Path('/root/.openclaw/dashboard/live_turtle_balance.json')  # template; see _balance_path()
DD_STATE_PREFIX = '/tmp/live_turtle_dd_'  # + <account-id>_<UTC-date>.json
AUTH_PATH       = Path('/root/.openclaw/agents/main/agent/auth-profiles.json')

# ── Rails ─────────────────────────────────────────────────────────────────────
STARTING_BALANCE_DEFAULT = 5_000.0     # matches Blade's start; user confirmed
MIN_BALANCE              = 100.0
DAILY_DD_HALT_PCT        = 0.04        # -4% halts remaining day
CLIENT_ID_PREFIX         = 'lens_turtle'
BAR_HISTORY_M15          = 200         # enough for swing detection + ATR
BAR_HISTORY_H4           = 200

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(LOG_PATH), level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
)
log = logging.getLogger('live_turtle')


# ══════════════════════════════════════════════════════════════════════════════
# OANDA — thin wrapper around oandapyV20
# ══════════════════════════════════════════════════════════════════════════════

_client = None
_account_id = None


_override_account_id = None


def set_account_override(account_id: str) -> None:
    """Override which OANDA practice account the executor trades against.
    Used to route Edge to its own book (`101-001-22502524-002`) while Blade
    uses `auth-profiles.json`'s default."""
    global _override_account_id, _client, _account_id
    _override_account_id = account_id
    _client = None
    _account_id = None


def _oanda():
    global _client, _account_id
    if _client is not None:
        return _client, _account_id
    from oandapyV20 import API
    creds = json.loads(AUTH_PATH.read_text())['profiles']['oanda:default']
    _client = API(access_token=creds['key'], environment='practice')
    _account_id = _override_account_id or creds['account_id']
    return _client, _account_id


def fetch_candles(instrument: str, granularity: str, count: int) -> list[dict]:
    """OANDA candles → the flat dict shape ict_backtest expects. Only complete
    candles are kept — a still-forming bar is close[0] in disguise."""
    from oandapyV20.endpoints.instruments import InstrumentsCandles
    client, _ = _oanda()
    r = InstrumentsCandles(instrument, params={
        'granularity': granularity, 'count': count, 'price': 'MBA',
    })
    # Retry transient throttling — Blade, Edge and the regime briefing share one
    # practice token on the same */15 cron minute and OANDA returns 401 for part
    # of that burst. See scripts/oanda_retry.py.
    resp = request_with_retry(client, r, label=f'{instrument}/{granularity}') or {}
    out = []
    for c in resp.get('candles', []):
        if not c.get('complete'):
            continue
        mid = c.get('mid') or {}; bid = c.get('bid') or {}; ask = c.get('ask') or {}
        try:
            row = {
                't': c['time'][:19],
                'o': float(mid['o']), 'h': float(mid['h']),
                'l': float(mid['l']), 'c': float(mid['c']),
                'v': int(c.get('volume', 0)),
            }
            if bid and ask:
                row['spread'] = round(float(ask['c']) - float(bid['c']), 6)
            out.append(row)
        except (KeyError, TypeError, ValueError):
            continue
    return out


def open_positions_for(instrument: str) -> list[dict]:
    """List OANDA-side open trades on this instrument that we opened
    (client extension id starts with our prefix)."""
    from oandapyV20.endpoints.trades import OpenTrades
    client, acct = _oanda()
    r = OpenTrades(acct); client.request(r)
    ours = []
    for t in r.response.get('trades', []):
        if t.get('instrument') != instrument:
            continue
        ce = t.get('clientExtensions') or {}
        if str(ce.get('id', '')).startswith(CLIENT_ID_PREFIX):
            ours.append(t)
    return ours


def account_summary() -> dict:
    from oandapyV20.endpoints.accounts import AccountSummary
    client, acct = _oanda()
    r = AccountSummary(acct)
    # Retried for the same reason as fetch_candles. This one matters more: a
    # transient failure here used to propagate as ERROR for the whole tick, and
    # the balance it returns feeds the daily-DD rail.
    return (request_with_retry(client, r, label=f'account/{acct}') or {}).get('account', {})


def place_bracket_market_order(instrument: str, units: int,
                               stop_distance: float, target_distance: float,
                               client_ext_id: str) -> dict:
    """MARKET order with SL and TP set RELATIVE TO THE ACTUAL FILL, not to a
    stale pre-fill candle price.

    2026-07-28 fix. The previous version passed absolute `stop` and `target`
    prices computed off `bars[i]['c']` (the last closed M15 mid). By the time
    OANDA fills the market order at bars[i+1]'s open + slippage, the price has
    moved — sometimes by more than the intended stop distance. The strategy
    was validated at a specific R:R (target_distance / stop_distance); if the
    stop-to-fill distance moves but the target stays anchored to the stale
    candle, the R:R the LIVE trade actually runs at diverges from what the
    backtest measured.

    The fix in two parts, both required:
      1. `stopLossOnFill.distance` — OANDA v20 accepts a distance on
         `StopLossDetails`. Submitted with the market order, this pins SL at
         (fill ± stop_distance) automatically. No stale-price drift.
      2. `takeProfitOnFill` — OANDA v20 does NOT support `distance` on
         `TakeProfitDetails`; only `price`. So we submit the market order
         with SL-distance only, read `orderFillTransaction.price` from the
         response, compute `target_price = fill ± target_distance` in the
         correct direction, then attach the TP via TradeCRCDO. Two atomic
         calls; the trade is never SL-less because SL was attached at fill.

    Units are signed: +ve long, -ve short. `target_distance` is always
    positive; direction sign taken from `units`.
    """
    from oandapyV20.endpoints.orders import OrderCreate
    from oandapyV20.endpoints.trades import TradeCRCDO
    client, acct = _oanda()

    if stop_distance <= 0 or target_distance <= 0:
        raise ValueError(
            f'place_bracket_market_order: distances must be > 0 '
            f'(stop={stop_distance}, target={target_distance})'
        )

    # 1) Market order with SL-distance attached — SL is guaranteed relative
    #    to actual fill by OANDA.
    body = {
        'order': {
            'type': 'MARKET',
            'instrument': instrument,
            'units': str(int(units)),
            'timeInForce': 'FOK',
            'positionFill': 'DEFAULT',
            'clientExtensions': {
                'id': client_ext_id,
                'tag': 'live_turtle',
                'comment': f'turtle_soup {instrument} entry via live_turtle_executor',
            },
            'stopLossOnFill': {
                'distance': f'{stop_distance:.5f}',
                'timeInForce': 'GTC',
            },
        }
    }
    r = OrderCreate(acct, data=body)
    client.request(r)
    resp = r.response

    # 2) Read actual fill, attach TP relative to it. If the order did not
    #    fill (e.g. FOK cancelled) there is no trade to attach TP to; return
    #    the response as-is so the caller can log it.
    fill_tx = resp.get('orderFillTransaction') or {}
    fill_price_str = fill_tx.get('price')
    trade_opened = fill_tx.get('tradeOpened') or {}
    trade_id = trade_opened.get('tradeID')
    if not fill_price_str or not trade_id:
        resp['_tp_attach_status'] = 'skipped_no_fill'
        return resp

    fill_price = float(fill_price_str)
    direction_sign = 1 if int(units) > 0 else -1
    target_price = fill_price + direction_sign * float(target_distance)

    tp_body = {
        'takeProfit': {
            'price': f'{target_price:.5f}',
            'timeInForce': 'GTC',
        }
    }
    try:
        r2 = TradeCRCDO(acct, trade_id, data=tp_body)
        client.request(r2)
        resp['_tp_attach_status'] = 'attached'
        resp['_tp_attach_response'] = r2.response
        resp['_fill_price'] = fill_price
        resp['_target_price'] = target_price
        resp['_realized_rr'] = round(
            abs(target_price - fill_price) / float(stop_distance), 3
        )
    except Exception as e:
        # SL is already attached server-side; a failed TP attach means the
        # trade will run to SL or manual exit. Log loudly, do not silently
        # succeed.
        resp['_tp_attach_status'] = f'FAILED: {type(e).__name__}: {e}'
        log.error(f'TP attach failed for trade {trade_id}: {e}')
    return resp


# ══════════════════════════════════════════════════════════════════════════════
# Balance + daily-DD rail
# ══════════════════════════════════════════════════════════════════════════════

def _book_key() -> str:
    """Identity of the book these rails protect: the OANDA account id.

    ── The 2026-07-29/30 zero-trade bug ──────────────────────────────────────
    Both the daily-DD state file and the balance file used to be global —
    `/tmp/live_turtle_dd_<UTC-date>.json` and one `live_turtle_balance.json`
    shared by every caller. But Blade and Edge run this same executor on the
    SAME */15 cron minute against DIFFERENT OANDA practice accounts (…-001 at
    $2,000 and …-002 at $5,000).

    Whichever agent ticked first wrote its own balance as `day_start_balance`.
    The other agent then read its genuinely different account balance against
    that foreign anchor:

        (2000 - 5000) / 5000 = -60%   ->  breaches the -4% rail  ->  halted

    and because the halt is a day-scoped latch, that one crossed wire stopped
    BOTH agents for the rest of every UTC day. `/tmp/live_turtle_dd_20260729`
    and `…20260730` both show `halt_dd: -0.6` latched ~10 seconds after the
    first tick of the day. Neither agent placed a single order.

    Keying on the account id — not the agent name — is the correct invariant:
    one daily-drawdown rail per book. Two agents sharing one account SHOULD
    share a rail (it is the same money); two agents on separate accounts must
    not. This also means the rail can never again be anchored to a balance
    that isn't its own.
    """
    _, acct = _oanda()
    return str(acct).replace('/', '_')


def _balance_path() -> Path:
    return BALANCE_PATH.with_name(f'live_turtle_balance_{_book_key()}.json')


def _load_balance() -> float:
    try:
        d = json.loads(_balance_path().read_text())
        return float(d.get('balance', STARTING_BALANCE_DEFAULT))
    except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError):
        return STARTING_BALANCE_DEFAULT


def _save_balance(bal: float) -> None:
    p = _balance_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        'balance': round(bal, 2),
        'account_id': _book_key(),
        'updated': datetime.now(timezone.utc).isoformat(),
    }, indent=2))


def _dd_state_path() -> str:
    d = datetime.now(timezone.utc).strftime('%Y%m%d')
    return f'{DD_STATE_PREFIX}{_book_key()}_{d}.json'


def _dd_check_and_maybe_halt(current_balance: float) -> bool:
    """Return True if we're already halted for the day (or should be). Persists
    the day-start balance on first call each UTC day, per book (see _book_key)."""
    p = Path(_dd_state_path())
    if not p.exists():
        p.write_text(json.dumps({
            'account_id': _book_key(),
            'day_start_balance': round(current_balance, 2),
            'halted': False,
        }, indent=2))
        return False
    d = json.loads(p.read_text())
    if d.get('halted'):
        return True
    day_start = float(d.get('day_start_balance', current_balance))
    if day_start <= 0:
        # A zero/negative anchor makes the ratio below meaningless. Re-anchor
        # rather than divide by it — Rule #9: no invented denominators.
        log.warning(f'daily-DD anchor invalid ({day_start}) — re-anchoring to '
                    f'{current_balance}')
        d['day_start_balance'] = round(current_balance, 2)
        p.write_text(json.dumps(d, indent=2))
        return False
    dd = (current_balance - day_start) / day_start
    if dd <= -DAILY_DD_HALT_PCT:
        d['halted'] = True
        d['halted_at'] = datetime.now(timezone.utc).isoformat()
        d['halt_dd'] = round(dd, 4)
        p.write_text(json.dumps(d, indent=2))
        log.warning(f'daily-DD halt tripped on {_book_key()}: dd={dd:.2%} '
                    f'(day_start={day_start}, now={current_balance})')
        return True
    return False


# ══════════════════════════════════════════════════════════════════════════════
# Killzone check
# ══════════════════════════════════════════════════════════════════════════════

def in_killzone_now(killzones: list, now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(timezone.utc)
    h = now.hour
    for z in killzones:
        rng = KILLZONES.get(z)
        if rng and rng[0] <= h < rng[1]:
            return True
    return False


# ══════════════════════════════════════════════════════════════════════════════
# Trade log
# ══════════════════════════════════════════════════════════════════════════════

def append_trade_log(record: dict) -> None:
    try:
        try:
            store = json.loads(TRADES_PATH.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            store = {
                'schema': 'jcf.live_turtle_trades/v1',
                'note': 'One record per decision — SIGNAL_FIRED, NO_SIGNAL, HALTED, ALREADY_OPEN, ERROR.',
                'records': [],
            }
        store.setdefault('records', []).append(record)
        TRADES_PATH.write_text(json.dumps(store, indent=2, default=str))
    except OSError as e:
        log.warning(f'append_trade_log: {e}')


# ══════════════════════════════════════════════════════════════════════════════
# The tick
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class TickResult:
    instrument: str
    status: str
    detail: str = ''
    signal: Optional[dict] = None
    order_response: Optional[dict] = None


def _pip_value(instrument: str) -> float:
    """Price-increment per point. Blade's table, extended for XAU."""
    return {
        'SPX500_USD': 1.0, 'DE30_EUR': 1.0, 'XAU_USD': 0.01,
        'CHF_JPY': 0.01,
    }.get(instrument, 1.0)


def _size_units(balance: float, entry: float, stop: float,
                risk_pct: float, instrument: str) -> int:
    """Position size in OANDA units. risk_$ / stop_distance = units.

    Blade's `_pip_value` is the price-increment-per-point, not the USD-per-unit
    value — but for sizing (units = risk_$ / stop_$_per_unit) the two
    coincide on USD-quoted instruments (SPX500_USD, XAU_USD) and are
    a reasonable proxy on non-USD-quoted instruments for paper. Fixed
    live: see the TODO in blade_bot.py:76-78.
    """
    stop_pts = abs(entry - stop)
    if stop_pts <= 0:
        return 0
    risk_dollars = balance * risk_pct
    dollars_per_point_per_unit = _pip_value(instrument)
    if dollars_per_point_per_unit <= 0:
        return 0
    units = int(risk_dollars / (stop_pts * dollars_per_point_per_unit))
    return max(units, 1)


def tick_one(entry: dict, dry_run: bool = False) -> TickResult:
    """Process one library entry (one instrument + one strategy) for this tick."""
    instrument = entry['instrument']
    strategy = entry['strategy']
    ex = entry.get('execution') or {}

    # 1) killzone gate — the library declares its own killzone list per strategy.
    if not in_killzone_now(ex.get('killzones') or ['LONDON', 'NY']):
        return TickResult(instrument, 'OUT_OF_KILLZONE')

    # 2) idempotency — one live position per instrument at a time.
    ours = open_positions_for(instrument)
    if ours:
        return TickResult(instrument, 'ALREADY_OPEN',
                          detail=f'{len(ours)} open positions with our tag')

    # 3) rails — balance floor + daily-DD halt.
    acct = account_summary()
    balance = float(acct.get('balance', 0) or 0)
    if balance < MIN_BALANCE:
        return TickResult(instrument, 'BELOW_MIN_BALANCE',
                          detail=f'balance={balance:.2f} < {MIN_BALANCE}')
    if _dd_check_and_maybe_halt(balance):
        return TickResult(instrument, 'DAILY_DD_HALTED')

    # 4) candles.
    bars = fetch_candles(instrument, 'M15', BAR_HISTORY_M15)
    h4   = fetch_candles(instrument, 'H4',  BAR_HISTORY_H4)
    if len(bars) < 60 or len(h4) < 60:
        return TickResult(instrument, 'INSUFFICIENT_HISTORY',
                          detail=f'M15={len(bars)} H4={len(h4)}')

    # 5) detection on the LAST CLOSED bar (close[1] contract).
    spec = BY_KEY[strategy]
    sh = swing_highs(bars, PARAMS['SWING_K'])
    sl = swing_lows(bars, PARAMS['SWING_K'])
    i = len(bars) - 1
    sig = _detect(spec, bars, i, h4, sh, sl)
    if not sig or sig.get('_skip_rr'):
        return TickResult(instrument, 'NO_SIGNAL',
                          detail='no valid setup on close[1]' if not sig
                                 else 'setup rejected on RR floor')

    # 6) DISTANCES from the signal. The R:R the strategy was validated on
    #    is target_distance / stop_distance; we preserve BOTH as distances
    #    and apply them relative to the actual fill (see
    #    place_bracket_market_order for the OANDA-side mechanism).
    reference_px = float(bars[i]['c'])              # last M15 close, for pre-fill sizing only
    stop_px_ref   = float(sig['stop'])
    target_px_ref = float(sig['target'])
    stop_distance   = abs(reference_px - stop_px_ref)
    target_distance = abs(target_px_ref - reference_px)
    validated_rr = round(target_distance / stop_distance, 3) if stop_distance > 0 else 0
    direction = sig['direction']
    risk_pct = float((entry.get('params') or {}).get('RISK_PCT', PARAMS['RISK_PCT']))
    units = _size_units(balance, reference_px, stop_px_ref, risk_pct, instrument)
    if units <= 0:
        return TickResult(instrument, 'SIZING_ZERO',
                          detail=f'ref={reference_px} stop_dist={stop_distance} risk_pct={risk_pct}')
    signed_units = units if direction == 'long' else -units

    if dry_run:
        # In dry-run we cannot know the actual fill price. Estimate as
        # (reference + typical M1 spread/2) for reporting, but LABEL it as
        # estimate so it's not misread as guaranteed. What matters here is
        # that the distances are what OANDA will use at fill time.
        est_fill = reference_px
        est_stop = est_fill - stop_distance if direction == 'long' else est_fill + stop_distance
        est_target = est_fill + target_distance if direction == 'long' else est_fill - target_distance
        return TickResult(instrument, 'DRY_RUN_SIGNAL', signal={
            'direction': direction,
            'reference_close': reference_px,
            'stop_distance': round(stop_distance, 5),
            'target_distance': round(target_distance, 5),
            'validated_rr': validated_rr,
            'estimated_fill': est_fill,
            'estimated_stop': round(est_stop, 5),
            'estimated_target': round(est_target, 5),
            'units': signed_units,
            'risk_pct': risk_pct,
            'balance': balance,
            'oanda_mechanism': 'stopLossOnFill.distance + post-fill TradeCRCDO takeProfit',
        })

    # 7) fire.
    client_ext_id = f'{CLIENT_ID_PREFIX}_{strategy}_{instrument}_{uuid.uuid4().hex[:8]}'
    resp = place_bracket_market_order(instrument, signed_units,
                                      stop_distance, target_distance, client_ext_id)
    return TickResult(instrument, 'SIGNAL_FIRED', signal={
        'direction': direction,
        'reference_close': reference_px,
        'stop_distance': round(stop_distance, 5),
        'target_distance': round(target_distance, 5),
        'validated_rr': validated_rr,
        'fill_price': resp.get('_fill_price'),
        'target_price_at_fill': resp.get('_target_price'),
        'realized_rr': resp.get('_realized_rr'),
        'tp_attach_status': resp.get('_tp_attach_status'),
        'units': signed_units,
        'client_id': client_ext_id, 'risk_pct': risk_pct,
        'library_content_hash': entry.get('content_hash'),
    }, order_response=resp)


def _dedupe_best_per_instrument(entries: list) -> list:
    """When more than one deployable strategy exists for the same instrument
    (e.g. turtle_soup AND sweep_fade_baseline once both are validated), pick
    the one with the highest expectancy_R. That's the honest tiebreaker:
    R-per-trade is position-size-invariant and directly reflects the
    strategy's per-decision edge. Ties broken by trade count (more trades =
    tighter estimate).

    Same-instrument competition is expected as the library grows — this is
    the "one strategy per instrument per tick" rail, not an assumption that
    only one exists."""
    by_inst: dict = {}
    for e in entries:
        inst = e['instrument']
        prior = by_inst.get(inst)
        if prior is None:
            by_inst[inst] = e; continue
        er_new  = (e.get('stats')     or {}).get('expectancy_R') or 0
        er_old  = (prior.get('stats') or {}).get('expectancy_R') or 0
        if er_new > er_old:
            by_inst[inst] = e
        elif er_new == er_old:
            if (e.get('n_trades') or 0) > (prior.get('n_trades') or 0):
                by_inst[inst] = e
    return list(by_inst.values())


def run_tick(agent: str = 'blade', dry_run: bool = False,
             instruments_filter: list | None = None) -> list[TickResult]:
    """One tick across every deployable entry for `agent`. Returns per-entry
    TickResults for downstream logging / Telegram."""
    lib = load_library()
    log.info(f'[library] loaded status={lib.get("_load_status")} '
             f'validated={len(lib.get("validated", []))} '
             f'updated_at={lib.get("updated_at")}')

    if lib.get('_load_status') != 'ok':
        return [TickResult('*', 'LIBRARY_UNAVAILABLE',
                           detail=f'load_status={lib.get("_load_status")}')]

    entries = _dedupe_best_per_instrument(list(iter_deployable(agent=agent)))
    results = []
    for entry in entries:
        if instruments_filter and entry['instrument'] not in instruments_filter:
            continue
        try:
            res = tick_one(entry, dry_run=dry_run)
        except Exception as e:
            log.exception(f'tick_one({entry.get("id")}) failed')
            res = TickResult(entry.get('instrument', '?'), 'ERROR',
                             detail=f'{type(e).__name__}: {e}')
        results.append(res)
        append_trade_log({
            'timestamp':   datetime.now(timezone.utc).isoformat(),
            'agent':       agent,
            'entry_id':    entry.get('id'),
            'instrument':  res.instrument,
            'status':      res.status,
            'detail':      res.detail,
            'signal':      res.signal,
            'order_response_id': (res.order_response or {}).get('orderFillTransaction', {}).get('id')
                                 if res.order_response else None,
            'dry_run':     dry_run,
        })
        log.info(f'tick[{agent}] {entry["id"]}: {res.status} {res.detail}')
    return results


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--agent', default='blade',
                    help='asset-class filter (blade/edge). default: blade')
    ap.add_argument('--instrument', action='append',
                    help='restrict to one or more instruments (repeatable)')
    ap.add_argument('--account-id',
                    help='override the OANDA account id (Edge uses its own book)')
    ap.add_argument('--dry-run', action='store_true',
                    help='detect + log but do NOT place orders')
    ap.add_argument('--list', action='store_true',
                    help='just list what would be traded and exit')
    a = ap.parse_args()

    if a.account_id:
        set_account_override(a.account_id)

    if a.list:
        for e in iter_deployable(agent=a.agent, instrument=None):
            print(f'{e["id"]:40}  killzones={",".join(e.get("execution",{}).get("killzones",[]))}  '
                  f'entry_type={e.get("execution",{}).get("entry_type")}')
        return 0

    results = run_tick(agent=a.agent, dry_run=a.dry_run,
                       instruments_filter=a.instrument)
    if not results:
        print(f'[live_turtle] {a.agent}: no deployable entries')
        return 0

    for r in results:
        line = f'[live_turtle] {r.instrument:12} {r.status:22} {r.detail or ""}'
        if r.signal:
            s = r.signal
            if s.get('stop_distance') is not None:
                line += (f' | {s.get("direction","")} '
                         f'stop_dist={s.get("stop_distance")} '
                         f'tgt_dist={s.get("target_distance")} '
                         f'RR={s.get("validated_rr")} '
                         f'units={s.get("units")}')
                if s.get('estimated_fill') is not None:
                    line += (f' | est: fill≈{s.get("estimated_fill")} '
                             f'SL≈{s.get("estimated_stop")} TP≈{s.get("estimated_target")}')
                if s.get('fill_price') is not None:
                    line += (f' | FILLED @ {s.get("fill_price")} '
                             f'TP@{s.get("target_price_at_fill")} '
                             f'realized_RR={s.get("realized_rr")} '
                             f'({s.get("tp_attach_status")})')
        print(line)
    return 0


if __name__ == '__main__':
    sys.exit(main())
