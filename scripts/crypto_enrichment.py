#!/usr/bin/env python3
"""
crypto_enrichment.py — Shared FreeCryptoAPI enrichment utility.

API base: https://api.freecryptoapi.com/v1
Auth:     Authorization: Bearer <FREECRYPTO_API_KEY>
Docs:     https://freecryptoapi.com/documentation/

Key endpoints used:
  GET /getData?symbol=BTC          — live aggregated spot price
  GET /getPerformance?symbol=BTC   — 1d/7d/30d change percentages
  GET /getData?symbol=BTC@binance+BTC@bybit+BTC  — per-exchange + aggregated

Design rules:
  - NEVER raise exceptions — always return None on failure
  - 30-second in-process cache per (endpoint, symbol) key
  - Daily quota tracker written to logs/enrichment_quota.json
  - Warn at 2,000 requests/day (projects to ~60K/month)
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

BASE_URL        = "https://api.freecryptoapi.com/v1/"
REQUEST_TIMEOUT = 2          # seconds — tight to protect callers
CACHE_TTL       = 30         # seconds before a cached entry is stale
DAILY_WARN_AT   = 2_000      # log warning if daily calls exceed this

QUOTA_LOG_PATH = Path("/root/.openclaw/logs/enrichment_quota.json")
ENRICH_LOG_PATH = Path("/root/.openclaw/logs/crypto_enrichment.log")

# Ensure log dir exists
QUOTA_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


# ── Env loader ────────────────────────────────────────────────────────────────

def _load_env_key() -> Optional[str]:
    """Read FREECRYPTO_API_KEY from /etc/environment then /root/.openclaw/.env."""
    for path in ("/etc/environment", "/root/.openclaw/.env"):
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("FREECRYPTO_API_KEY"):
                        _, _, val = line.partition("=")
                        val = val.strip().strip('"').strip("'")
                        if val and "placeholder" not in val.lower():
                            return val
        except FileNotFoundError:
            pass
        except Exception as e:
            log.debug("Env load error (%s): %s", path, e)
    return None


# ── Quota tracker ─────────────────────────────────────────────────────────────

def _read_quota() -> dict:
    try:
        with open(QUOTA_LOG_PATH) as f:
            data = json.load(f)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if data.get("date") != today:
            return {"date": today, "requests": 0}
        return data
    except Exception:
        return {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "requests": 0}


def _write_quota(data: dict) -> None:
    try:
        with open(QUOTA_LOG_PATH, "w") as f:
            json.dump(data, f)
    except Exception as e:
        log.debug("Quota write error: %s", e)


def _increment_quota() -> int:
    """Increment daily request count, warn if over threshold. Returns new count."""
    data = _read_quota()
    data["requests"] += 1
    _write_quota(data)
    count = data["requests"]
    if count == DAILY_WARN_AT:
        log.warning(
            "[crypto_enrichment] Daily request count hit %d — projecting ~%dK/month. "
            "Review polling frequency.",
            count,
            count * 30 // 1000,
        )
    return count


# ── Main class ────────────────────────────────────────────────────────────────

class CryptoDataEnricher:
    """
    Thin wrapper around FreeCryptoAPI with caching, quota tracking, and
    full exception suppression. Every public method returns None on failure.
    """

    def __init__(self) -> None:
        self.api_key: Optional[str] = _load_env_key()
        if not self.api_key:
            log.warning(
                "[crypto_enrichment] FREECRYPTO_API_KEY not set — all enrichment calls "
                "will return None. Set the key in /root/.openclaw/.env."
            )
        self._cache: dict[str, tuple[float, object]] = {}   # key → (ts, result)
        self._session_requests: int = 0

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _cache_get(self, key: str) -> Optional[object]:
        entry = self._cache.get(key)
        if entry and (time.monotonic() - entry[0]) < CACHE_TTL:
            return entry[1]
        return None

    def _cache_set(self, key: str, value: object) -> None:
        self._cache[key] = (time.monotonic(), value)

    def _get(self, endpoint: str, params: dict) -> Optional[dict]:
        """
        Make a GET request. Returns parsed JSON dict or None.
        Never raises.
        """
        if not self.api_key:
            return None
        url = f"{BASE_URL}{endpoint.lstrip('/')}"
        t0 = time.monotonic()
        try:
            r = requests.get(
                url,
                params=params,
                headers=self._headers(),
                timeout=REQUEST_TIMEOUT,
            )
            latency_ms = int((time.monotonic() - t0) * 1000)
            success = r.status_code == 200
            self._log_call(endpoint, params.get("symbol", ""), success, latency_ms)
            if not success:
                log.debug(
                    "[crypto_enrichment] %s %s → HTTP %d", endpoint, params, r.status_code
                )
                return None
            _increment_quota()
            self._session_requests += 1
            return r.json()
        except requests.exceptions.Timeout:
            latency_ms = int((time.monotonic() - t0) * 1000)
            self._log_call(endpoint, params.get("symbol", ""), False, latency_ms)
            log.debug("[crypto_enrichment] Timeout on %s after %dms", endpoint, latency_ms)
            return None
        except Exception as e:
            latency_ms = int((time.monotonic() - t0) * 1000)
            self._log_call(endpoint, params.get("symbol", ""), False, latency_ms)
            log.debug("[crypto_enrichment] Error on %s: %s", endpoint, e)
            return None

    def _log_call(
        self, endpoint: str, symbol: str, success: bool, latency_ms: int
    ) -> None:
        try:
            with open(ENRICH_LOG_PATH, "a") as f:
                ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
                status = "ok" if success else "fail"
                f.write(f"{ts} {endpoint} {symbol} {status} {latency_ms}ms\n")
        except Exception:
            pass

    @staticmethod
    def _extract_price(data: dict, symbol: str) -> Optional[float]:
        """
        Try several common response shapes to find the spot price.

        FreeCryptoAPI /getData response shape (not fully documented):
        Attempt 1: data["data"][SYMBOL]["price"]
        Attempt 2: data["data"][SYMBOL]["last"]
        Attempt 3: data[SYMBOL]["price"]
        Attempt 4: data["price"]
        Attempt 5: data["result"]["price"] or data["result"][0]["price"]
        """
        sym = symbol.upper()
        candidates = [
            # Actual FreeCryptoAPI shape: {"symbols": [{"symbol": "BTC", "last": "...", ...}]}
            lambda d: next((item["last"] for item in d.get("symbols", []) if item.get("symbol") == sym), None),
            lambda d: next((item["price"] for item in d.get("symbols", []) if item.get("symbol") == sym), None),
            lambda d: next((item["close"] for item in d.get("symbols", []) if item.get("symbol") == sym), None),
            # Other common shapes
            lambda d: d["data"][sym]["price"],
            lambda d: d["data"][sym]["last"],
            lambda d: d["data"][sym]["close"],
            lambda d: d[sym]["price"],
            lambda d: d[sym]["last"],
            lambda d: d["price"],
            lambda d: d["last"],
            lambda d: d["result"]["price"],
            lambda d: d["result"][0]["price"] if isinstance(d.get("result"), list) else None,
        ]
        for fn in candidates:
            try:
                val = fn(data)
                if val is not None:
                    return float(val)
            except (KeyError, TypeError, IndexError, ValueError):
                continue
        return None

    # ── Public API ────────────────────────────────────────────────────────────

    def get_spot_price(self, symbol: str) -> Optional[dict]:
        """
        Return {"price": float, "timestamp": str, "source": "freecryptoapi"} or None.
        Symbols: "BTC", "ETH", "SOL"
        Cached for 30 seconds.
        """
        symbol = symbol.upper()
        cache_key = f"spot:{symbol}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        data = self._get("getData", {"symbol": symbol})
        if data is None:
            return None

        price = self._extract_price(data, symbol)
        if price is None:
            log.debug("[crypto_enrichment] Could not parse price from getData response: %s", data)
            return None

        result = {
            "price":     price,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source":    "freecryptoapi",
        }
        self._cache_set(cache_key, result)
        return result

    def get_24h_change(self, symbol: str) -> Optional[dict]:
        """
        Return {"symbol": str, "change_24h_pct": float, "volume_24h": float} or None.
        Uses /getPerformance which returns 1d/7d/30d/etc. change percentages.
        Cached for 30 seconds.
        """
        symbol = symbol.upper()
        cache_key = f"perf:{symbol}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        data = self._get("getPerformance", {"symbol": symbol})
        if data is None:
            return None

        # Try to find 1d change — various field name conventions
        change_1d = None
        volume_24h = 0.0
        for field in ("1d", "change_1d", "change_24h", "performance_1d", "day1"):
            try:
                val = (data.get("data") or data).get(field)
                if val is not None:
                    change_1d = float(val)
                    break
            except Exception:
                continue

        if change_1d is None:
            log.debug("[crypto_enrichment] Could not parse 1d change from: %s", data)
            return None

        # Volume is optional — try getData as fallback
        try:
            spot_data = self._get("getData", {"symbol": symbol})
            if spot_data:
                vol_obj = (spot_data.get("data") or spot_data)
                sym_data = vol_obj.get(symbol) or vol_obj
                for vf in ("volume_24h", "volume", "vol_24h", "totalVolume"):
                    v = sym_data.get(vf) if isinstance(sym_data, dict) else None
                    if v is not None:
                        volume_24h = float(v)
                        break
        except Exception:
            pass

        result = {
            "symbol":         symbol,
            "change_24h_pct": change_1d,
            "volume_24h":     volume_24h,
        }
        self._cache_set(cache_key, result)
        return result

    def get_multi_exchange_summary(self, symbol: str) -> Optional[dict]:
        """
        Compare Binance-specific price vs FreeCryptoAPI aggregated price.
        Returns {"binance_price": float, "aggregated_price": float, "max_divergence_pct": float}
        or None if unavailable.

        Uses ?symbol=BTC@binance+BTC to get both in one request.
        If per-exchange data isn't available on free tier, returns aggregated only with
        divergence=0 (no false positives).
        Cached for 30 seconds.
        """
        symbol = symbol.upper()
        cache_key = f"multi:{symbol}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        # Single request: aggregated + binance-specific
        combined_symbol = f"{symbol}@binance+{symbol}"
        data = self._get("getData", {"symbol": combined_symbol})
        if data is None:
            return None

        agg_price = self._extract_price(data, symbol)
        if agg_price is None:
            return None

        # Try to find binance-specific price
        binance_price = None
        try:
            d = data.get("data") or data
            for key in (f"{symbol}@binance", f"{symbol}@BINANCE", "BINANCE"):
                obj = d.get(key)
                if obj and isinstance(obj, dict):
                    for pf in ("price", "last", "close"):
                        if obj.get(pf) is not None:
                            binance_price = float(obj[pf])
                            break
                if binance_price:
                    break
        except Exception:
            pass

        # If per-exchange data isn't on free tier, use aggregated for both
        # — divergence will be 0, no false positives
        if binance_price is None:
            binance_price = agg_price

        divergence = abs(binance_price - agg_price) / agg_price * 100 if agg_price else 0.0

        result = {
            "binance_price":      round(binance_price, 2),
            "aggregated_price":   round(agg_price, 2),
            "max_divergence_pct": round(divergence, 4),
        }
        self._cache_set(cache_key, result)
        return result

    def get_request_count(self) -> int:
        """Return total API calls made this process session."""
        return self._session_requests


# ── Module-level singleton ────────────────────────────────────────────────────

_enricher: Optional[CryptoDataEnricher] = None


def get_enricher() -> CryptoDataEnricher:
    """Return (or lazily create) the module-level singleton enricher."""
    global _enricher
    if _enricher is None:
        _enricher = CryptoDataEnricher()
    return _enricher


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    e = get_enricher()
    print("=== FreeCryptoAPI Enrichment Smoke Test ===")
    print(f"API key loaded: {'yes' if e.api_key else 'NO — set FREECRYPTO_API_KEY in .env'}")
    for sym in ("BTC", "ETH", "SOL"):
        spot = e.get_spot_price(sym)
        perf = e.get_24h_change(sym)
        print(f"\n{sym}:")
        print(f"  spot:  {spot}")
        print(f"  24h:   {perf}")
    multi = e.get_multi_exchange_summary("BTC")
    print(f"\nBTC multi-exchange: {multi}")
    print(f"\nTotal API calls this session: {e.get_request_count()}")
    quota = _read_quota()
    print(f"Daily quota used today: {quota['requests']}")
