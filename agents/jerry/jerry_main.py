"""
jerry_main.py — Autonomous stock and options trader for JCF HQ.

Daily cycle (all times UTC):
  13:00  Discovery run — find today's opportunities (pre-market)
  13:30  Market opens — 5-minute trading ticks begin
  20:00  Market closes — ticks stop
  20:30  Review run — analyze the day
  Outside hours: 60-second heartbeat sleep

Weekends: full sleep (no market).
Safety floor: pause if portfolio < $25K.
"""

import sys
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from jerry_config import (
    wrap_message,
    STARTING_BALANCE, SAFETY_FLOOR, SAFETY_FLOOR_PCT,
    MAIN_LOOP_SECS, SENTINEL_DATA, TRADE_HISTORY_PATH,
    DASHBOARD_PATH, WATCHLIST_PATH, PERFORMANCE_PATH,
    get_logger, send_telegram, load_json, save_json,
    is_weekday, is_market_hours, is_discovery_window, is_review_window,
)
from jerry_trader   import JerryTrader
from jerry_discover import discover_opportunities
from jerry_review   import review_day

log = get_logger('main')

# ── State ──────────────────────────────────────────────────────────────────────

_trader             : JerryTrader = None
_shutdown           : bool        = False
_paused             : bool        = False
_status             : str         = 'initializing'

_discovery_done_today : bool = False
_review_done_today    : bool = False
_wrap_done_today      : bool = False
_last_date            : str  = ''


def _handle_signal(sig, frame):
    global _shutdown
    log.info('Signal %s received — shutting down gracefully', sig)
    _shutdown = True


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT,  _handle_signal)


# ── Dashboard ──────────────────────────────────────────────────────────────────

def _update_dashboard(status: str = None) -> None:
    global _status
    if status:
        _status = status
    try:
        account   = _trader.get_account()
        positions = _trader.get_positions()
        history   = load_json(TRADE_HISTORY_PATH, [])

        closed_today = [
            t for t in history
            if (t.get('closed_at') or '').startswith(
                datetime.now(timezone.utc).strftime('%Y-%m-%d')
            )
        ]
        all_closed = [t for t in history if t.get('status') == 'closed']
        wins       = sum(1 for t in all_closed if float(t.get('pnl', 0)) > 0)
        win_rate   = (wins / len(all_closed) * 100) if all_closed else 0

        balance       = account.get('portfolio_value', STARTING_BALANCE)
        total_pnl     = balance - STARTING_BALANCE

        dashboard = {
            'last_updated':   datetime.now(timezone.utc).isoformat(),
            'balance':        round(balance, 2),
            'cash':           account.get('cash', 0),
            'buying_power':   account.get('buying_power', 0),
            'total_pnl':      round(total_pnl, 2),
            'total_pnl_pct':  round(total_pnl / STARTING_BALANCE * 100, 2),
            'open_positions': positions,
            'trades_today':   len(closed_today),
            'total_trades':   len(all_closed),
            'win_rate':       round(win_rate, 1),
            'status':         _status,
        }
        save_json(DASHBOARD_PATH, dashboard)
    except Exception as e:
        log.error('Dashboard update error: %s', e)


# ── Safety floor ───────────────────────────────────────────────────────────────

def _check_safety_floor() -> bool:
    global _paused
    balance = _trader.get_balance()

    if balance <= 0:
        log.warning('Safety check: could not read balance')
        return True

    if balance < SAFETY_FLOOR:
        if not _paused:
            log.error(
                'SAFETY FLOOR HIT: $%.2f < floor $%.2f — PAUSING',
                balance, SAFETY_FLOOR,
            )
            send_telegram(
                f"🤵 JERRY — SAFETY FLOOR HIT\n"
                f"Balance: ${balance:,.2f}  Floor: ${SAFETY_FLOOR:,.2f}\n"
                f"All trading PAUSED. Manual intervention required."
            )
            _paused = True
            _update_dashboard('paused')
        return False

    if _paused:
        log.info('Balance $%.2f recovered above floor — RESUMING', balance)
        send_telegram(f"🤵 JERRY — RESUMED (balance ${balance:,.2f})")
        _paused = False

    return True


# ── Watchlist execution ────────────────────────────────────────────────────────

def _parse_entry_zone(entry_zone: str) -> tuple[float, float]:
    """Parse '850-860' → (850.0, 860.0) or '855' → (846.0, 864.0) ±1%."""
    try:
        if '-' in str(entry_zone):
            parts = str(entry_zone).split('-')
            return float(parts[0]), float(parts[1])
        price = float(str(entry_zone).replace('$', ''))
        margin = price * 0.01
        return price - margin, price + margin
    except Exception:
        return 0.0, float('inf')


def _is_price_in_zone(price: float, entry_zone: str) -> bool:
    low, high = _parse_entry_zone(entry_zone)
    return low <= price <= high


def _calculate_qty_from_pct(balance: float, pct: float, price: float) -> int:
    notional = balance * (pct / 100)
    # Cap at 15% regardless of what discovery suggested
    max_notional = balance * 0.15
    notional = min(notional, max_notional)
    if price <= 0:
        return 0
    return max(1, int(notional / price))


def _run_trading_tick() -> None:
    """5-minute tick: check watchlist entries and manage open positions."""
    watchlist_data = load_json(WATCHLIST_PATH, {})
    watchlist      = watchlist_data.get('watchlist', [])

    if not watchlist:
        log.debug('Watchlist empty — nothing to check')
        return

    open_symbols = _trader.get_open_symbols()
    account      = _trader.get_account()
    balance      = account.get('portfolio_value', STARTING_BALANCE)

    # Track symbols already processed this tick to avoid duplicate orders
    executed_this_tick = set()

    for item in watchlist:
        symbol  = item.get('symbol', '')
        action  = item.get('action', 'buy')
        typ     = item.get('type', 'stock')
        conf    = item.get('confidence', 'low')
        size_pct = float(item.get('position_size_pct', 5))

        if not symbol:
            continue

        # Skip if already in position or already executed this tick
        if symbol in open_symbols or symbol in executed_this_tick:
            continue

        # Skip low-confidence unless Sentinel signal backs it
        if conf == 'low' and not item.get('sentinel_signal'):
            continue

        if typ == 'stock':
            # ── Stock execution ──────────────────────────────────────────────
            entry_zone = item.get('entry_zone', '')
            if not entry_zone:
                continue

            snap  = _trader.get_snapshot(symbol)
            price = snap.get('price', 0)
            if price <= 0:
                continue

            if not _is_price_in_zone(price, entry_zone):
                log.debug('%s price $%.2f not in zone %s', symbol, price, entry_zone)
                continue

            # Parse SL/TP
            try:
                sl = float(str(item.get('stop_loss', '')).replace('$', ''))
            except (ValueError, TypeError):
                sl = None
            try:
                tp = float(str(item.get('target', '')).replace('$', ''))
            except (ValueError, TypeError):
                tp = None

            notional = balance * (size_pct / 100)
            notional = min(notional, balance * 0.15)  # hard cap 15%

            log.info(
                'ENTRY SIGNAL: %s %s @ $%.2f | zone=%s | conf=%s | $%.0f',
                action.upper(), symbol, price, entry_zone, conf, notional,
            )

            if action == 'buy':
                result = _trader.buy_stock(
                    symbol=symbol, notional=notional,
                    stop_loss=sl, take_profit=tp,
                    strategy_name=item.get('timeframe', 'Swing'),
                    thesis=item.get('thesis', ''),
                )
            elif action == 'short':
                result = _trader.short_stock(
                    symbol=symbol, notional=notional,
                    stop_loss=sl, take_profit=tp,
                    strategy_name='Short',
                    thesis=item.get('thesis', ''),
                )
            else:
                continue

            if result:
                executed_this_tick.add(symbol)

        elif typ == 'option':
            # ── Options execution ────────────────────────────────────────────
            underlying  = item.get('underlying', symbol)
            option_type = item.get('option_type', 'call')
            strike      = item.get('strike')
            expiry      = item.get('expiry')

            if not all([strike, expiry]):
                log.debug('Options item %s missing strike/expiry', symbol)
                continue

            # Build OCC symbol
            occ = _trader.build_occ_symbol(
                underlying=underlying,
                expiry=expiry,
                option_type=option_type,
                strike=float(strike),
            )

            # Check if we already have this options position
            if occ in open_symbols:
                continue

            # For sell_put / sell_call: check if premium is near target
            premium_target_str = item.get('premium_target', '0')
            try:
                premium_target = float(str(premium_target_str).replace('$', ''))
            except (ValueError, TypeError):
                premium_target = 0

            # Qty: ~2-3% of account per options trade (max risk = max_risk field)
            max_risk   = item.get('max_risk', balance * 0.03)
            qty_contracts = max(1, int(float(max_risk) / (float(strike) * 100 * 0.03)))
            qty_contracts = min(qty_contracts, 5)  # cap at 5 contracts

            log.info(
                'OPTIONS: %s %s occ=%s x%d contracts',
                action.upper(), symbol, occ, qty_contracts,
            )

            if action in ('buy_call', 'buy_put', 'buy'):
                result = _trader.buy_option(
                    occ_symbol=occ, qty=qty_contracts,
                    strategy_name=action,
                    thesis=item.get('thesis', ''),
                )
            elif action in ('sell_put', 'sell_call', 'sell'):
                result = _trader.sell_option(
                    occ_symbol=occ, qty=qty_contracts,
                    strategy_name=action,
                    thesis=item.get('thesis', ''),
                )
            else:
                continue

            if result:
                executed_this_tick.add(occ)

    # ── Manage open positions ─────────────────────────────────────────────────
    _manage_positions(watchlist)


def _manage_positions(watchlist: list) -> None:
    """
    Review open positions. Close any that hit manual SL/TP thresholds
    (backup to bracket orders). Also enforce time stops from watchlist.
    """
    positions = _trader.get_positions()
    if not positions:
        return

    # Build watchlist lookup: symbol → item
    wl_map = {item.get('symbol'): item for item in watchlist}
    history = load_json(TRADE_HISTORY_PATH, [])
    open_trades = {
        t.get('symbol'): t for t in history
        if t.get('status') == 'open'
    }

    for pos in positions:
        symbol  = pos['symbol']
        current = float(pos.get('current_price', 0))
        entry   = float(pos.get('avg_entry_price', 0))
        side    = pos.get('side', 'long')

        if current <= 0 or entry <= 0:
            continue

        trade = open_trades.get(symbol)
        if not trade:
            continue

        sl = trade.get('stop_loss')
        tp = trade.get('take_profit')

        # Manual SL/TP check (backup — bracket orders handle this on exchange)
        if side == 'long':
            if sl and current <= float(sl):
                log.info('SL hit for %s: current=%.2f <= sl=%.2f', symbol, current, float(sl))
                _trader.close_position(symbol, reason='stop_loss')
                continue
            if tp and current >= float(tp):
                log.info('TP hit for %s: current=%.2f >= tp=%.2f', symbol, current, float(tp))
                _trader.close_position(symbol, reason='take_profit')
                continue
        else:  # short
            if sl and current >= float(sl):
                log.info('SL hit for %s (short): current=%.2f >= sl=%.2f', symbol, current, float(sl))
                _trader.close_position(symbol, reason='stop_loss')
                continue
            if tp and current <= float(tp):
                log.info('TP hit for %s (short): current=%.2f <= tp=%.2f', symbol, current, float(tp))
                _trader.close_position(symbol, reason='take_profit')
                continue

        # Time stop for day-trade style plays
        wl_item    = wl_map.get(symbol, {})
        timeframe  = wl_item.get('timeframe', '')
        opened_at  = trade.get('opened_at', '')
        if 'day' in timeframe.lower() and opened_at:
            try:
                from datetime import datetime as _dt
                opened_dt = _dt.fromisoformat(opened_at)
                age_mins  = (datetime.now(timezone.utc) - opened_dt).total_seconds() / 60
                if age_mins > 360:   # 6 hour hard stop for day trades
                    log.info('Time stop: %s held %.0fm (day trade) — closing', symbol, age_mins)
                    _trader.close_position(symbol, reason='time_stop')
            except Exception:
                pass


# ── Discovery cycle ────────────────────────────────────────────────────────────

def _run_discovery() -> None:
    global _discovery_done_today
    log.info('=== DISCOVERY STARTING ===')
    _update_dashboard('discovering')

    try:
        sentinel_data = load_json(SENTINEL_DATA, {})
        trade_history = load_json(TRADE_HISTORY_PATH, [])
        account       = _trader.get_account()
        positions     = _trader.get_positions()

        portfolio = {'account': account, 'positions': positions}

        result = discover_opportunities(portfolio, sentinel_data, trade_history)

        wl = result.get('watchlist', [])
        log.info('Discovery complete: %d plays in watchlist', len(wl))
        _discovery_done_today = True

    except Exception as e:
        log.error('Discovery error: %s', e, exc_info=True)


# ── Review cycle ───────────────────────────────────────────────────────────────

def _run_review() -> None:
    global _review_done_today
    log.info('=== REVIEW STARTING ===')
    _update_dashboard('reviewing')

    try:
        trade_history = load_json(TRADE_HISTORY_PATH, [])
        account       = _trader.get_account()
        positions     = _trader.get_positions()
        portfolio     = {'account': account, 'positions': positions}

        review_day(trade_history, portfolio)
        _review_done_today = True
        log.info('Review complete')

    except Exception as e:
        log.error('Review error: %s', e, exc_info=True)


# ── Daily wrap (22:00 UTC) ────────────────────────────────────────────────────

def _is_wrap_window(now) -> bool:
    return now.hour == 22 and now.minute < 5


def _send_daily_wrap() -> None:
    global _wrap_done_today
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    try:
        history   = load_json(TRADE_HISTORY_PATH, [])
        if not isinstance(history, list):
            history = []
        closed_today = [
            t for t in history
            if t.get('status') == 'closed' and (t.get('closed_at') or '').startswith(today)
        ]
        account   = _trader.get_account()
        positions = _trader.get_positions()
        balance   = account.get('portfolio_value', 0.0)
        cash      = account.get('cash', 0.0)
        daily_pnl = sum(float(t.get('pnl', 0) or 0) for t in closed_today)

        lines = [
            f"🤖 JERRY — DAILY WRAP",
            f"Date: {today}",
            "",
            f"Trades today: {len(closed_today)}",
        ]
        if closed_today:
            for t in closed_today:
                sym    = t.get('symbol', '?')
                kind   = 'option' if t.get('asset_type') == 'option' else 'stock'
                pnl    = float(t.get('pnl', 0) or 0)
                reason = t.get('close_reason') or 'closed'
                if pnl > 0:
                    pnl_str = f"+${pnl:.2f}"
                elif pnl < 0:
                    pnl_str = f"-${abs(pnl):.2f}"
                else:
                    pnl_str = "$0"
                lines.append(f"- {sym} {kind} → {reason} | {pnl_str}")
        else:
            lines.append("- (none)")

        if daily_pnl > 0:
            dpnl = f"+${daily_pnl:.2f}"
        elif daily_pnl < 0:
            dpnl = f"-${abs(daily_pnl):.2f}"
        else:
            dpnl = "$0"

        lines += [
            "",
            f"Daily P&L: {dpnl}",
            f"Open positions: {len(positions)}",
            f"Portfolio value: ${balance:,.2f} | Cash: ${cash:,.2f}",
        ]
        send_telegram(wrap_message('jerry', '\n'.join(lines)))
        _wrap_done_today = True
        log.info('Daily wrap sent (%d trades, P&L $%.2f)', len(closed_today), daily_pnl)
    except Exception as e:
        log.error('Daily wrap error: %s', e, exc_info=True)


# ── Date tracking ──────────────────────────────────────────────────────────────

def _check_date_rollover() -> None:
    """Reset daily flags when the date changes. Also check if watchlist was already
    written today (e.g. by a manual test run) to avoid duplicate discovery."""
    global _discovery_done_today, _review_done_today, _wrap_done_today, _last_date
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    if today != _last_date:
        _last_date            = today
        _review_done_today    = False
        _wrap_done_today      = False
        # Check if watchlist.json was already populated today
        wl_data = load_json(WATCHLIST_PATH, {})
        meta    = wl_data.get('_meta', {})
        if (meta.get('timestamp') or '').startswith(today) and wl_data.get('watchlist'):
            log.info('Watchlist already populated today (%d plays) — skipping discovery',
                     len(wl_data['watchlist']))
            _discovery_done_today = True
        else:
            _discovery_done_today = False

        # Check if review was already run today (check performance.json)
        perf = load_json(PERFORMANCE_PATH, [])
        if isinstance(perf, list) and perf:
            last_review = perf[-1]
            if last_review.get('date', '') == today or \
               (last_review.get('_meta', {}).get('timestamp') or '').startswith(today):
                log.info('Review already done today — skipping')
                _review_done_today = True

        log.info('New trading day: %s', today)


# ── Main loop ─────────────────────────────────────────────────────────────────

def run() -> None:
    global _trader

    _trader = JerryTrader()

    log.info('=== JERRY STARTING ===')
    log.info('Starting balance: $%.2f  Safety floor: $%.2f',
             STARTING_BALANCE, SAFETY_FLOOR)

    account = _trader.get_account()
    balance = account.get('portfolio_value', 0)

    send_telegram(
        f"🤵 JERRY — ONLINE\n"
        f"Account: ${balance:,.2f} | Floor: ${SAFETY_FLOOR:,.0f}\n"
        f"Paper trading: paper-api.alpaca.markets\n"
        f"Cycle: 5m tick | Discovery 13:00 UTC | Review 20:30 UTC\n"
        f"Sentinel: insider data loaded"
    )

    _update_dashboard('initializing')

    while not _shutdown:
        loop_start = time.time()

        try:
            _check_date_rollover()

            now = datetime.now(timezone.utc)

            # Weekend — sleep
            if not is_weekday(now):
                if _status != 'sleeping':
                    log.info('Weekend — Jerry sleeping')
                    _update_dashboard('sleeping')
                _interruptible_sleep(60)
                continue

            # Safety floor
            if not _check_safety_floor():
                _interruptible_sleep(MAIN_LOOP_SECS)
                continue

            # ── Pre-market discovery (13:00-13:30 UTC) ───────────────────────
            if (is_discovery_window(now) and
                    not is_market_hours(now) and
                    not _discovery_done_today):
                _run_discovery()

            # ── Market hours: 5-minute trading tick ──────────────────────────
            if is_market_hours(now):
                _update_dashboard('trading')
                try:
                    _run_trading_tick()
                except Exception as e:
                    log.error('Trading tick error: %s', e, exc_info=True)
                _update_dashboard('trading')

            # ── Post-market review (20:30 UTC) ────────────────────────────────
            elif (is_review_window(now) and
                  not _review_done_today and
                  _discovery_done_today):   # only review if we had a real trading day
                _run_review()
                _update_dashboard('market_closed')

            # ── Outside market hours ──────────────────────────────────────────
            else:
                if is_market_hours(now):
                    pass  # handled above
                else:
                    _update_dashboard('market_closed')

            # ── Daily wrap (22:00 UTC) ────────────────────────────────────────
            if _is_wrap_window(now) and not _wrap_done_today:
                _send_daily_wrap()

        except Exception as e:
            log.error('Main loop error: %s', e, exc_info=True)

        # Sleep for remainder of tick window
        elapsed    = time.time() - loop_start
        sleep_time = max(5, MAIN_LOOP_SECS - elapsed) if is_market_hours() else 60
        log.debug('Tick %.1fs — sleeping %.0fs', elapsed, sleep_time)
        _interruptible_sleep(sleep_time)

    log.info('=== JERRY SHUTDOWN COMPLETE ===')
    send_telegram("🤵 JERRY — OFFLINE (graceful shutdown)")


def _interruptible_sleep(seconds: float) -> None:
    deadline = time.time() + seconds
    while not _shutdown and time.time() < deadline:
        time.sleep(1)


if __name__ == '__main__':
    run()
