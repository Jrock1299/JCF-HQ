"""
strategy.py — Score 15-minute Kalshi crypto markets for trade worthiness.

Scoring model (0–100):
  Momentum  (0–40): how far the YES mid-price is from 50¢ fair value
  Time      (0–30): prefer 8–14 min remaining; penalise too early / too late
  Liquidity (0–30): orderbook depth across top 3 bid/ask levels

Only markets scoring ≥ 65 are flagged as tradeable.
Direction rule: price > 50 → buy YES (momentum toward YES resolution)
                price < 50 → buy NO  (momentum toward NO  resolution)
"""

import csv
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import kalshi_get

# ── FreeCryptoAPI enrichment (optional — degrades gracefully if unavailable) ───

try:
    sys.path.insert(0, "/root/.openclaw/scripts")
    from crypto_enrichment import get_enricher as _get_enricher
    _ENRICHER_AVAILABLE = True
except Exception:
    _ENRICHER_AVAILABLE = False

ENRICHMENT_LOG = Path("/root/kalshi-bot/enrichment_log.csv")
_ENRICHMENT_LOG_HEADER = ["timestamp", "ticker", "base_score", "spot_price",
                           "spot_velocity", "spot_modifier", "final_score",
                           "trade_taken", "outcome"]

# Rolling spot-price window: ticker → [price1, price2, ...] (max 5)
_spot_windows: dict[str, list[float]] = {}

log = logging.getLogger(__name__)

# 15-minute crypto series we trade
SERIES_15M = ["KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXHYPE15M"]

SCORE_THRESHOLD = 65   # minimum score to emit a signal
FAIR_VALUE      = 50   # cents — probability-neutral price

# Time window for scoring (minutes remaining)
TIME_IDEAL_LO  = 8
TIME_IDEAL_HI  = 14
TIME_OUTER_LO  = 4     # below this → no time score
TIME_OUTER_HI  = 18    # above this → no time score


# ── Signal dataclass ──────────────────────────────────────────────────────────

@dataclass
class TradeSignal:
    ticker:        str
    direction:     str          # "YES" or "NO"
    score:         int          # 0–100
    entry_price:   int          # cents (what we'd pay)
    mid_price:     float        # cents
    minutes_left:  float
    reasoning:     str


# ── Orderbook helpers ─────────────────────────────────────────────────────────

def fetch_orderbook(ticker: str) -> Optional[dict]:
    """Fetch and normalise the orderbook for a market.

    Kalshi returns `orderbook_fp` with dollar-string prices sorted ascending:
      {"orderbook_fp": {"yes_dollars": [["0.45", "200.00"], ...],
                        "no_dollars":  [["0.51", "300.00"], ...]}}

    We normalise to cent integers sorted descending (best bid first):
      {"yes": [[45, 200], [44, 150], ...],
       "no":  [[51, 300], [50, 120], ...]}

    Best YES bid = yes[0][0]  (highest price a buyer will pay)
    Best YES ask = 100 - no[0][0]  (complementary: best no bid inverted)
    """
    try:
        data = kalshi_get(f"/markets/{ticker}/orderbook")
    except Exception as exc:
        log.warning("Orderbook fetch failed for %s: %s", ticker, exc)
        return None

    raw = data.get("orderbook_fp") or data.get("orderbook")
    if raw is None:
        log.warning("No orderbook key in response for %s: %s", ticker, list(data))
        return None

    def _parse_side(key_dollars: str, key_cents: str) -> list:
        levels = raw.get(key_dollars) or raw.get(key_cents) or []
        parsed = []
        for price_raw, qty_raw in levels:
            try:
                price_cents = round(float(price_raw) * 100)
                qty = float(qty_raw)
                if 1 <= price_cents <= 99:
                    parsed.append([price_cents, qty])
            except (ValueError, TypeError):
                continue
        # Sort descending so index 0 = best bid
        parsed.sort(key=lambda x: x[0], reverse=True)
        return parsed

    return {
        "yes": _parse_side("yes_dollars", "yes"),
        "no":  _parse_side("no_dollars",  "no"),
    }


def _best_bid_ask(orderbook: dict) -> tuple[Optional[int], Optional[int]]:
    """Return (best_yes_bid_cents, best_yes_ask_cents)."""
    yes_levels = orderbook.get("yes") or []
    no_levels  = orderbook.get("no")  or []

    best_yes_bid = yes_levels[0][0] if yes_levels else None
    best_no_bid  = no_levels[0][0]  if no_levels  else None
    best_yes_ask = (100 - best_no_bid) if best_no_bid is not None else None

    return best_yes_bid, best_yes_ask


def _orderbook_depth(orderbook: dict, levels: int = 3) -> int:
    """Sum total quantity across top N levels of both YES and NO sides."""
    total = 0
    for side in ("yes", "no"):
        for _, qty in (orderbook.get(side) or [])[:levels]:
            total += qty
    return int(total)


# ── Scoring components ────────────────────────────────────────────────────────

def _score_momentum(mid_price: float) -> tuple[int, str]:
    """0–40 pts based on distance from fair value."""
    dist = abs(mid_price - FAIR_VALUE)
    if dist >= 30:
        return 40, f"mid {mid_price:.1f}¢, {dist:.0f}¢ from fair (very strong)"
    if dist >= 20:
        return 30, f"mid {mid_price:.1f}¢, {dist:.0f}¢ from fair (strong)"
    if dist >= 15:
        return 20, f"mid {mid_price:.1f}¢, {dist:.0f}¢ from fair (moderate)"
    if dist >= 10:
        return 10, f"mid {mid_price:.1f}¢, {dist:.0f}¢ from fair (weak)"
    return 0, f"mid {mid_price:.1f}¢, {dist:.0f}¢ from fair (no signal)"


def _score_time(minutes_left: float) -> tuple[int, str]:
    """0–30 pts based on time remaining. Sweet spot: 8–14 min."""
    if TIME_IDEAL_LO <= minutes_left <= TIME_IDEAL_HI:
        return 30, f"{minutes_left:.1f}m remaining (ideal)"
    if 6 <= minutes_left < TIME_IDEAL_LO:
        return 20, f"{minutes_left:.1f}m remaining (slightly late)"
    if TIME_IDEAL_HI < minutes_left <= TIME_OUTER_HI:
        return 15, f"{minutes_left:.1f}m remaining (slightly early)"
    if TIME_OUTER_LO <= minutes_left < 6:
        return 10, f"{minutes_left:.1f}m remaining (very late)"
    return 0, f"{minutes_left:.1f}m remaining (outside window)"


def _score_liquidity(depth: int) -> tuple[int, str]:
    """0–30 pts based on combined orderbook depth."""
    if depth >= 500:
        return 30, f"depth {depth} (liquid)"
    if depth >= 200:
        return 20, f"depth {depth} (adequate)"
    if depth >= 50:
        return 10, f"depth {depth} (thin)"
    return 0, f"depth {depth} (too thin — skip)"


# ── Spot momentum enrichment ──────────────────────────────────────────────────

_TICKER_TO_SYMBOL = {
    "KXBTC15M": "BTC",
    "KXETH15M": "ETH",
}


def _log_enrichment(ticker: str, base_score: int, spot_price: Optional[float],
                    spot_velocity: Optional[float], spot_modifier: int,
                    final_score: int, trade_taken: bool) -> None:
    """Append one row to enrichment_log.csv (header written on first call)."""
    try:
        write_header = not ENRICHMENT_LOG.exists() or ENRICHMENT_LOG.stat().st_size == 0
        with open(ENRICHMENT_LOG, "a", newline="") as f:
            w = csv.writer(f)
            if write_header:
                w.writerow(_ENRICHMENT_LOG_HEADER)
            w.writerow([
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                ticker,
                base_score,
                round(spot_price, 2) if spot_price is not None else "",
                round(spot_velocity, 4) if spot_velocity is not None else "",
                spot_modifier,
                final_score,
                trade_taken,
                "",   # outcome — filled in later if tracked
            ])
    except Exception as e:
        log.debug("enrichment_log write error: %s", e)


def spot_momentum_check(ticker: str, direction: str, base_score: int) -> int:
    """
    Fetch the current spot price for BTC/ETH, maintain a rolling 5-price window,
    and return a score modifier:
        +10  — spot velocity confirms the Kalshi direction (confirmation)
        -15  — spot velocity contradicts the Kalshi direction (divergence)
          0  — insufficient data, non-crypto ticker, or enricher unavailable

    Only fires for KXBTC15M and KXETH15M.
    Logs every call to enrichment_log.csv.
    """
    symbol = _TICKER_TO_SYMBOL.get(ticker)
    if symbol is None or not _ENRICHER_AVAILABLE:
        return 0

    spot_price: Optional[float] = None
    spot_velocity: Optional[float] = None
    modifier = 0

    try:
        enricher = _get_enricher()
        result = enricher.get_spot_price(symbol)
        if result is None:
            _log_enrichment(ticker, base_score, None, None, 0,
                            base_score, base_score >= SCORE_THRESHOLD)
            return 0

        spot_price = result["price"]

        window = _spot_windows.setdefault(ticker, [])
        window.append(spot_price)
        if len(window) > 5:
            window.pop(0)

        if len(window) < 2:
            # Not enough data yet — neutral, no modifier
            _log_enrichment(ticker, base_score, spot_price, None, 0,
                            base_score, base_score >= SCORE_THRESHOLD)
            return 0

        oldest = window[0]
        spot_velocity = (spot_price - oldest) / oldest * 100   # % change over window

        # Confirmation: spot moving same way as our Kalshi direction
        if spot_velocity > 0 and direction == "YES":
            modifier = +10
        elif spot_velocity < 0 and direction == "NO":
            modifier = +10
        # Divergence: spot moving opposite to our Kalshi direction
        elif spot_velocity > 0 and direction == "NO":
            modifier = -15
        elif spot_velocity < 0 and direction == "YES":
            modifier = -15
        # velocity == 0 → modifier stays 0

    except Exception as e:
        log.debug("spot_momentum_check error for %s: %s", ticker, e)

    final_score = base_score + modifier
    trade_taken = final_score >= SCORE_THRESHOLD
    _log_enrichment(ticker, base_score, spot_price, spot_velocity,
                    modifier, final_score, trade_taken)

    log.debug("[enrichment] %s spot=%.2f vel=%.4f%% dir=%s modifier=%+d → %d",
              ticker, spot_price or 0, spot_velocity or 0, direction, modifier, final_score)
    return modifier


# ── Per-market scorer ─────────────────────────────────────────────────────────

def score_market(
    ticker: str, minutes_left: float, orderbook: dict
) -> Optional[TradeSignal]:
    """
    Score one market. Return a TradeSignal if score ≥ SCORE_THRESHOLD, else None.
    """
    bid, ask = _best_bid_ask(orderbook)

    if bid is None or ask is None:
        log.debug("%s: incomplete orderbook, skipping", ticker)
        return None

    if ask <= bid:
        log.debug("%s: crossed/locked book (bid=%s ask=%s), skipping", ticker, bid, ask)
        return None

    mid_price = (bid + ask) / 2.0
    depth     = _orderbook_depth(orderbook)

    m_pts, m_desc = _score_momentum(mid_price)
    t_pts, t_desc = _score_time(minutes_left)
    l_pts, l_desc = _score_liquidity(depth)
    total = m_pts + t_pts + l_pts

    log.debug("%s mid=%.1f mom=%d time=%d liq=%d → %d",
              ticker, mid_price, m_pts, t_pts, l_pts, total)

    if total < SCORE_THRESHOLD:
        return None

    direction   = "YES" if mid_price > FAIR_VALUE else "NO"

    # ── Spot momentum enrichment (BTC/ETH only) ───────────────────────────────
    spot_modifier = spot_momentum_check(ticker, direction, total)
    final_score   = total + spot_modifier
    if final_score < SCORE_THRESHOLD:
        log.info("%s: spot divergence dropped score %d → %d (below threshold, skipping)",
                 ticker, total, final_score)
        return None

    # We pay the ask side for whichever contract we're buying
    entry_price = ask if direction == "YES" else (100 - bid)

    spot_note = ""
    if spot_modifier != 0:
        spot_note = (f" [Spot] momentum {'confirms' if spot_modifier > 0 else 'diverges'} "
                     f"({spot_modifier:+d}pts).")

    reasoning = (
        f"[Momentum] {m_desc}. "
        f"[Time] {t_desc}. "
        f"[Liquidity] {l_desc}."
        f"{spot_note} "
        f"Total score: {final_score}/100."
    )

    return TradeSignal(
        ticker=ticker,
        direction=direction,
        score=final_score,
        entry_price=entry_price,
        mid_price=mid_price,
        minutes_left=minutes_left,
        reasoning=reasoning,
    )


# ── 15M market discovery ──────────────────────────────────────────────────────

def get_active_15m_markets() -> list[dict]:
    """
    Return open markets for all SERIES_15M tickers closing in 2–18 min.
    Each dict gets a `minutes_to_close` float added.
    """
    now    = int(time.time())
    min_ts = now + TIME_OUTER_LO * 60
    max_ts = now + TIME_OUTER_HI * 60
    markets: list[dict] = []

    for series in SERIES_15M:
        try:
            data = kalshi_get("/markets", {
                "series_ticker": series,
                "status":        "open",
                "min_close_ts":  min_ts,
                "max_close_ts":  max_ts,
                "limit":         20,
            })
        except Exception as exc:
            log.error("Error fetching markets for %s: %s", series, exc)
            continue

        for m in data.get("markets", []):
            close_str = m.get("close_time", "")
            try:
                dt = datetime.fromisoformat(close_str.replace("Z", "+00:00"))
                close_ts = int(dt.timestamp())
                m["minutes_to_close"] = round((close_ts - now) / 60, 2)
            except (ValueError, AttributeError):
                m["minutes_to_close"] = 0.0
            markets.append(m)

    log.info("Found %d active 15M markets across %d series",
             len(markets), len(SERIES_15M))
    return markets


# ── Main entry point ──────────────────────────────────────────────────────────
#
# NOTE: Momentum scoring superseded by kalshi_brain.py (Claude API + web search).
#       analyze_15m_markets() now returns [] so main.py falls through to the
#       brain-based execution path.  The score_market() helpers below are kept
#       intact and can be re-enabled by restoring the body of this function.
#

def analyze_15m_markets() -> list[TradeSignal]:
    """
    Momentum-based 15M pipeline — DISABLED.
    Superseded by kalshi_brain.py.  Returns empty list.
    """
    # ── ORIGINAL BODY (commented out 2026-04-15 — replaced by Claude brain) ──
    # markets = get_active_15m_markets()
    # if not markets:
    #     log.info("No 15M markets in scoring window")
    #     return []
    #
    # signals: list[TradeSignal] = []
    # for m in markets:
    #     ticker = m["ticker"]
    #     mins   = m.get("minutes_to_close", 0.0)
    #     ob = fetch_orderbook(ticker)
    #     if ob is None:
    #         continue
    #     signal = score_market(ticker, mins, ob)
    #     if signal:
    #         signals.append(signal)
    #         log.info("SIGNAL  %s  %s  score=%d  entry=%d¢  %.1fm left",
    #                  ticker, signal.direction, signal.score,
    #                  signal.entry_price, signal.minutes_left)
    #
    # signals.sort(key=lambda s: s.score, reverse=True)
    # log.info("%d signal(s) above threshold=%d", len(signals), SCORE_THRESHOLD)
    # return signals
    return []
