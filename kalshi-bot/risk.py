"""
risk.py — Bankroll tracking and risk gates for the Kalshi bot.

Hard limits:
  - Position size:  2% of current bankroll per trade
  - Max 15 trades/day
  - Stop trading if daily loss exceeds 10% of starting bankroll
  - Max 5 open positions simultaneously
  - Trade size: $1.00 minimum, $50.00 maximum

Usage:
    rm = RiskManager()
    ok, reason = rm.can_trade()
    if ok:
        size = rm.position_size()
        # ... place order ...
        rm.record_open(ticker, direction, size, entry_price_cents)

    # When market resolves:
    rm.record_close(ticker, settlement_price_cents)  # 0 or 100 for binary
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

from config import (
    kalshi_get,
    RISK_PER_TRADE_PCT,
    MAX_DAILY_TRADES,
    DAILY_LOSS_LIMIT_PCT,
    MAX_OPEN_POSITIONS,
)

log = logging.getLogger(__name__)

MIN_TRADE_DOLLARS = 1.00
MAX_TRADE_DOLLARS = 50.00


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class Position:
    ticker:        str
    direction:     str    # "YES" or "NO"
    size_dollars:  float
    entry_price:   int    # cents
    opened_at:     float = field(default_factory=time.time)


@dataclass
class TradeRecord:
    ticker:    str
    direction: str
    size:      float
    price:     int        # entry price cents
    pnl:       Optional[float] = None   # set on close


# ── RiskManager ───────────────────────────────────────────────────────────────

class RiskManager:
    """
    Single source of truth for risk state.
    Thread-safe assumptions: single-threaded event loop (no locking).
    """

    def __init__(self):
        self.starting_bankroll: float = self._fetch_balance()
        self.current_bankroll:  float = self.starting_bankroll
        self._trade_day:         date  = datetime.now(timezone.utc).date()
        self.trades_today:       list[TradeRecord]  = []
        self.open_positions:     dict[str, Position] = {}  # ticker → Position
        self.daily_pnl:          float = 0.0

        log.info(
            "RiskManager ready — bankroll $%.2f | max %d trades/day | "
            "loss limit $%.2f (%.0f%%)",
            self.starting_bankroll,
            MAX_DAILY_TRADES,
            self.starting_bankroll * DAILY_LOSS_LIMIT_PCT,
            DAILY_LOSS_LIMIT_PCT * 100,
        )

    # ── Balance ───────────────────────────────────────────────────────────────

    def _fetch_balance(self) -> float:
        """Read USD balance from Kalshi. Returns 0.0 on failure."""
        try:
            data = kalshi_get("/portfolio/balance")
            cents = data.get("balance", 0)
            dollars = cents / 100.0
            log.info("Kalshi balance: $%.2f", dollars)
            return dollars
        except Exception as exc:
            log.error("Balance fetch failed: %s", exc)
            return 0.0

    def refresh_balance(self):
        """Re-query Kalshi for the current balance (call after fills settle)."""
        self.current_bankroll = self._fetch_balance()

    # ── Day rollover ──────────────────────────────────────────────────────────

    def _maybe_rollover(self):
        today = datetime.now(timezone.utc).date()
        if today != self._trade_day:
            log.info("New trading day — resetting daily counters")
            self._trade_day       = today
            self.trades_today     = []
            self.daily_pnl        = 0.0
            # Refresh from Kalshi so loss-limit basis reflects real balance
            self.refresh_balance()
            self.starting_bankroll = self.current_bankroll
            log.info("Day rollover balance refresh: $%.2f", self.current_bankroll)

    # ── Core gate ─────────────────────────────────────────────────────────────

    def can_trade(self) -> tuple[bool, str]:
        """
        Check all risk rules. Return (True, "ok") or (False, human-readable reason).

        Checks (in order):
          1. Daily trade count < MAX_DAILY_TRADES
          2. Daily loss < DAILY_LOSS_LIMIT_PCT of starting bankroll
          3. Open positions < MAX_OPEN_POSITIONS
          4. Bankroll > 0
        """
        self._maybe_rollover()

        trades_used = len(self.trades_today)
        if trades_used >= MAX_DAILY_TRADES:
            return False, (
                f"daily trade limit reached ({trades_used}/{MAX_DAILY_TRADES})"
            )

        loss_limit = self.starting_bankroll * DAILY_LOSS_LIMIT_PCT
        if self.daily_pnl <= -loss_limit:
            return False, (
                f"daily loss limit hit — down ${abs(self.daily_pnl):.2f} "
                f"of ${loss_limit:.2f} limit"
            )

        open_count = len(self.open_positions)
        if open_count >= MAX_OPEN_POSITIONS:
            return False, (
                f"max open positions reached ({open_count}/{MAX_OPEN_POSITIONS})"
            )

        if self.current_bankroll <= 0:
            return False, "bankroll is zero or negative"

        return True, "ok"

    # ── Sizing ────────────────────────────────────────────────────────────────

    def position_size(self) -> float:
        """
        Return dollar amount to spend on the next trade.
        = 2% of current bankroll, clamped to [$1, $50].
        """
        raw = self.current_bankroll * RISK_PER_TRADE_PCT
        return max(MIN_TRADE_DOLLARS, min(MAX_TRADE_DOLLARS, raw))

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def record_open(
        self,
        ticker: str,
        direction: str,
        size_dollars: float,
        entry_price_cents: int,
    ):
        """Register a new open position. Call immediately after order fill."""
        self._maybe_rollover()
        rec = TradeRecord(
            ticker=ticker,
            direction=direction,
            size=size_dollars,
            price=entry_price_cents,
        )
        self.trades_today.append(rec)
        self.open_positions[ticker] = Position(
            ticker=ticker,
            direction=direction,
            size_dollars=size_dollars,
            entry_price=entry_price_cents,
        )
        log.info(
            "OPEN  %s %s  $%.2f @ %d¢  |  %d open, %d today",
            direction, ticker, size_dollars, entry_price_cents,
            len(self.open_positions), len(self.trades_today),
        )

    def record_close(self, ticker: str, settlement_price_cents: int):
        """
        Mark a position closed at settlement. Updates daily P&L.

        settlement_price_cents: 0 (NO wins) or 100 (YES wins) for binary markets.
        """
        pos = self.open_positions.pop(ticker, None)
        if pos is None:
            log.warning("record_close: no open position found for %s", ticker)
            return

        # Number of contracts purchased
        entry_dollars = pos.entry_price / 100.0
        contracts     = (pos.size_dollars / entry_dollars) if entry_dollars > 0 else 0
        settle_dollars = settlement_price_cents / 100.0

        if pos.direction == "YES":
            # Paid entry_dollars per contract; received settle_dollars per contract
            pnl = contracts * (settle_dollars - entry_dollars)
        else:
            # Bought NO at (1 - bid/100); NO pays out (1 - settle/100) per contract
            no_cost    = 1.0 - entry_dollars
            no_payout  = 1.0 - settle_dollars
            pnl = contracts * (no_payout - no_cost)

        self.daily_pnl        += pnl
        self.current_bankroll += pnl

        # Back-fill P&L on the trade record
        for rec in reversed(self.trades_today):
            if rec.ticker == ticker and rec.pnl is None:
                rec.pnl = pnl
                break

        log.info(
            "CLOSE %s %s  pnl $%+.2f  |  daily pnl $%+.2f  bankroll $%.2f",
            pos.direction, ticker, pnl, self.daily_pnl, self.current_bankroll,
        )

    # ── Live position sync ────────────────────────────────────────────────────

    def sync_open_positions(self):
        """
        Reconcile in-memory open_positions against Kalshi's live portfolio.

        Removes any tracked position whose ticker no longer appears in the API
        response or whose net contract count is 0 (settled / expired).
        Call at the start of every loop so stale ghost positions never block
        the risk gate.
        """
        try:
            data = kalshi_get("/portfolio/positions")
        except Exception as exc:
            log.warning("sync_open_positions: API call failed — skipping: %s", exc)
            return

        live_tickers: set[str] = set()
        for pos in data.get("market_positions", []):
            ticker = pos.get("ticker", "")
            net    = pos.get("position", 0)
            if ticker and net != 0:
                live_tickers.add(ticker)

        stale = [t for t in list(self.open_positions) if t not in live_tickers]
        for ticker in stale:
            log.info("sync_open_positions: clearing settled/expired position %s", ticker)
            self.open_positions.pop(ticker)

        if stale:
            log.info(
                "sync_open_positions: cleared %d stale position(s) — %d remain",
                len(stale), len(self.open_positions),
            )

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Snapshot of current risk state for logging / dry-run display."""
        ok, reason = self.can_trade()
        loss_limit = self.starting_bankroll * DAILY_LOSS_LIMIT_PCT
        return {
            "bankroll":           round(self.current_bankroll, 2),
            "starting_bankroll":  round(self.starting_bankroll, 2),
            "daily_pnl":          round(self.daily_pnl, 2),
            "loss_limit":         round(loss_limit, 2),
            "trades_today":       len(self.trades_today),
            "trades_remaining":   max(0, MAX_DAILY_TRADES - len(self.trades_today)),
            "open_positions":     len(self.open_positions),
            "open_tickers":       list(self.open_positions.keys()),
            "can_trade":          ok,
            "reason":             reason,
            "next_size_dollars":  round(self.position_size(), 2),
        }
