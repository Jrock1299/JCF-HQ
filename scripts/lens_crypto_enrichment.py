#!/usr/bin/env python3
"""
lens_crypto_enrichment.py — Post-process Lens market_bias.json with live crypto prices.

Called by run_lens.sh immediately after the Lens agent completes.
Appends a `crypto_context` key to market_bias.json containing:
  - Live BTC / ETH / SOL spot prices and 24h change %
  - Aggregate sentiment (bullish / neutral / bearish) derived from 24h performance

Gracefully no-ops if:
  - market_bias.json doesn't exist yet
  - FreeCryptoAPI key not set or API unreachable
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/root/.openclaw/scripts")

MARKET_BIAS_PATH = Path("/root/.openclaw/dashboard/market_bias.json")
SYMBOLS = ["BTC", "ETH", "SOL"]

SENTIMENT_BULL_THRESHOLD =  1.0   # avg 24h change > +1% → bullish
SENTIMENT_BEAR_THRESHOLD = -1.0   # avg 24h change < -1% → bearish

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def crypto_snapshot() -> dict | None:
    """
    Fetch spot price and 24h change for BTC, ETH, SOL.
    Returns a dict ready to be written as `crypto_context`, or None on failure.
    """
    try:
        from crypto_enrichment import get_enricher
    except Exception as e:
        log.warning("crypto_enrichment import failed: %s", e)
        return None

    enricher = get_enricher()
    if not enricher.api_key:
        log.warning("FREECRYPTO_API_KEY not set — skipping lens enrichment")
        return None

    assets: dict = {}
    changes: list[float] = []

    for sym in SYMBOLS:
        spot = enricher.get_spot_price(sym)
        perf = enricher.get_24h_change(sym)

        asset_data: dict = {}
        if spot is not None:
            asset_data["price"]  = spot["price"]
            asset_data["source"] = spot["source"]
        if perf is not None:
            asset_data["change_24h_pct"] = perf["change_24h_pct"]
            if perf["volume_24h"]:
                asset_data["volume_24h"] = perf["volume_24h"]
            changes.append(perf["change_24h_pct"])

        if asset_data:
            assets[sym] = asset_data

    if not assets:
        return None

    # Derive sentiment from average 24h change across available symbols
    if changes:
        avg_change = sum(changes) / len(changes)
        if avg_change > SENTIMENT_BULL_THRESHOLD:
            sentiment = "bullish"
        elif avg_change < SENTIMENT_BEAR_THRESHOLD:
            sentiment = "bearish"
        else:
            sentiment = "neutral"
    else:
        sentiment = "neutral"

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sentiment": sentiment,
        "assets":    assets,
    }


def main() -> None:
    if not MARKET_BIAS_PATH.exists():
        log.warning("market_bias.json not found at %s — skipping", MARKET_BIAS_PATH)
        sys.exit(0)

    try:
        with open(MARKET_BIAS_PATH) as f:
            bias = json.load(f)
    except Exception as e:
        log.error("Could not read market_bias.json: %s", e)
        sys.exit(1)

    context = crypto_snapshot()
    if context is None:
        print("[lens_crypto_enrichment] Enrichment unavailable — market_bias.json unchanged")
        sys.exit(0)

    bias["crypto_context"] = context

    try:
        with open(MARKET_BIAS_PATH, "w") as f:
            json.dump(bias, f, indent=2)
    except Exception as e:
        log.error("Could not write market_bias.json: %s", e)
        sys.exit(1)

    sym_summary = ", ".join(
        f"{s}=${d.get('price', '?'):.0f} ({d.get('change_24h_pct', 0):+.1f}%)"
        for s, d in context["assets"].items()
        if isinstance(d.get("price"), (int, float))
    )
    print(f"[lens_crypto_enrichment] {context['sentiment'].upper()} | {sym_summary}")


if __name__ == "__main__":
    main()
