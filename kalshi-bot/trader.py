"""
trader.py — Order execution layer for the Kalshi bot.

Three public functions:
  place_trade(ticker, direction, size_dollars, entry_price_cents, dry_run)
    → OrderResult

  check_open_positions()
    → list[PositionInfo]

  close_position(ticker, current_position, dry_run)
    → OrderResult | None
"""

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Optional

import requests
from config import kalshi_get, kalshi_post
from strategy import fetch_orderbook  # normalised orderbook parser

ORDER_FILL_TIMEOUT = 120   # seconds before an unfilled limit order is cancelled
ORDER_POLL_INTERVAL = 10   # seconds between fill-status checks

log = logging.getLogger(__name__)


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class OrderResult:
    success:       bool
    order_id:      str
    ticker:        str
    direction:     str          # "YES" or "NO"
    contracts:     int
    entry_price:   int          # cents — the limit price we requested
    filled_price:  Optional[int] = None   # cents — set if immediately filled
    status:        str = "resting"        # resting | filled | dry_run
    error:         Optional[str] = None


@dataclass
class PositionInfo:
    ticker:          str
    direction:       str    # "YES" or "NO"
    contracts:       int
    avg_price:       int    # cents
    current_value:   float  # dollars — contracts × current_yes_price / 100


# ── Order placement ───────────────────────────────────────────────────────────

def place_trade(
    ticker: str,
    direction: str,
    size_dollars: float,
    entry_price_cents: int,
    dry_run: bool = True,
) -> OrderResult:
    """
    Place a limit order on Kalshi.

    Args:
        ticker:            e.g. "KXBTC15M-24-B50000"
        direction:         "YES" or "NO"
        size_dollars:      dollar amount to spend (e.g. 2.00)
        entry_price_cents: limit price in cents (1–99)
        dry_run:           if True, skip the API call and return a fake confirmation

    Returns:
        OrderResult with order_id, contracts, status.

    Contracts purchased = floor(size_dollars / (entry_price_cents / 100)).
    Minimum 1 contract. If the math yields 0 (price > size), returns an error.

    Kalshi POST /portfolio/orders body:
      {
        "ticker":    str,
        "side":      "yes" | "no",
        "action":    "buy",
        "type":      "limit",
        "count":     int,          # number of contracts
        "yes_price": int,          # cents, required for limit orders
        "no_price":  int,          # cents, required for limit orders
      }
    yes_price + no_price must equal 100.
    """
    if entry_price_cents <= 0 or entry_price_cents >= 100:
        return OrderResult(
            success=False,
            order_id="",
            ticker=ticker,
            direction=direction,
            contracts=0,
            entry_price=entry_price_cents,
            error=f"invalid entry price {entry_price_cents}¢ (must be 1–99)",
        )

    entry_dollars = entry_price_cents / 100.0
    contracts     = math.floor(size_dollars / entry_dollars)

    if contracts < 1:
        return OrderResult(
            success=False,
            order_id="",
            ticker=ticker,
            direction=direction,
            contracts=0,
            entry_price=entry_price_cents,
            error=(
                f"size ${size_dollars:.2f} too small for price {entry_price_cents}¢ "
                f"(need at least ${entry_dollars:.2f})"
            ),
        )

    yes_price = entry_price_cents if direction == "YES" else (100 - entry_price_cents)
    no_price  = 100 - yes_price

    if dry_run:

        fake_id = f"DRY-{ticker[-8:]}-{direction[0]}{entry_price_cents}"
        log.info(
            "[DRY RUN] Would place: %s %s  %d contracts @ %d¢  ($%.2f)",
            direction, ticker, contracts, entry_price_cents, size_dollars,
        )
        return OrderResult(
            success=True,
            order_id=fake_id,
            ticker=ticker,
            direction=direction,
            contracts=contracts,
            entry_price=entry_price_cents,
            status="dry_run",
        )

    # ── Live order ────────────────────────────────────────────────────────────
    # Kalshi requires exactly ONE of yes_price or no_price (in cents, 1–99).
    price_field = "yes_price" if direction == "YES" else "no_price"
    price_value = yes_price   if direction == "YES" else no_price

    body = {
        "ticker":      ticker,
        "side":        direction.lower(),
        "action":      "buy",
        "type":        "limit",
        "count":       contracts,
        price_field:   price_value,
    }

    try:
        resp = kalshi_post("/portfolio/orders", body)
        order = resp.get("order", resp)   # API wraps in {"order": {...}}
        order_id    = order.get("order_id", order.get("id", "unknown"))
        status_raw  = order.get("status", "resting")
        filled_price = None

        # If the order was immediately filled, extract fill price
        if status_raw in ("filled", "partially_filled"):
            fills = order.get("fills", [])
            if fills:
                fill_prices = [f.get("yes_price", yes_price) for f in fills]
                filled_price = round(sum(fill_prices) / len(fill_prices))

        log.info(
            "ORDER PLACED: %s %s %d contracts @ %d¢  id=%s  status=%s",
            direction, ticker, contracts, entry_price_cents, order_id, status_raw,
        )
        return OrderResult(
            success=True,
            order_id=order_id,
            ticker=ticker,
            direction=direction,
            contracts=contracts,
            entry_price=entry_price_cents,
            filled_price=filled_price,
            status=status_raw,
        )

    except requests.HTTPError as exc:
        body = exc.response.text if exc.response is not None else ""
        log.error("Order HTTP error for %s: %s — %s", ticker, exc, body)
        return OrderResult(
            success=False, order_id="", ticker=ticker, direction=direction,
            contracts=contracts, entry_price=entry_price_cents,
            error=f"{exc} | {body}",
        )
    except Exception as exc:
        log.error("Order failed for %s: %s", ticker, exc)
        return OrderResult(
            success=False, order_id="", ticker=ticker, direction=direction,
            contracts=contracts, entry_price=entry_price_cents, error=str(exc),
        )


# ── Position inspection ───────────────────────────────────────────────────────

def check_open_positions() -> list[PositionInfo]:
    """
    Return all open positions from GET /portfolio/positions.

    Kalshi position fields (v2):
      ticker, side, position (contracts held), average_price (cents),
      market_exposure (current value in cents).
    """
    try:
        data = kalshi_get("/portfolio/positions", {"settlement_status": "unsettled"})
    except Exception as exc:
        log.error("Failed to fetch positions: %s", exc)
        return []

    positions: list[PositionInfo] = []
    for p in data.get("market_positions", []):
        # Kalshi returns positive count for YES, negative for NO
        raw_position = p.get("position", 0)
        if raw_position == 0:
            continue

        direction = "YES" if raw_position > 0 else "NO"
        contracts = abs(raw_position)

        # average_price is in cents for YES contracts
        avg_price = p.get("average_price", 0)

        # market_exposure is in cents (current mark value)
        exposure_cents = p.get("market_exposure", 0)
        current_value  = abs(exposure_cents) / 100.0

        positions.append(PositionInfo(
            ticker=p["ticker"],
            direction=direction,
            contracts=contracts,
            avg_price=avg_price,
            current_value=current_value,
        ))

    log.debug("Fetched %d open position(s)", len(positions))
    return positions


# ── Position exit ─────────────────────────────────────────────────────────────

def close_position(
    ticker: str,
    current_position: PositionInfo,
    dry_run: bool = True,
) -> Optional[OrderResult]:
    """
    Exit an open position by placing the opposing order at market price.

    Strategy: sell YES at the current best bid (or buy NO at best ask).
    We use a limit order at a slightly aggressive price to ensure fill.

    For YES positions: place a sell-YES limit slightly below current ask.
    For NO  positions: place a sell-NO  limit slightly below current ask.

    In practice we fetch the orderbook to find the best opposing price.
    """
    ob = fetch_orderbook(ticker)
    if ob is None:
        log.error("Could not fetch orderbook for close of %s", ticker)
        return None

    yes_levels = ob.get("yes") or []
    no_levels  = ob.get("no")  or []

    if current_position.direction == "YES":
        # We hold YES — want to sell YES. Sell YES = buy NO from Kalshi's perspective.
        # Use best NO bid as our exit price for the NO side.
        # Equivalently: close at (100 - best_no_bid) on the YES side.
        if not no_levels:
            log.warning("No NO bids to close YES position for %s", ticker)
            return None
        best_no_bid   = no_levels[0][0]
        exit_yes_price = 100 - best_no_bid   # what we'll receive per YES contract sold
        close_direction = "NO"
        close_price_cents = best_no_bid  # price for the NO contract we're buying to close
    else:
        # We hold NO — want to sell NO. Sell NO = buy YES from Kalshi's perspective.
        if not yes_levels:
            log.warning("No YES bids to close NO position for %s", ticker)
            return None
        best_yes_bid     = yes_levels[0][0]
        close_direction  = "YES"
        close_price_cents = best_yes_bid

    # Size = contracts × price per contract
    size_dollars = current_position.contracts * (close_price_cents / 100.0)

    log.info(
        "Closing %s %s: %d contracts via %s @ %d¢",
        current_position.direction, ticker,
        current_position.contracts, close_direction, close_price_cents,
    )

    return place_trade(
        ticker=ticker,
        direction=close_direction,
        size_dollars=size_dollars,
        entry_price_cents=close_price_cents,
        dry_run=dry_run,
    )


# ── Order lifecycle management ────────────────────────────────────────────────

def get_order_status(order_id: str) -> str:
    """
    Return the current status string for an order, or "unknown" on error.

    Kalshi GET /portfolio/orders/{order_id} → {"order": {"status": "resting"|"filled"|...}}
    Possible statuses: resting, filled, partially_filled, cancelled, expired
    """
    try:
        data = kalshi_get(f"/portfolio/orders/{order_id}")
        order = data.get("order", data)
        return order.get("status", "unknown")
    except Exception as exc:
        log.warning("Could not fetch status for order %s: %s", order_id, exc)
        return "unknown"


def cancel_order(order_id: str) -> bool:
    """
    Cancel a resting order via DELETE /portfolio/orders/{order_id}.
    Returns True if the cancellation request succeeded, False otherwise.
    """
    import requests
    from config import BASE_URL, _auth_headers
    try:
        path = f"/portfolio/orders/{order_id}"
        url  = f"{BASE_URL}{path}"
        resp = requests.delete(
            url,
            headers=_auth_headers("DELETE", f"/trade-api/v2{path}"),
        )
        resp.raise_for_status()
        log.info("Cancelled order %s", order_id)
        return True
    except Exception as exc:
        log.error("Failed to cancel order %s: %s", order_id, exc)
        return False
