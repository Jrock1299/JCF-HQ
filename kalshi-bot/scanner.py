"""
scanner.py — Find active Kalshi crypto markets closing in the target window.

Strategy:
  1. Discover crypto series tickers via GET /series (category field lives here,
     not on /markets as of Jan 2026).
  2. Query GET /markets for each series with status=open and a close-time window.
  3. Enrich each market with recent trade history for momentum analysis.
"""

import time
import logging
from datetime import datetime, timezone
from typing import Optional

from config import (
    kalshi_get,
    SCAN_CLOSE_MIN_MINUTES,
    SCAN_CLOSE_MAX_MINUTES,
    MOMENTUM_WINDOW_MINUTES,
)

log = logging.getLogger(__name__)


# ── Series discovery ─────────────────────────────────────────────────────────

def get_crypto_series_tickers() -> list[str]:
    """Return all series tickers whose category contains 'crypto'."""
    tickers = []
    cursor = None

    while True:
        params = {"limit": 200}
        if cursor:
            params["cursor"] = cursor

        data = kalshi_get("/series", params)
        series_list = data.get("series", [])

        for s in series_list:
            category = (s.get("category") or "").lower()
            if "crypto" in category:
                tickers.append(s["ticker"])

        cursor = data.get("cursor")
        if not cursor or not series_list:
            break

    log.info("Found %d crypto series: %s", len(tickers), tickers)
    return tickers


# ── Market scanning ──────────────────────────────────────────────────────────

def _close_window_ts() -> tuple[int, int]:
    """Return (min_close_ts, max_close_ts) for the target close window."""
    now = int(time.time())
    return (
        now + SCAN_CLOSE_MIN_MINUTES * 60,
        now + SCAN_CLOSE_MAX_MINUTES * 60,
    )


def scan_markets(series_tickers: Optional[list[str]] = None) -> list[dict]:
    """
    Return open crypto markets closing within [MIN, MAX] minutes.

    Each returned dict is the raw Kalshi market object plus an added
    `minutes_to_close` key for convenience.
    """
    if series_tickers is None:
        series_tickers = get_crypto_series_tickers()

    if not series_tickers:
        log.warning("No crypto series found — check Kalshi category metadata.")
        return []

    min_ts, max_ts = _close_window_ts()
    now = int(time.time())
    eligible = []

    for series_ticker in series_tickers:
        cursor = None
        while True:
            params = {
                "series_ticker": series_ticker,
                "status":        "open",
                "min_close_ts":  min_ts,
                "max_close_ts":  max_ts,
                "limit":         200,
            }
            if cursor:
                params["cursor"] = cursor

            try:
                data = kalshi_get("/markets", params)
            except Exception as exc:
                log.error("Error fetching markets for series %s: %s", series_ticker, exc)
                break

            markets = data.get("markets", [])
            for m in markets:
                close_time = _parse_iso(m.get("close_time"))
                if close_time:
                    mins = (close_time - now) / 60
                    m["minutes_to_close"] = round(mins, 2)
                    eligible.append(m)

            cursor = data.get("cursor")
            if not cursor or not markets:
                break

    log.info("Found %d eligible markets (closing in %d–%d min)",
             len(eligible), SCAN_CLOSE_MIN_MINUTES, SCAN_CLOSE_MAX_MINUTES)
    return eligible


# ── Trade history enrichment ─────────────────────────────────────────────────

def get_recent_trades(ticker: str, window_minutes: int = MOMENTUM_WINDOW_MINUTES) -> list[dict]:
    """
    Return trades for `ticker` from the last `window_minutes` minutes,
    sorted oldest-first.
    """
    min_ts = int(time.time()) - window_minutes * 60

    try:
        data = kalshi_get("/markets/trades", {
            "ticker":  ticker,
            "min_ts":  min_ts,
            "limit":   1000,
        })
    except Exception as exc:
        log.error("Error fetching trades for %s: %s", ticker, exc)
        return []

    trades = data.get("trades", [])
    # Sort oldest → newest
    trades.sort(key=lambda t: t.get("created_time", ""))
    return trades


def enrich_with_trades(markets: list[dict]) -> list[dict]:
    """Add `recent_trades` key to each market dict in-place, return the list."""
    for m in markets:
        ticker = m["ticker"]
        m["recent_trades"] = get_recent_trades(ticker)
        log.debug("%s: %d trades in last %dm",
                  ticker, len(m["recent_trades"]), MOMENTUM_WINDOW_MINUTES)
    return markets


# ── All-category market scan ─────────────────────────────────────────────────

def scan_all_markets(hours_min: float = 1.0, hours_max: float = 48.0) -> list[dict]:
    """
    Return ALL open Kalshi markets closing within [hours_min, hours_max] hours,
    regardless of category.

    Each returned dict is the raw Kalshi market object plus an added
    `minutes_to_close` key.  Used to feed the Claude brain with a broad view
    of the market universe.
    """
    now     = int(time.time())
    min_ts  = now + int(hours_min  * 3600)
    max_ts  = now + int(hours_max  * 3600)
    markets = []
    cursor  = None

    while True:
        params: dict = {
            "status":        "open",
            "min_close_ts":  min_ts,
            "max_close_ts":  max_ts,
            "limit":         200,
        }
        if cursor:
            params["cursor"] = cursor

        try:
            data = kalshi_get("/markets", params)
        except Exception as exc:
            log.error("scan_all_markets: API error: %s", exc)
            break

        page = data.get("markets", [])
        for m in page:
            close_ts = _parse_iso(m.get("close_time"))
            if close_ts:
                mins = (close_ts - now) / 60
                m["minutes_to_close"] = round(mins, 2)
                markets.append(m)

        cursor = data.get("cursor")
        if not cursor or not page:
            break

    log.info(
        "scan_all_markets: %d markets closing in %.0f–%.0fh",
        len(markets), hours_min, hours_max,
    )
    return markets


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_iso(ts_str: Optional[str]) -> Optional[int]:
    """Parse an ISO 8601 timestamp string to a Unix int, or None."""
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return int(dt.replace(tzinfo=timezone.utc).timestamp()
                   if dt.tzinfo is None else dt.timestamp())
    except ValueError:
        return None


# ── Quick test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
    )

    print("=== Kalshi Crypto Market Scanner ===\n")

    # Step 1: discover crypto series
    series = get_crypto_series_tickers()
    if not series:
        print("No crypto series found. The market may have no active crypto categories right now.")
        print("Attempting a broad open-market scan as a fallback...\n")
        # Fallback: scan all open markets in the close window (no series filter)
        min_ts, max_ts = _close_window_ts()
        now = int(time.time())
        data = kalshi_get("/markets", {
            "status":       "open",
            "min_close_ts": min_ts,
            "max_close_ts": max_ts,
            "limit":        200,
        })
        markets = data.get("markets", [])
        for m in markets:
            close_time = _parse_iso(m.get("close_time"))
            if close_time:
                m["minutes_to_close"] = round((close_time - now) / 60, 2)
        print(f"Fallback found {len(markets)} open markets closing in "
              f"{SCAN_CLOSE_MIN_MINUTES}–{SCAN_CLOSE_MAX_MINUTES} minutes.\n")
        for m in markets[:10]:
            print(f"  {m['ticker']:50s}  "
                  f"yes_bid={m.get('yes_bid_dollars','?'):6s}  "
                  f"yes_ask={m.get('yes_ask_dollars','?'):6s}  "
                  f"closes_in={m.get('minutes_to_close','?')}m")
        raise SystemExit(0)

    # Step 2: scan eligible markets
    markets = scan_markets(series)

    if not markets:
        print(f"No crypto markets closing in {SCAN_CLOSE_MIN_MINUTES}–"
              f"{SCAN_CLOSE_MAX_MINUTES} minutes right now.")
        print("Try widening SCAN_CLOSE_MIN_MINUTES / SCAN_CLOSE_MAX_MINUTES in config.py "
              "or run again closer to a contract expiry.\n")

        # Still show what crypto markets ARE open
        print("Currently open crypto markets (any close time):")
        for s in series:
            data = kalshi_get("/markets", {"series_ticker": s, "status": "open", "limit": 10})
            for m in data.get("markets", []):
                print(f"  {m['ticker']:50s}  "
                      f"close={m.get('close_time','?')}")
        raise SystemExit(0)

    # Step 3: enrich with recent trades
    print(f"Found {len(markets)} eligible markets. Fetching recent trade history...\n")
    enrich_with_trades(markets)

    # Step 4: display summary
    print(f"{'TICKER':<50} {'CLOSES IN':>10} {'YES BID':>8} {'YES ASK':>8} "
          f"{'TRADES(5m)':>10} {'VOLUME 24h':>12}")
    print("-" * 105)
    for m in sorted(markets, key=lambda x: x["minutes_to_close"]):
        print(
            f"{m['ticker']:<50} "
            f"{m['minutes_to_close']:>9.1f}m "
            f"{m.get('yes_bid_dollars','?'):>8} "
            f"{m.get('yes_ask_dollars','?'):>8} "
            f"{len(m['recent_trades']):>10} "
            f"{m.get('volume_24h_fp','?'):>12}"
        )
