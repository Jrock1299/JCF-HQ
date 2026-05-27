"""
phantom_main.py — Autonomous orchestrator for Phantom.

Cycle:
  Every 5 min              : fetch market data, evaluate strategy conditions,
                             manage open positions (EXECUTION — always on)
  Daily  at 21:00 UTC      : run performance review on open positions + results
  Weekly Saturday 11:00 UTC: run discovery (after Norman's 10:00 UTC report),
                             backtest hypotheses, deploy passing ones

Safety floor: pause if balance < 25% of starting balance.
"""

import json
import sys
import time
import signal
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, '/root/.openclaw/agents/norman')

from phantom_config import (
    INSTRUMENTS, STARTING_BALANCE, SAFETY_FLOOR_PCT,
    MAIN_LOOP_SECS,
    DAILY_REVIEW_HOUR,
    WEEKLY_DISCOVERY_WEEKDAY, WEEKLY_DISCOVERY_HOUR,
    STRATEGIES_PATH, TRADE_HISTORY_PATH,
    NORMAN_REPORT_PATH, SCHEDULE_STATE_PATH,
    get_logger, send_telegram, load_json, save_json,
)

from phantom_trader   import PhantomTrader
from phantom_discover import discover_strategies
from phantom_backtest import backtest_strategy, fetch_historical
from phantom_review   import review_performance

log = get_logger('main')

# ── State ──────────────────────────────────────────────────────────────────────

_trader   : PhantomTrader = None
_paused   : bool          = False
_shutdown : bool          = False


def _handle_signal(sig, frame):
    global _shutdown
    log.info('Signal %s received — shutting down gracefully', sig)
    _shutdown = True


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT,  _handle_signal)


# ── Safety floor ───────────────────────────────────────────────────────────────

def _check_safety_floor() -> bool:
    """Returns True if trading should continue, False if we should pause."""
    global _paused
    balance = _trader.get_balance()
    floor   = STARTING_BALANCE * SAFETY_FLOOR_PCT

    if balance <= 0:
        # Can't fetch balance — don't pause, just warn
        log.warning('Safety check: could not read balance')
        return True

    if balance < floor:
        if not _paused:
            log.error(
                'SAFETY FLOOR HIT: balance $%.2f < floor $%.2f — PAUSING',
                balance, floor,
            )
            send_telegram(
                f"PHANTOM — SAFETY FLOOR HIT\n"
                f"Balance: ${balance:.2f}  Floor: ${floor:.2f}\n"
                f"All trading PAUSED. Manual intervention required."
            )
            _paused = True
        return False

    if _paused:
        log.info('Balance $%.2f recovered above floor $%.2f — RESUMING', balance, floor)
        send_telegram(f"PHANTOM — RESUMED (balance ${balance:.2f} above floor)")
        _paused = False

    return True


# ── Market data helpers ────────────────────────────────────────────────────────

def _fetch_current_prices() -> dict:
    """Fetch latest ticker for all instruments. Returns {symbol: ticker_dict}."""
    prices = {}
    for symbol in INSTRUMENTS:
        ticker = _trader.get_ticker(symbol)
        if ticker:
            prices[symbol] = ticker
    return prices


# ── Strategy condition evaluation ─────────────────────────────────────────────

def _load_active_strategies() -> list:
    strategies = load_json(STRATEGIES_PATH, [])
    if not isinstance(strategies, list):
        return []
    return [s for s in strategies if s.get('status') == 'active']


def _check_entry_conditions(strategy: dict, market_data: dict) -> dict | None:
    """
    Lightweight wrapper: pull candles and call the backtest module's condition
    evaluator. Returns signal dict or None.
    """
    from phantom_backtest import _evaluate_simple_conditions  # noqa: F401

    instruments = strategy.get('instruments', [])
    timeframe   = strategy.get('timeframe', '1h')

    for symbol in instruments:
        candles = _trader.get_market_data(symbol, timeframe, limit=50)
        if not candles:
            continue

        # Build minimal OHLCV arrays for indicators
        closes  = [c['close']  for c in candles]
        highs   = [c['high']   for c in candles]
        lows    = [c['low']    for c in candles]
        volumes = [c['volume'] for c in candles]

        entry_conds = strategy.get('entry_conditions', [])
        conditions_text = '\n'.join(entry_conds)

        matched = _evaluate_simple_conditions(
            conditions_text, closes, highs, lows, volumes,
        )

        if matched:
            side = 'long'
            # Simple heuristic: if any condition mentions 'short', 'bear', 'sell' → short
            lower_conds = conditions_text.lower()
            if any(w in lower_conds for w in ('short', 'bear', 'sell signal', 'breakdown')):
                side = 'short'

            return {
                'symbol':    symbol,
                'side':      side,
                'strategy':  strategy,
                'candles':   candles,
            }

    return None


def _parse_leverage(strategy: dict) -> int:
    """Parse e.g. '5x', '10', 5 → int."""
    raw = strategy.get('leverage', '5x')
    if isinstance(raw, int):
        return raw
    try:
        return int(str(raw).lower().replace('x', '').strip())
    except ValueError:
        return 5


def _parse_position_size(strategy: dict, balance: float) -> float:
    """
    Parse position_size_logic like '10% of account' → USDT amount.
    Falls back to 5% of balance.
    """
    raw = str(strategy.get('position_size_logic', '5%')).lower()
    import re
    m = re.search(r'(\d+(?:\.\d+)?)\s*%', raw)
    if m:
        pct = float(m.group(1)) / 100
        return round(balance * pct, 2)
    return round(balance * 0.05, 2)


def _calculate_sl_tp(
    strategy: dict, side: str, entry_price: float, candles: list,
) -> tuple[float | None, float | None]:
    """Derive SL/TP from strategy exit_conditions (best effort, ATR-based)."""
    from phantom_backtest import _atr
    if not candles or len(candles) < 14:
        return None, None

    highs  = [c['high']  for c in candles]
    lows   = [c['low']   for c in candles]
    closes = [c['close'] for c in candles]
    atr    = _atr(highs, lows, closes, 14)
    if not atr or atr[-1] == 0:
        return None, None

    current_atr = atr[-1]
    exit_cfg    = strategy.get('exit_conditions', {})

    # Try to infer multipliers from stop_loss string (e.g. "1.5x ATR")
    import re
    sl_mult, tp_mult = 1.5, 2.5
    sl_str = str(exit_cfg.get('stop_loss', ''))
    tp_str = str(exit_cfg.get('take_profit', ''))
    m = re.search(r'(\d+(?:\.\d+)?)\s*[x×]?\s*atr', sl_str, re.I)
    if m:
        sl_mult = float(m.group(1))
    m = re.search(r'(\d+(?:\.\d+)?)\s*[x×]?\s*atr', tp_str, re.I)
    if m:
        tp_mult = float(m.group(1))

    if side == 'long':
        sl = round(entry_price - sl_mult * current_atr, 4)
        tp = round(entry_price + tp_mult * current_atr, 4)
    else:
        sl = round(entry_price + sl_mult * current_atr, 4)
        tp = round(entry_price - tp_mult * current_atr, 4)

    return sl, tp


# ── Position management ────────────────────────────────────────────────────────

def _manage_open_positions(active_strategies: list) -> None:
    """
    Check time stops on open positions and trailing SL logic.
    Lightweight — full P&L management relies on exchange SL/TP orders.
    """
    positions = _trader.get_positions()
    if not positions:
        return

    history = load_json(TRADE_HISTORY_PATH, [])
    open_records = {
        t['symbol']: t
        for t in history
        if t.get('status') == 'open'
    }

    now = datetime.now(timezone.utc)

    for pos in positions:
        symbol = pos['symbol']
        record = open_records.get(symbol)
        if not record:
            continue

        # Find matching strategy for time stop
        strategy = next(
            (s for s in active_strategies if s.get('name') == record.get('strategy_name')),
            None,
        )
        if not strategy:
            continue

        # Time stop
        opened_at = record.get('opened_at')
        if opened_at:
            try:
                opened_dt = datetime.fromisoformat(opened_at)
                age_hours = (now - opened_dt).total_seconds() / 3600
                time_stop_str = str(strategy.get('exit_conditions', {}).get('time_stop', ''))
                import re
                m = re.search(r'(\d+(?:\.\d+)?)\s*(?:hour|hr|h)', time_stop_str, re.I)
                if m:
                    max_hours = float(m.group(1))
                    if age_hours > max_hours:
                        log.info(
                            'Time stop: %s held %.1fh > %.1fh — closing',
                            symbol, age_hours, max_hours,
                        )
                        _trader.close_position(symbol, reason='time_stop')
                        continue
            except Exception:
                pass


# ── Wall-clock schedule state ─────────────────────────────────────────────────

def _load_schedule_state() -> dict:
    s = load_json(SCHEDULE_STATE_PATH, {}) or {}
    return {
        'last_discovery_isoweek': s.get('last_discovery_isoweek'),  # "2026-W16"
        'last_review_date':       s.get('last_review_date'),        # "2026-04-19"
    }


def _save_schedule_state(state: dict) -> None:
    save_json(SCHEDULE_STATE_PATH, state)


def _isoweek_key(dt: datetime) -> str:
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"


def _due_for_weekly_discovery(now: datetime, state: dict) -> bool:
    """True if it's on/after the Sat 11:00 UTC slot and we haven't run this ISO week."""
    if now.weekday() < WEEKLY_DISCOVERY_WEEKDAY:
        return False
    if now.weekday() == WEEKLY_DISCOVERY_WEEKDAY and now.hour < WEEKLY_DISCOVERY_HOUR:
        return False
    # We're past the slot for this week. Has this ISO week already fired?
    return state.get('last_discovery_isoweek') != _isoweek_key(now)


def _due_for_daily_review(now: datetime, state: dict) -> bool:
    """True if we're past 21:00 UTC today and haven't reviewed today yet."""
    if now.hour < DAILY_REVIEW_HOUR:
        return False
    return state.get('last_review_date') != now.strftime('%Y-%m-%d')


# ── Norman report (discovery context) ──────────────────────────────────────────

def _load_norman_context() -> str | None:
    """Return a compact text summary of Norman's latest report, or None."""
    report = load_json(NORMAN_REPORT_PATH, None)
    if not report:
        log.warning('Norman report not available at %s — discovering without it', NORMAN_REPORT_PATH)
        return None
    try:
        return json.dumps(report, default=str)[:8000]
    except Exception as e:
        log.warning('Norman report unreadable (%s) — discovering without it', e)
        return None


# ── Discovery & deployment cycle ──────────────────────────────────────────────

def _run_discovery_cycle() -> int:
    """Weekly cycle: discover → backtest → deploy → notify. Returns deploy count."""
    log.info('=== WEEKLY DISCOVERY CYCLE STARTING ===')

    prices           = _fetch_current_prices()
    active_strategies = _load_active_strategies()
    trade_history    = load_json(TRADE_HISTORY_PATH, [])
    norman_context   = _load_norman_context()

    # Run discovery (pass Norman's analysis as context)
    try:
        disc = discover_strategies(
            prices, active_strategies, trade_history,
            norman_context=norman_context,
        )
    except Exception as e:
        log.error('Discovery failed: %s', e)
        _send_weekly_summary(None, 0, [], [], used_norman=bool(norman_context))
        return 0

    new_strats = disc.get('new_strategies', [])
    assessment = disc.get('market_assessment')
    log.info('Discovery returned %d new strategy hypotheses', len(new_strats))

    if not new_strats:
        _send_weekly_summary(assessment, 0, [], [], used_norman=bool(norman_context))
        return 0

    # Backtest each hypothesis
    deployed = []
    rejected = []

    for hyp in new_strats:
        name = hyp.get('name', 'unnamed')
        log.info('Backtesting: %s', name)

        instruments = hyp.get('instruments', ['BTC/USDT:USDT'])
        timeframe   = hyp.get('timeframe', '4h')

        # Fetch historical data for all instruments
        historical_data = {}
        for symbol in instruments:
            candles = fetch_historical(symbol, timeframe, limit=500)
            if candles:
                historical_data[symbol] = candles

        if not historical_data:
            log.warning('No historical data for %s — skipping', name)
            continue

        try:
            result = backtest_strategy(hyp, historical_data)
        except Exception as e:
            log.error('Backtest error for %s: %s', name, e)
            continue

        verdict = result.get('verdict', 'REJECT')
        log.info(
            'Backtest %s: %s | WR=%.0f%% PF=%.2f Sharpe=%.2f',
            name, verdict,
            result.get('win_rate', 0),
            result.get('profit_factor', 0),
            result.get('sharpe', 0),
        )

        if verdict == 'DEPLOY':
            # Add to strategies.json
            strategies = load_json(STRATEGIES_PATH, [])
            if not isinstance(strategies, list):
                strategies = []

            new_entry = {
                'name':           name,
                'description':    hyp.get('description', ''),
                'instruments':    instruments,
                'timeframe':      timeframe,
                'entry_conditions': hyp.get('entry_conditions', []),
                'exit_conditions':  hyp.get('exit_conditions', {}),
                'leverage':       hyp.get('leverage', '5x'),
                'position_size_logic': hyp.get('position_size_logic', '5% of account'),
                'edge_explanation': hyp.get('edge_explanation', ''),
                'invalidation':   hyp.get('invalidation', ''),
                'confidence':     hyp.get('confidence', 'medium'),
                'confidence_score': 5,
                'status':         'active',
                'deployed_at':    datetime.now(timezone.utc).isoformat(),
                'backtest':       {
                    'win_rate':      result.get('win_rate'),
                    'profit_factor': result.get('profit_factor'),
                    'sharpe':        result.get('sharpe'),
                    'ruin_pct':      result.get('ruin_pct'),
                    'n_trades':      result.get('n_trades'),
                },
                'performance': {
                    'trades': 0, 'win_rate': 0, 'profit_factor': 0,
                },
            }
            strategies.append(new_entry)
            save_json(STRATEGIES_PATH, strategies)
            deployed.append(name)
            log.info('Deployed: %s', name)
        else:
            rejected.append(name)

    log.info(
        'Discovery cycle complete: %d deployed, %d rejected',
        len(deployed), len(rejected),
    )
    _send_weekly_summary(
        assessment, len(new_strats), deployed, rejected,
        used_norman=bool(norman_context),
    )
    return len(deployed)


def _send_weekly_summary(
    assessment: str | None,
    n_hypotheses: int,
    deployed: list,
    rejected: list,
    used_norman: bool,
) -> None:
    """Saturday summary: what Phantom analyzed and what came out of it."""
    lines = [
        "PHANTOM — WEEKLY DISCOVERY SUMMARY",
        f"Analyzed: {', '.join(s.split('/')[0] for s in INSTRUMENTS)}",
        f"Norman report: {'loaded' if used_norman else 'unavailable'}",
        f"Hypotheses generated: {n_hypotheses}",
        f"Deployed: {len(deployed)}" + (f" — {', '.join(deployed)}" if deployed else ""),
        f"Rejected: {len(rejected)}" + (f" — {', '.join(rejected)}" if rejected else ""),
    ]
    if assessment:
        lines.append(f"Regime read: {assessment[:400]}")
    send_telegram('\n'.join(lines))


# ── Trading tick ──────────────────────────────────────────────────────────────

def _run_trading_tick() -> None:
    """5-minute tick: check conditions and manage positions."""
    active_strategies = _load_active_strategies()

    if not active_strategies:
        log.debug('No active strategies — skipping tick')
        return

    balance  = _trader.get_balance()
    positions = _trader.get_positions()
    symbols_with_positions = {p['symbol'] for p in positions}

    # Manage existing positions (time stops, etc.)
    _manage_open_positions(active_strategies)

    # Check entry conditions
    for strategy in active_strategies:
        instruments = strategy.get('instruments', [])
        # Skip if already in a position on any of these instruments
        if any(sym in symbols_with_positions for sym in instruments):
            continue

        signal = _check_entry_conditions(strategy, {})
        if signal is None:
            continue

        symbol    = signal['symbol']
        side      = signal['side']
        leverage  = _parse_leverage(strategy)
        size_usdt = _parse_position_size(strategy, balance)

        # Sanity: don't risk more than 10% of balance per trade
        max_size = balance * 0.10
        size_usdt = min(size_usdt, max_size)

        if size_usdt < 10:
            log.warning('Position size $%.2f too small for %s — skipping', size_usdt, symbol)
            continue

        # Estimate entry price for SL/TP
        ticker = _trader.get_ticker(symbol)
        entry_price = float(ticker.get('last') or ticker.get('close', 0)) if ticker else 0
        sl, tp = None, None
        if entry_price > 0:
            sl, tp = _calculate_sl_tp(strategy, side, entry_price, signal['candles'])

        log.info(
            'Entry signal: %s %s %s  lev=%dx  size=$%.0f  SL=%.4f TP=%.4f',
            strategy['name'], symbol, side.upper(), leverage, size_usdt,
            sl or 0, tp or 0,
        )

        _trader.open_position(
            symbol        = symbol,
            side          = side,
            leverage      = leverage,
            amount_usdt   = size_usdt,
            strategy_name = strategy['name'],
            context       = strategy.get('edge_explanation', '')[:200],
            sl_price      = sl,
            tp_price      = tp,
        )


# ── Main loop ─────────────────────────────────────────────────────────────────

def run() -> None:
    global _trader

    _trader = PhantomTrader()

    log.info('=== PHANTOM STARTING ===')
    log.info('Starting balance: $%.2f  Floor: $%.2f',
             STARTING_BALANCE, STARTING_BALANCE * SAFETY_FLOOR_PCT)

    send_telegram(
        "PHANTOM — ONLINE\n"
        f"Starting balance: ${STARTING_BALANCE:,.0f}\n"
        f"Safety floor: ${STARTING_BALANCE * SAFETY_FLOOR_PCT:,.0f}\n"
        f"Instruments: {', '.join(s.split('/')[0] for s in INSTRUMENTS)}\n"
        "Schedule: 5m execution | daily 21:00 UTC review | "
        "weekly Sat 11:00 UTC discovery"
    )

    while not _shutdown:
        loop_start = time.time()

        try:
            # ── Safety floor check ──────────────────────────────────────────
            if not _check_safety_floor():
                log.info('Paused — sleeping %ds', MAIN_LOOP_SECS)
                time.sleep(MAIN_LOOP_SECS)
                continue

            now_utc = datetime.now(timezone.utc)
            sched   = _load_schedule_state()

            # ── Weekly discovery (Saturday 11:00 UTC) ───────────────────────
            if _due_for_weekly_discovery(now_utc, sched):
                try:
                    _run_discovery_cycle()
                except Exception as e:
                    log.error('Discovery cycle error: %s', e, exc_info=True)
                # Mark this ISO week done regardless of outcome, so a failure
                # doesn't retrigger every 5 minutes until midnight Sunday.
                sched['last_discovery_isoweek'] = _isoweek_key(now_utc)
                _save_schedule_state(sched)

            # ── Daily review (21:00 UTC) ────────────────────────────────────
            if _due_for_daily_review(now_utc, sched):
                log.info('=== DAILY REVIEW CYCLE STARTING ===')
                try:
                    review_performance()
                except Exception as e:
                    log.error('Review cycle error: %s', e, exc_info=True)
                sched['last_review_date'] = now_utc.strftime('%Y-%m-%d')
                _save_schedule_state(sched)

            # ── Execution tick (every 5m, continuous) ──────────────────────
            try:
                _run_trading_tick()
            except Exception as e:
                log.error('Trading tick error: %s', e, exc_info=True)

        except Exception as e:
            log.error('Main loop error: %s', e, exc_info=True)

        # Sleep for remainder of 5-min window — interruptible so SIGTERM exits fast
        elapsed = time.time() - loop_start
        sleep_time = max(5, MAIN_LOOP_SECS - elapsed)
        log.debug('Tick done in %.1fs — sleeping %.0fs', elapsed, sleep_time)
        deadline = time.time() + sleep_time
        while not _shutdown and time.time() < deadline:
            time.sleep(1)

    log.info('=== PHANTOM SHUTDOWN COMPLETE ===')
    send_telegram("PHANTOM — OFFLINE (graceful shutdown)")


def run_once_weekly_discovery() -> int:
    """One-shot: fire the weekly discovery cycle and exit. Intended for cron."""
    global _trader
    _trader = PhantomTrader()
    log.info('=== ONE-SHOT WEEKLY DISCOVERY ===')
    deployed = _run_discovery_cycle()
    state = _load_schedule_state()
    state['last_discovery_isoweek'] = _isoweek_key(datetime.now(timezone.utc))
    _save_schedule_state(state)
    return deployed


def run_once_daily_review() -> None:
    """One-shot: fire the daily review cycle and exit. Intended for cron."""
    global _trader
    _trader = PhantomTrader()
    log.info('=== ONE-SHOT DAILY REVIEW ===')
    try:
        review_performance()
    except Exception as e:
        log.error('Daily review error: %s', e, exc_info=True)
    state = _load_schedule_state()
    state['last_review_date'] = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    _save_schedule_state(state)


if __name__ == '__main__':
    if '--weekly-discovery' in sys.argv:
        sys.exit(0 if run_once_weekly_discovery() is not None else 1)
    if '--daily-review' in sys.argv:
        run_once_daily_review()
        sys.exit(0)
    run()
