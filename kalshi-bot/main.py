"""
main.py — Main event loop for the Kalshi bot (Claude-brain edition).

DRY_RUN = True  → simulate only, no real orders
DRY_RUN = False → live trading

Architecture (v2 — 2026-04-15):
  • Every 60s: scan all open markets (1-48h window), manage pending orders
  • Smart throttle: call Claude brain when cache expires OR new markets appear
    OR a watched price moves > 5%.  Targets 10-20 brain calls/day (~$3-6/day).
  • Brain recommendations are cached and executed on every loop until expired.
  • Legacy 15M momentum scoring retained in strategy.py but disabled (returns []).

Safety features:
  • Unfilled limit orders cancelled after ORDER_FILL_TIMEOUT seconds
  • Every Kalshi API segment wrapped in try/except; one failure can't crash the loop
  • On restart, today's trade count and P&L are recovered from trades_log.csv
    so hard limits aren't accidentally reset mid-day
  • Balance circuit-breaker halts trading for 30 min if Kalshi balance depleted
"""

import csv
import json
import logging
import signal
import time
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ── Balance circuit-breaker ───────────────────────────────────────────────────
# If we get INSUF_BALANCE_THRESHOLD consecutive insufficient_balance errors,
# refresh the real Kalshi balance. If it's still below the minimum trade size,
# halt all trading for INSUF_BALANCE_HALT_SECS seconds and log a CRITICAL alert.
INSUF_BALANCE_THRESHOLD  = 3       # consecutive errors before triggering
INSUF_BALANCE_HALT_SECS  = 1800    # 30 min halt before retrying

_insuf_balance_streak: int    = 0
_insuf_balance_halt_until: float = 0.0

# ── Brain throttle ────────────────────────────────────────────────────────────
# Smart throttling prevents excessive API costs while staying responsive.
# Normal cache: 30 min.  Quiet hours (00:00–06:00 UTC): 2 hours.
# Hard cap: 20 brain calls/day regardless of triggers.
# Triggers that fire a call early: new tickers appear, or >5% price move.

BRAIN_CACHE_SECS        = 3600   # 60 min normal cache window
BRAIN_CACHE_QUIET_SECS  = 14400  # 4 h quiet-hours cache (midnight–06:00 UTC)
BRAIN_MAX_CALLS_PER_DAY = 10     # hard daily cap
PRICE_CHANGE_THRESHOLD  = 0.05   # 5% move on a watched ticker triggers refresh

_brain_recs:       list[dict]     = []    # cached recommendations from last brain call
_last_brain_call:  float          = 0.0  # time.time() of last call
_brain_calls_today: int           = 0
_brain_calls_date:  str           = ''
_known_tickers:    set[str]       = set()          # tickers seen on last scan
_watched_prices:   dict[str, float] = {}           # ticker → last YES mid-price

# ── Configuration ─────────────────────────────────────────────────────────────

from config import MAX_DAILY_TRADES, MAX_OPEN_POSITIONS

DRY_RUN            = False  # ← LIVE TRADING
LOOP_INTERVAL      = 60     # seconds between scans
ORDER_FILL_TIMEOUT = 120    # seconds before an unfilled order is cancelled
LOG_LEVEL          = logging.INFO

TRADES_CSV  = Path(__file__).parent / "trades_log.csv"
CSV_COLUMNS = [
    "timestamp", "ticker", "direction", "size",
    "entry_price", "contracts", "order_id", "status",
    "settlement_result", "settlement_pnl",
]

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)-8s %(name)-12s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")

logging.getLogger("strategy").setLevel(logging.WARNING)
logging.getLogger("risk").setLevel(logging.WARNING)
logging.getLogger("trader").setLevel(logging.WARNING)
logging.getLogger("scanner").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)

# ── CSV helpers ───────────────────────────────────────────────────────────────

def _ensure_csv():
    if not TRADES_CSV.exists():
        with TRADES_CSV.open("w", newline="") as f:
            csv.DictWriter(f, fieldnames=CSV_COLUMNS).writeheader()
        log.info("Created %s", TRADES_CSV)


def _log_trade(
    ticker: str,
    direction: str,
    size: float,
    entry_price: int,
    contracts: int,
    order_id: str,
    status: str,
    settlement_result: str = "",
    settlement_pnl: str = "",
):
    row = {
        "timestamp":        datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ticker":           ticker,
        "direction":        direction,
        "size":             f"{size:.2f}",
        "entry_price":      entry_price,
        "contracts":        contracts,
        "order_id":         order_id,
        "status":           status,
        "settlement_result": settlement_result,
        "settlement_pnl":   settlement_pnl,
    }
    with TRADES_CSV.open("a", newline="") as f:
        csv.DictWriter(f, fieldnames=CSV_COLUMNS).writerow(row)


# ── CSV state recovery ────────────────────────────────────────────────────────

def _load_today_from_csv() -> tuple[int, float]:
    """
    Read trades_log.csv and return (trades_today_count, daily_pnl) for today.

    Called on startup so a restart mid-day doesn't reset the trade counter
    or P&L tracker against the daily limits.

    P&L is approximated as:
      filled contracts × (1.00 - entry_price) for YES wins (settled = 100¢)
      filled contracts × entry_price           for YES losses (settled = 0¢)

    Because we don't store settlement outcomes in the CSV we can't know actual
    P&L precisely — so we restore trade count (hard safety) and leave P&L at 0
    (conservative: the loss-limit basis is today's opening balance from Kalshi,
    which already reflects any realised gains/losses).

    Returns:
        trades_count: number of non-error, non-cancelled rows today
        daily_pnl:    always 0.0 (see above)
    """
    if not TRADES_CSV.exists():
        return 0, 0.0

    today_str = date.today().isoformat()   # "2026-03-26"
    count = 0
    pnl   = 0.0

    try:
        with TRADES_CSV.open(newline="") as f:
            for row in csv.DictReader(f):
                ts = row.get("timestamp", "")
                if not ts.startswith(today_str):
                    continue
                status = row.get("status", "")
                if status.startswith("error") or status == "cancelled":
                    continue
                if status == "settled":
                    # Recover actual P&L from settlement rows
                    try:
                        pnl += float(row.get("settlement_pnl") or 0)
                    except ValueError:
                        pass
                    continue
                count += 1
    except Exception as exc:
        log.warning("Could not parse trades_log.csv for recovery: %s", exc)

    return count, pnl


def _restore_risk_state(rm):
    """
    Inject today's trade count recovered from CSV into an already-constructed
    RiskManager so can_trade() enforces the correct remaining allowance.
    """
    from risk import TradeRecord
    count, _ = _load_today_from_csv()
    if count == 0:
        return

    # Populate trades_today with placeholder records (ticker/direction/size
    # don't affect the gate — only len(trades_today) does).
    for i in range(count):
        rm.trades_today.append(
            TradeRecord(ticker=f"recovered-{i}", direction="YES", size=0.0, price=0)
        )
    log.info("Recovered %d trade(s) from today's CSV — %d remaining today",
             count, max(0, MAX_DAILY_TRADES - count))


# ── Settlement checker ───────────────────────────────────────────────────────
# Called after sync_open_positions to log outcomes for any positions that just
# settled.  Snapshots open_positions BEFORE sync; after sync, any disappeared
# tickers are settled — we query Kalshi for the YES/NO result and log to CSV.

_pre_sync_positions: dict = {}   # ticker → Position snapshot taken before sync


def _snapshot_positions(rm) -> None:
    """Save a copy of current open positions before sync clears settled ones."""
    global _pre_sync_positions
    _pre_sync_positions = dict(rm.open_positions)


def _check_and_log_settlements(rm) -> None:
    """
    After sync_open_positions has run, identify tickers that disappeared
    (i.e. just settled).  For each, query Kalshi for the settlement result,
    call rm.record_close, and append a settlement row to trades_log.csv.
    """
    from config import kalshi_get

    settled = [t for t in _pre_sync_positions if t not in rm.open_positions]
    if not settled:
        return

    for ticker in settled:
        pos = _pre_sync_positions[ticker]
        try:
            data   = kalshi_get(f"/markets/{ticker}")
            market = data.get("market", data)
            status = market.get("status", "")
            result = market.get("result", "")   # "yes" | "no" | ""

            if not result:
                # Market closed/expired but no result yet — skip logging
                log.debug("Settlement: %s closed but no result yet", ticker)
                continue

            # Binary settlement: YES wins → 100¢, NO wins → 0¢
            settle_cents = 100 if result.lower() == "yes" else 0
            rm.record_close(ticker, settle_cents)

            # Recalculate P&L for the CSV row
            entry_dollars = pos.entry_price / 100.0
            contracts     = (pos.size_dollars / entry_dollars) if entry_dollars > 0 else 0
            if pos.direction == "YES":
                pnl = contracts * (settle_cents / 100.0 - entry_dollars)
            else:
                no_cost   = 1.0 - entry_dollars
                no_payout = 1.0 - settle_cents / 100.0
                pnl       = contracts * (no_payout - no_cost)

            won = (pos.direction == "YES" and result.lower() == "yes") or \
                  (pos.direction == "NO"  and result.lower() == "no")
            settlement_result = "WIN" if won else "LOSS"

            _log_trade(
                ticker=ticker,
                direction=pos.direction,
                size=pos.size_dollars,
                entry_price=pos.entry_price,
                contracts=int(contracts),
                order_id="settlement",
                status="settled",
                settlement_result=settlement_result,
                settlement_pnl=f"{pnl:+.2f}",
            )
            log.info(
                "SETTLED %s %s — result=%s  P&L=%+.2f",
                pos.direction, ticker, result.upper(), pnl,
            )

        except Exception as exc:
            log.warning("Settlement check failed for %s: %s", ticker, exc)


# ── Pending order tracker ─────────────────────────────────────────────────────
# Tracks resting limit orders so we can cancel them if unfilled after timeout.
# Structure: {order_id: {"ticker": str, "placed_at": float, "direction": str,
#                        "size": float, "entry_price": int}}

_pending_orders: dict[str, dict] = {}


def _register_pending(order_id: str, ticker: str, direction: str,
                      size: float, entry_price: int):
    _pending_orders[order_id] = {
        "ticker":      ticker,
        "placed_at":   time.time(),
        "direction":   direction,
        "size":        size,
        "entry_price": entry_price,
    }
    log.debug("Tracking pending order %s for %s", order_id, ticker)


def _check_pending_orders(rm):
    """
    For each tracked resting order:
      • If filled → remove from tracker, log status update.
      • If age > ORDER_FILL_TIMEOUT → cancel via API, free the position slot,
        append a "cancelled" row to the CSV.

    Runs at the start of every loop iteration.
    """
    if not _pending_orders or DRY_RUN:
        return

    from trader import get_order_status, cancel_order

    now      = time.time()
    to_clear = []

    for order_id, info in list(_pending_orders.items()):
        age = now - info["placed_at"]

        try:
            status = get_order_status(order_id)
        except Exception as exc:
            log.warning("Status check failed for order %s: %s", order_id, exc)
            continue

        if status in ("filled", "partially_filled"):
            log.info("Order %s filled for %s (%.0fs after placement)",
                     order_id, info["ticker"], age)
            to_clear.append(order_id)

        elif status in ("cancelled", "expired"):
            log.info("Order %s is already %s", order_id, status)
            rm.open_positions.pop(info["ticker"], None)
            to_clear.append(order_id)

        elif age > ORDER_FILL_TIMEOUT:
            log.warning(
                "Order %s for %s unfilled after %.0fs — cancelling",
                order_id, info["ticker"], age,
            )
            cancelled = cancel_order(order_id)
            if cancelled:
                # Free the position slot so the bot can enter elsewhere
                rm.open_positions.pop(info["ticker"], None)
                _log_trade(
                    ticker=info["ticker"],
                    direction=info["direction"],
                    size=info["size"],
                    entry_price=info["entry_price"],
                    contracts=0,
                    order_id=order_id,
                    status="cancelled",
                )
            to_clear.append(order_id)

    for oid in to_clear:
        _pending_orders.pop(oid, None)


# ── Status line ───────────────────────────────────────────────────────────────

def _status_line(rm, loop_n: int, markets_found: int, trades_placed: int):
    s        = rm.status()
    now      = datetime.now().strftime("%H:%M:%S")
    mode     = "[DRY RUN]" if DRY_RUN else "[LIVE]   "
    pnl_sign = "+" if s["daily_pnl"] >= 0 else ""
    pending  = len(_pending_orders)
    cache_age = int(time.time() - _last_brain_call) if _last_brain_call > 0 else -1
    cache_str = f"{cache_age}s ago" if cache_age >= 0 else "never"

    print(
        f"{mode} [{now}] loop #{loop_n:03d} | "
        f"Trades: {s['trades_today']:>2}/{s.get('trades_remaining', 0) + s['trades_today']} | "
        f"Open: {s['open_positions']}/{MAX_OPEN_POSITIONS} | "
        f"Pending: {pending} | "
        f"P&L: {pnl_sign}${s['daily_pnl']:.2f} | "
        f"Bankroll: ${s['bankroll']:.2f} | "
        f"Markets: {markets_found} | "
        f"Brain: {len(_brain_recs)} recs ({cache_str}) | "
        f"Placed: {trades_placed} | "
        f"Next: {LOOP_INTERVAL}s"
    )


# ── Graceful shutdown ─────────────────────────────────────────────────────────

_running = True

KALSHI_DAILY_JSON = Path("/tmp/jcf_kalshi_daily.json")
_daily_summary_written_date: Optional[str] = None   # tracks which date we already wrote


def _write_daily_summary(rm) -> None:
    """Write yesterday's trade stats to /tmp/jcf_kalshi_daily.json at 06:45 UTC.

    Called once per calendar-day when UTC time crosses 06:45.
    Reads yesterday's rows from trades_log.csv and writes a summary JSON that
    daily_briefing.py can consume at 07:00 UTC.
    """
    yest_str  = (date.today() - timedelta(days=1)).isoformat()
    trades    = 0
    wins      = 0
    losses    = 0
    pnl       = 0.0

    try:
        if TRADES_CSV.exists():
            with TRADES_CSV.open(newline="") as f:
                for row in csv.DictReader(f):
                    ts = row.get("timestamp", "")
                    if not ts.startswith(yest_str):
                        continue
                    status = row.get("status", "")
                    if status.startswith("error") or status == "cancelled":
                        continue
                    if status == "settled":
                        result = row.get("settlement_result", "")
                        if result == "WIN":
                            wins += 1
                        elif result == "LOSS":
                            losses += 1
                        try:
                            pnl += float(row.get("settlement_pnl") or 0)
                        except ValueError:
                            pass
                        continue
                    trades += 1
    except Exception as exc:
        log.warning("_write_daily_summary: CSV read error: %s", exc)

    s         = rm.status()
    bankroll  = s.get("bankroll", 0)

    summary = {
        "date":     yest_str,
        "trades":   trades,
        "wins":     wins,
        "losses":   losses,
        "pnl":      round(pnl, 2),
        "bankroll": round(bankroll, 2),
        "written":  datetime.now(timezone.utc).isoformat(),
    }

    try:
        KALSHI_DAILY_JSON.write_text(json.dumps(summary, indent=2))
        log.info("Daily summary written to %s: %s", KALSHI_DAILY_JSON, summary)
    except Exception as exc:
        log.warning("_write_daily_summary: write error: %s", exc)


def _handle_sigint(sig, frame):
    global _running
    print("\n[main] Caught SIGINT — finishing current loop then exiting.")
    _running = False

signal.signal(signal.SIGINT,  _handle_sigint)
signal.signal(signal.SIGTERM, _handle_sigint)


# ── Brain helpers ────────────────────────────────────────────────────────────

def _is_quiet_hours() -> bool:
    """True between midnight and 06:00 UTC (thin markets, extend cache)."""
    return 0 <= datetime.now(timezone.utc).hour < 6


def _should_call_brain(all_markets: list) -> bool:
    """
    Return True if a fresh brain call is warranted.

    Checks (in priority order):
      1. Hard daily cap reached → False
      2. Cache period not expired AND no triggers → False
      3. Cache expired → True
      4. New tickers appeared since last call → True
      5. Watched price moved > PRICE_CHANGE_THRESHOLD → True
    """
    global _brain_calls_today, _brain_calls_date

    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    if _brain_calls_date != today:
        _brain_calls_date  = today
        _brain_calls_today = 0

    if _brain_calls_today >= BRAIN_MAX_CALLS_PER_DAY:
        log.debug("Brain: daily cap %d reached", BRAIN_MAX_CALLS_PER_DAY)
        return False

    cache_secs = BRAIN_CACHE_QUIET_SECS if _is_quiet_hours() else BRAIN_CACHE_SECS
    elapsed    = time.time() - _last_brain_call

    if elapsed >= cache_secs:
        return True  # cache expired

    # Trigger: new tickers appeared
    current_tickers = {m['ticker'] for m in all_markets}
    new_tickers = current_tickers - _known_tickers
    if new_tickers:
        log.info("Brain trigger: %d new tickers appeared", len(new_tickers))
        return True

    # Trigger: significant price move on a watched ticker
    for m in all_markets:
        ticker = m.get('ticker', '')
        if ticker not in _watched_prices:
            continue
        try:
            bid = float(m.get('yes_bid_dollars') or 0)
            ask = float(m.get('yes_ask_dollars') or 0)
            mid = (bid + ask) / 2.0
        except (TypeError, ValueError):
            continue
        last_mid = _watched_prices[ticker]
        if last_mid > 0 and abs(mid - last_mid) / last_mid > PRICE_CHANGE_THRESHOLD:
            log.info("Brain trigger: %s price moved %.1f%% (%.2f → %.2f)",
                     ticker, (mid - last_mid) / last_mid * 100, last_mid, mid)
            return True

    return False


def _update_brain_state(all_markets: list) -> None:
    """Record the current ticker set and mid-prices for trigger detection."""
    global _known_tickers, _watched_prices
    _known_tickers = {m['ticker'] for m in all_markets}
    for m in all_markets:
        ticker = m.get('ticker', '')
        if not ticker:
            continue
        try:
            bid = float(m.get('yes_bid_dollars') or 0)
            ask = float(m.get('yes_ask_dollars') or 0)
            mid = (bid + ask) / 2.0
            if mid > 0:
                _watched_prices[ticker] = mid
        except (TypeError, ValueError):
            pass


def _execute_brain_recs(rm) -> int:
    """
    Execute trades from the cached brain recommendations.

    For each valid recommendation:
      - Skip if ticker already in open_positions
      - Use brain's limit_price as entry (cents)
      - Use brain's position_size_usd, capped to 5% of current bankroll
      - Remove from cache after placing to prevent re-entry

    Returns number of trades placed this call.
    """
    global _brain_recs, _insuf_balance_streak, _insuf_balance_halt_until

    if not _brain_recs:
        return 0

    from trader import place_trade

    placed     = 0
    to_execute = list(_brain_recs)  # snapshot — we'll modify _brain_recs live

    for rec in to_execute:
        ticker    = rec.get('ticker', '')
        direction = rec.get('direction', '').upper()
        if direction not in ('YES', 'NO'):
            log.debug("Brain rec %s: invalid direction '%s', skipping",
                      ticker, rec.get('direction'))
            continue

        limit_price = int(rec.get('limit_price', 0))
        if not (1 <= limit_price <= 99):
            log.debug("Brain rec %s: invalid limit_price %d, skipping",
                      ticker, limit_price)
            continue

        # Risk gate
        try:
            can, reason = rm.can_trade()
        except Exception as exc:
            log.error("can_trade() raised in brain exec: %s", exc)
            break
        if not can:
            log.debug("Brain exec: risk gate closed — %s", reason)
            break

        if ticker in rm.open_positions:
            continue

        # Position sizing: brain Kelly, capped at 5% of bankroll
        brain_size = float(rec.get('position_size_usd', 0))
        max_size   = rm.current_bankroll * 0.05
        size       = max(1.00, min(brain_size, max_size))

        if size > rm.current_bankroll:
            log.debug("Brain rec %s: size $%.2f > bankroll $%.2f, skipping",
                      ticker, size, rm.current_bankroll)
            continue

        log.info(
            "BRAIN TRADE: %s %s  edge=%.0f%%  conf=%s  size=$%.2f  "
            "limit=%d¢  | %s",
            direction, ticker,
            rec.get('edge_pct', 0), rec.get('confidence', '?'),
            size, limit_price,
            str(rec.get('key_factor', ''))[:80],
        )

        try:
            result = place_trade(
                ticker=ticker,
                direction=direction,
                size_dollars=size,
                entry_price_cents=limit_price,
                dry_run=DRY_RUN,
            )
        except Exception as exc:
            log.error("place_trade (brain) raised for %s: %s", ticker, exc, exc_info=True)
            continue

        if result.success:
            try:
                rm.record_open(ticker, direction, size, limit_price)
            except Exception as exc:
                log.error("record_open failed for %s: %s", ticker, exc)

            _log_trade(ticker, direction, size, limit_price,
                       result.contracts, result.order_id, result.status)

            if result.status == "resting":
                _register_pending(result.order_id, ticker, direction, size, limit_price)

            # Remove from cache after placing (don't re-enter same position)
            _brain_recs = [r for r in _brain_recs if r.get('ticker') != ticker]

            placed += 1
            log.info("Brain trade placed: %s %s  %d contracts @ %d¢  id=%s  status=%s",
                     direction, ticker, result.contracts, limit_price,
                     result.order_id, result.status)

        else:
            log.warning("Brain trade rejected for %s: %s", ticker, result.error)
            _log_trade(ticker, direction, size, limit_price, 0, "",
                       f"error: {result.error}")

            # Insufficient-balance circuit breaker (same as legacy path)
            if result.error and "insufficient_balance" in str(result.error):
                _insuf_balance_streak += 1
                if _insuf_balance_streak >= INSUF_BALANCE_THRESHOLD:
                    log.warning(
                        "insufficient_balance x%d — refreshing Kalshi balance...",
                        _insuf_balance_streak,
                    )
                    rm.refresh_balance()
                    from risk import MIN_TRADE_DOLLARS
                    if rm.current_bankroll < MIN_TRADE_DOLLARS:
                        log.critical(
                            "BALANCE DEPLETED: Kalshi balance $%.2f is below minimum "
                            "trade size $%.2f. Halting trading for %ds. "
                            "Fund the Kalshi account to resume.",
                            rm.current_bankroll, MIN_TRADE_DOLLARS,
                            INSUF_BALANCE_HALT_SECS,
                        )
                        _insuf_balance_halt_until = time.time() + INSUF_BALANCE_HALT_SECS
                        _insuf_balance_streak = 0
                        break
                    else:
                        log.info("Balance refresh: $%.2f — streak reset",
                                 rm.current_bankroll)
                        _insuf_balance_streak = 0
            else:
                _insuf_balance_streak = 0

    return placed


# ── Core loop iteration ───────────────────────────────────────────────────────

def run_loop_once(rm, loop_n: int) -> tuple[int, int]:
    """
    One full scan-analyse-trade cycle. Returns (markets_found, trades_placed).

    Flow:
      0a. Sync live positions (clears settled ghosts)
      0b. Cancel stale pending orders
      0c. Balance circuit-breaker gate
      1.  Pre-trade risk gate
      2.  Scan ALL open markets (1-48h window) for brain input
      3.  Call Claude brain if throttle allows (smart triggers)
      4.  Execute from brain recommendation cache (primary path)
      5.  Legacy 15M momentum signals (currently disabled in strategy.py)

    Each segment is wrapped in try/except so a single API hiccup can't abort
    the whole loop.
    """
    from strategy import analyze_15m_markets
    from scanner  import scan_all_markets
    from kalshi_brain import analyze_markets as brain_analyze

    # ── 0a. Sync live positions ───────────────────────────────────────────────
    try:
        _snapshot_positions(rm)
        rm.sync_open_positions()
        _check_and_log_settlements(rm)
    except Exception as exc:
        log.error("Error in sync_open_positions: %s", exc, exc_info=True)

    # ── 0b. Cancel stale pending orders ──────────────────────────────────────
    try:
        _check_pending_orders(rm)
    except Exception as exc:
        log.error("Error in pending-order check: %s", exc, exc_info=True)

    markets_found = 0
    trades_placed = 0

    # ── 0c. Insufficient-balance circuit breaker ──────────────────────────────
    global _insuf_balance_streak, _insuf_balance_halt_until
    if time.time() < _insuf_balance_halt_until:
        remaining = int(_insuf_balance_halt_until - time.time())
        log.debug("Balance halt active — %ds remaining", remaining)
        return 0, 0

    # ── 1. Pre-trade risk gate ────────────────────────────────────────────────
    try:
        can, reason = rm.can_trade()
    except Exception as exc:
        log.error("can_trade() raised: %s", exc, exc_info=True)
        return 0, 0

    if not can:
        log.debug("Risk gate closed: %s", reason)
        return 0, 0

    # ── 2. Scan all open markets ──────────────────────────────────────────────
    all_markets: list = []
    try:
        all_markets = scan_all_markets(hours_min=0.5, hours_max=48.0)
        markets_found = len(all_markets)
        _update_brain_state(all_markets)
    except Exception as exc:
        log.error("scan_all_markets failed: %s", exc, exc_info=True)

    # ── 3. Call Claude brain (if throttle allows) ─────────────────────────────
    global _brain_recs, _last_brain_call, _brain_calls_today

    if all_markets and _should_call_brain(all_markets):
        try:
            log.info(
                "Calling Kalshi Brain — %d markets, bankroll $%.2f, "
                "call #%d today",
                len(all_markets), rm.current_bankroll, _brain_calls_today + 1,
            )
            brain_result = brain_analyze(all_markets, [], rm.current_bankroll)
            new_recs = brain_result.get('recommendations', [])
            _brain_recs        = new_recs
            _last_brain_call   = time.time()
            _brain_calls_today += 1
            log.info(
                "Brain returned %d recommendation(s) | %s",
                len(new_recs),
                brain_result.get('skipped_reason', '')[:80],
            )
        except Exception as exc:
            log.error("Brain analysis failed: %s", exc, exc_info=True)
    else:
        cache_age = int(time.time() - _last_brain_call)
        if _last_brain_call > 0:
            log.debug("Brain cache: %d recs, %ds old", len(_brain_recs), cache_age)

    # ── 4. Execute from brain recommendation cache (primary) ──────────────────
    try:
        brain_trades = _execute_brain_recs(rm)
        trades_placed += brain_trades
    except Exception as exc:
        log.error("Brain trade execution failed: %s", exc, exc_info=True)

    # ── 5. Legacy 15M momentum signals (disabled in strategy.py, kept here) ───
    # NOTE: analyze_15m_markets() returns [] since 2026-04-15 (superseded by
    # the brain above).  This block is kept to re-enable easily if needed.
    try:
        signals = analyze_15m_markets()
    except Exception as exc:
        log.error("Legacy market scan failed: %s", exc, exc_info=True)
        return markets_found, trades_placed

    if signals:
        log.info("%d legacy signal(s) above threshold", len(signals))
        from trader import place_trade
        for sig in signals:
            try:
                can, reason = rm.can_trade()
            except Exception as exc:
                log.error("can_trade() raised mid-loop: %s", exc)
                break
            if not can:
                log.info("Risk gate closed mid-loop: %s", reason)
                break
            if sig.ticker in rm.open_positions:
                continue

            size = rm.position_size()
            log.info("Legacy signal: %s %s  score=%d  entry=%d¢  size=$%.2f",
                     sig.ticker, sig.direction, sig.score, sig.entry_price, size)
            try:
                result = place_trade(
                    ticker=sig.ticker, direction=sig.direction,
                    size_dollars=size, entry_price_cents=sig.entry_price,
                    dry_run=DRY_RUN,
                )
            except Exception as exc:
                log.error("place_trade raised for %s: %s", sig.ticker, exc, exc_info=True)
                continue

            if result.success:
                try:
                    rm.record_open(sig.ticker, sig.direction, size, sig.entry_price)
                except Exception as exc:
                    log.error("record_open failed for %s: %s", sig.ticker, exc)
                _log_trade(sig.ticker, sig.direction, size, sig.entry_price,
                           result.contracts, result.order_id, result.status)
                if result.status == "resting":
                    _register_pending(result.order_id, sig.ticker,
                                      sig.direction, size, sig.entry_price)
                trades_placed += 1
                log.info("Legacy trade: %s %s  %d contracts @ %d¢  id=%s",
                         sig.direction, sig.ticker, result.contracts,
                         sig.entry_price, result.order_id)
            else:
                log.warning("Legacy order rejected for %s: %s", sig.ticker, result.error)
                _log_trade(sig.ticker, sig.direction, size, sig.entry_price,
                           0, "", f"error: {result.error}")
                if result.error and "insufficient_balance" in str(result.error):
                    _insuf_balance_streak += 1
                    if _insuf_balance_streak >= INSUF_BALANCE_THRESHOLD:
                        rm.refresh_balance()
                        from risk import MIN_TRADE_DOLLARS
                        if rm.current_bankroll < MIN_TRADE_DOLLARS:
                            log.critical(
                                "BALANCE DEPLETED: $%.2f. Halting %ds.",
                                rm.current_bankroll, INSUF_BALANCE_HALT_SECS,
                            )
                            _insuf_balance_halt_until = (
                                time.time() + INSUF_BALANCE_HALT_SECS
                            )
                            _insuf_balance_streak = 0
                            break
                        _insuf_balance_streak = 0
                else:
                    _insuf_balance_streak = 0

    return markets_found, trades_placed


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    global _running

    print("=" * 72)
    mode_str = "DRY RUN (no real orders)" if DRY_RUN else "*** LIVE TRADING ***"
    print(f"  Kalshi Bot v2 (Claude Brain) — {mode_str}")
    print(f"  Scan interval: {LOOP_INTERVAL}s  |  Fill timeout: {ORDER_FILL_TIMEOUT}s")
    print(f"  Brain cache: {BRAIN_CACHE_SECS}s normal / {BRAIN_CACHE_QUIET_SECS}s quiet")
    print(f"  Brain cap: {BRAIN_MAX_CALLS_PER_DAY} calls/day  |  "
          f"Max positions: {MAX_OPEN_POSITIONS}  |  Max trades/day: {MAX_DAILY_TRADES}")
    print(f"  Log: {TRADES_CSV}")
    print("=" * 72)

    _ensure_csv()

    # ── Risk manager + crash-recovery ─────────────────────────────────────────
    from risk import RiskManager
    try:
        rm = RiskManager()
    except Exception as exc:
        log.critical("Failed to initialise RiskManager: %s", exc)
        return

    _restore_risk_state(rm)

    s = rm.status()
    print(f"  Bankroll: ${s['bankroll']:.2f}  |  "
          f"Loss limit: ${s['loss_limit']:.2f}  |  "
          f"Trade size: ${s['next_size_dollars']:.2f}/trade  |  "
          f"Trades used today: {s['trades_today']}/{s.get('trades_remaining', 0) + s['trades_today']}")
    print("=" * 72)
    print()

    loop_n = 0
    global _daily_summary_written_date
    while _running:
        loop_n += 1
        loop_start = time.monotonic()

        # ── 06:45 UTC daily summary writer ────────────────────────────────────
        now_utc = datetime.now(timezone.utc)
        if now_utc.hour == 6 and now_utc.minute >= 45:
            today_str = now_utc.strftime('%Y-%m-%d')
            if _daily_summary_written_date != today_str:
                _daily_summary_written_date = today_str
                _write_daily_summary(rm)

        try:
            markets_found, trades_placed = run_loop_once(rm, loop_n)
        except Exception as exc:
            log.error("Unhandled error in loop #%d: %s", loop_n, exc, exc_info=True)
            markets_found, trades_placed = 0, 0

        _status_line(rm, loop_n, markets_found, trades_placed)

        elapsed   = time.monotonic() - loop_start
        sleep_for = max(0.0, LOOP_INTERVAL - elapsed)
        if _running and sleep_for > 0:
            time.sleep(sleep_for)

    print("\n[main] Bot stopped cleanly.")


if __name__ == "__main__":
    main()
