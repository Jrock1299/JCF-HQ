#!/usr/bin/env python3
"""
sentinel_sync.py — JCF HQ Sentinel Data Pipeline
Pulls insider trading + market intelligence from FREE API tiers.
Includes discovery scan for small/mid-cap institutional moves.

Sources: Finnhub Free + FMP Free
Output:  /root/.openclaw/dashboard/sentinel_data.json
"""

import os, sys, json, time, requests
from datetime import datetime, timedelta

# ─── Config ───────────────────────────────────────────────────────────────────

DASHBOARD_DIR = "/root/.openclaw/dashboard"
OUTPUT_FILE = os.path.join(DASHBOARD_DIR, "sentinel_data.json")
LOG_FILE = "/root/.openclaw/logs/sentinel_sync.log"

FINNHUB_KEY = os.environ.get("FINNHUB_API_KEY", "")
FMP_KEY = os.environ.get("FMP_API_KEY", "")

FINNHUB_BASE = "https://finnhub.io/api/v1"
FMP_BASE = "https://site.financialmodelingprep.com/api/v3"

# ─── JASE'S WATCHLIST ─────────────────────────────────────────────────────────
# Personal holdings + watchlist tickers organized by theme.
# Edit this to add/remove tickers.

WATCHLIST = {
    "holdings": ["NVDA", "IREN", "UUUU", "IONQ", "VST", "TEM", "SOFI", "MSTR", "USAR", "OKLO"],
    "quantum_nuclear": ["RGTI", "CCJ", "QBTS", "NLR", "SMR"],
    "energy": ["REMX", "XLE", "XOM", "CVX"],
    "metals": ["SCCO", "IAU", "URA", "SLV", "FCX", "GLD"],
    "robotics_ai": ["JOBY", "NRSN", "SYM", "RR", "ARBE"],
    "saudi": ["FLSA", "KSA"],
    "tech_semis": ["AMD", "ARM", "PLTR", "COIN", "MARA"],
}

# Flatten for lookups
ALL_WATCHLIST = []
for tickers in WATCHLIST.values():
    ALL_WATCHLIST.extend(tickers)
ALL_WATCHLIST = list(set(ALL_WATCHLIST))

# Rate limiting
FINNHUB_DELAY = 1.1
FMP_DELAY = 0.5

# ─── Logging ──────────────────────────────────────────────────────────────────

def log(msg):
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except:
        pass

# ─── API Helpers ──────────────────────────────────────────────────────────────

def finnhub_get(endpoint, params=None):
    if not FINNHUB_KEY:
        return None
    if params is None:
        params = {}
    params["token"] = FINNHUB_KEY
    try:
        time.sleep(FINNHUB_DELAY)
        r = requests.get(f"{FINNHUB_BASE}{endpoint}", params=params, timeout=15)
        if r.status_code == 200:
            return r.json()
        elif r.status_code == 429:
            log(f"  RATE LIMITED on {endpoint}, waiting 60s...")
            time.sleep(60)
            return None
        elif r.status_code == 403:
            log(f"  PREMIUM REQUIRED: {endpoint}")
            return None
        else:
            log(f"  Finnhub {endpoint} → {r.status_code}")
            return None
    except Exception as e:
        log(f"  Finnhub error {endpoint}: {e}")
        return None

def fmp_get(endpoint, params=None):
    if not FMP_KEY:
        return None
    if params is None:
        params = {}
    params["apikey"] = FMP_KEY
    try:
        time.sleep(FMP_DELAY)
        r = requests.get(f"{FMP_BASE}{endpoint}", params=params, timeout=15)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict) and "Error Message" in data:
                log(f"  FMP error {endpoint}: {data['Error Message']}")
                return None
            return data
        elif r.status_code == 429:
            log(f"  FMP RATE LIMITED: {endpoint}")
            return None
        else:
            log(f"  FMP {endpoint} → {r.status_code}")
            return None
    except Exception as e:
        log(f"  FMP error {endpoint}: {e}")
        return None

# ─── Data Fetchers ────────────────────────────────────────────────────────────

def fetch_market_wide_insiders():
    """Latest insider transactions across ALL stocks (not just watchlist)."""
    log("Fetching market-wide insider transactions...")
    data = finnhub_get("/stock/insider-transactions", {"symbol": ""})
    if data and "data" in data:
        txs = data["data"][:100]
        log(f"  Got {len(txs)} market-wide transactions")
        return txs
    return []

def fetch_watchlist_insiders_finnhub():
    """Insider transactions for Jase's specific watchlist tickers."""
    log("Fetching watchlist insider transactions (Finnhub)...")
    results = []
    priority = WATCHLIST.get("holdings", []) + WATCHLIST.get("quantum_nuclear", [])
    for ticker in priority[:12]:
        data = finnhub_get("/stock/insider-transactions", {"symbol": ticker})
        if data and "data" in data:
            for tx in data["data"][:5]:
                tx["_watchlist"] = True
                results.append(tx)
    log(f"  Got {len(results)} watchlist insider txs")
    return results

def fetch_watchlist_insiders_fmp():
    """Insider transactions for watchlist from FMP."""
    log("Fetching watchlist insider transactions (FMP)...")
    results = []
    tickers = WATCHLIST.get("holdings", [])[:8]
    for ticker in tickers:
        data = fmp_get("/insider-trading", {"symbol": ticker})
        if data and isinstance(data, list):
            for tx in data[:3]:
                tx["_watchlist"] = True
                results.append(tx)
    log(f"  Got {len(results)} FMP watchlist insider txs")
    return results

def fetch_fmp_insider_market():
    """Latest insider trades across the market from FMP."""
    log("Fetching FMP market-wide insider trades...")
    data = fmp_get("/insider-trading", {"page": 0})
    if data and isinstance(data, list):
        log(f"  Got {len(data[:50])} FMP market trades")
        return data[:50]
    return []

def fetch_insider_sentiment():
    """Insider sentiment (MSPR) for holdings — may require premium."""
    log("Fetching insider sentiment for holdings...")
    results = []
    today = datetime.utcnow()
    from_d = (today - timedelta(days=90)).strftime("%Y-%m-%d")
    to_d = today.strftime("%Y-%m-%d")
    for ticker in WATCHLIST.get("holdings", [])[:8]:
        data = finnhub_get("/stock/insider-sentiment", {
            "symbol": ticker, "from": from_d, "to": to_d
        })
        if data and "data" in data and data["data"]:
            latest = data["data"][-1]
            results.append({
                "symbol": ticker,
                "mspr": latest.get("mspr", 0),
                "change": latest.get("change", 0),
                "month": latest.get("month"),
                "year": latest.get("year"),
            })
    log(f"  Got sentiment for {len(results)} tickers")
    return results

def fetch_recommendations():
    """Analyst buy/hold/sell for holdings + key watchlist."""
    log("Fetching analyst recommendations...")
    results = []
    tickers = WATCHLIST.get("holdings", []) + WATCHLIST.get("tech_semis", [])[:3]
    for ticker in list(set(tickers))[:12]:
        data = finnhub_get("/stock/recommendation", {"symbol": ticker})
        if data and len(data) > 0:
            r = data[0]
            results.append({
                "symbol": ticker,
                "buy": r.get("buy", 0),
                "hold": r.get("hold", 0),
                "sell": r.get("sell", 0),
                "strongBuy": r.get("strongBuy", 0),
                "strongSell": r.get("strongSell", 0),
                "period": r.get("period", ""),
            })
    log(f"  Got recommendations for {len(results)} tickers")
    return results

def fetch_earnings_calendar():
    """Upcoming earnings next 7 days."""
    log("Fetching earnings calendar...")
    today = datetime.utcnow()
    data = finnhub_get("/calendar/earnings", {
        "from": today.strftime("%Y-%m-%d"),
        "to": (today + timedelta(days=7)).strftime("%Y-%m-%d"),
    })
    if data and "earningsCalendar" in data:
        earnings = data["earningsCalendar"][:50]
        log(f"  Got {len(earnings)} upcoming earnings")
        return earnings
    return []

def fetch_market_news():
    """Combined market news from Finnhub + FMP."""
    log("Fetching market news...")
    news = []

    fh_data = finnhub_get("/news", {"category": "general"})
    if fh_data:
        for n in fh_data[:12]:
            news.append({
                "headline": n.get("headline", ""),
                "source": n.get("source", ""),
                "url": n.get("url", ""),
                "summary": n.get("summary", "")[:200],
                "datetime": n.get("datetime", 0),
                "related": n.get("related", ""),
                "api": "finnhub",
            })

    fmp_data = fmp_get("/stock_news", {"limit": 12})
    if fmp_data and isinstance(fmp_data, list):
        for n in fmp_data[:12]:
            news.append({
                "headline": n.get("title", ""),
                "source": n.get("site", ""),
                "url": n.get("url", ""),
                "summary": n.get("text", "")[:200],
                "datetime": n.get("publishedDate", ""),
                "related": n.get("symbol", ""),
                "api": "fmp",
            })

    log(f"  Got {len(news)} news items")
    return news

def fetch_economic_calendar():
    """Upcoming high-impact economic events."""
    log("Fetching economic calendar...")
    today = datetime.utcnow()
    data = fmp_get("/economic_calendar", {
        "from": today.strftime("%Y-%m-%d"),
        "to": (today + timedelta(days=7)).strftime("%Y-%m-%d"),
    })
    if data and isinstance(data, list):
        events = [e for e in data if e.get("impact", "") in ("High", "Medium")][:20]
        log(f"  Got {len(events)} economic events")
        return events
    return []

# ─── DISCOVERY SCAN ───────────────────────────────────────────────────────────

def discovery_scan(market_txs_finnhub, market_txs_fmp):
    """
    Scan market-wide insider transactions for interesting small/mid-cap activity.
    Filters:
    - NOT already on Jase's watchlist (those are tracked separately)
    - Purchase transactions only (buys signal confidence)
    - Groups by ticker, scores by cluster strength and dollar value
    Returns top discoveries sorted by score.
    """
    log("Running discovery scan for small/mid-cap institutional moves...")

    discoveries = {}

    def process_tx(symbol, name, code, price, shares, date, source):
        if not symbol or symbol in ALL_WATCHLIST:
            return

        code_upper = str(code).upper()
        is_buy = code_upper in ("P", "P-PURCHASE", "PURCHASE", "A")
        if not is_buy:
            return

        value = abs(float(price or 0)) * abs(float(shares or 0))
        if value < 10000:
            return

        if symbol not in discoveries:
            discoveries[symbol] = {
                "symbol": symbol,
                "score": 0,
                "buy_count": 0,
                "total_value": 0,
                "insiders": [],
                "latest_date": "",
                "discovery": True,
            }

        d = discoveries[symbol]
        d["buy_count"] += 1
        d["total_value"] += value
        d["score"] += 10

        if value > 50000: d["score"] += 10
        if value > 200000: d["score"] += 15
        if value > 500000: d["score"] += 20
        if value > 1000000: d["score"] += 30

        if len(d["insiders"]) < 5:
            d["insiders"].append({
                "name": name,
                "value": round(value, 2),
                "date": date,
                "source": source,
            })

        if str(date) > d["latest_date"]:
            d["latest_date"] = str(date)

    for tx in (market_txs_finnhub or []):
        process_tx(
            tx.get("symbol", ""),
            tx.get("name", "Unknown"),
            tx.get("transactionCode", ""),
            tx.get("transactionPrice", 0),
            tx.get("change", 0),
            tx.get("transactionDate", tx.get("filingDate", "")),
            "finnhub",
        )

    for tx in (market_txs_fmp or []):
        process_tx(
            tx.get("symbol", tx.get("ticker", "")),
            tx.get("reportingName", tx.get("name", "Unknown")),
            tx.get("transactionType", tx.get("acquistionOrDisposition", "")),
            tx.get("price", 0),
            tx.get("securitiesTransacted", 0),
            tx.get("transactionDate", tx.get("filingDate", "")),
            "fmp",
        )

    for sym, d in discoveries.items():
        if d["buy_count"] >= 3:
            d["score"] += 30
            d["signal_type"] = "CLUSTER_BUY"
        elif d["buy_count"] >= 2:
            d["score"] += 15
            d["signal_type"] = "MULTI_BUY"
        else:
            d["signal_type"] = "INSIDER_BUY"

    sorted_disc = sorted(discoveries.values(), key=lambda x: x["score"], reverse=True)
    top = sorted_disc[:20]
    log(f"  Found {len(discoveries)} unique tickers with insider buying")
    log(f"  Top discoveries: {[d['symbol'] for d in top[:5]]}")
    return top

# ─── Signal Scoring (Watchlist) ───────────────────────────────────────────────

def score_watchlist_signals(finnhub_wl, fmp_wl):
    """Score insider activity specifically for watchlist tickers."""
    log("Scoring watchlist insider signals...")

    signals = {}

    def process(tx, source):
        symbol = tx.get("symbol", tx.get("ticker", ""))
        if not symbol:
            return

        code = str(tx.get("transactionCode", tx.get("transactionType", ""))).upper()
        is_buy = code in ("P", "P-PURCHASE", "PURCHASE", "A")
        is_sell = code in ("S", "S-SALE", "SALE", "D")

        price = float(tx.get("transactionPrice", tx.get("price", 0)) or 0)
        shares = abs(float(tx.get("change", tx.get("securitiesTransacted", 0)) or 0))
        value = price * shares

        if symbol not in signals:
            category = "other"
            for cat, tickers in WATCHLIST.items():
                if symbol in tickers:
                    category = cat
                    break

            signals[symbol] = {
                "symbol": symbol,
                "category": category,
                "score": 0,
                "buy_count": 0,
                "sell_count": 0,
                "total_buy_value": 0,
                "total_sell_value": 0,
                "insiders": [],
                "latest_date": "",
                "on_watchlist": True,
                "signal_type": "neutral",
            }

        s = signals[symbol]

        if is_buy:
            s["buy_count"] += 1
            s["total_buy_value"] += value
            s["score"] += 10
            if value > 100000: s["score"] += 15
            if value > 500000: s["score"] += 20
            if value > 1000000: s["score"] += 30
        elif is_sell:
            s["sell_count"] += 1
            s["total_sell_value"] += value
            s["score"] -= 3

        if symbol in WATCHLIST.get("holdings", []):
            s["score"] += 8

        if len(s["insiders"]) < 5:
            s["insiders"].append({
                "name": tx.get("name", tx.get("reportingName", "Unknown")),
                "type": "BUY" if is_buy else "SELL" if is_sell else "OTHER",
                "value": round(value, 2),
                "date": tx.get("transactionDate", tx.get("filingDate", "")),
            })

        d = tx.get("transactionDate", tx.get("filingDate", ""))
        if str(d) > s["latest_date"]:
            s["latest_date"] = str(d)

    for tx in (finnhub_wl or []):
        process(tx, "finnhub")
    for tx in (fmp_wl or []):
        process(tx, "fmp")

    for sym, s in signals.items():
        if s["buy_count"] >= 3:
            s["score"] += 25
            s["signal_type"] = "STRONG_BUY"
        elif s["buy_count"] >= 2:
            s["score"] += 10
            s["signal_type"] = "BUY"
        elif s["buy_count"] >= 1 and s["sell_count"] == 0:
            s["signal_type"] = "BUY"
        elif s["sell_count"] >= 3 and s["buy_count"] == 0:
            s["signal_type"] = "SELL"
        elif s["buy_count"] == 0 and s["sell_count"] > 0:
            s["signal_type"] = "SELL"
        else:
            s["signal_type"] = "MIXED"

    return sorted(signals.values(), key=lambda x: x["score"], reverse=True)

# ─── Main Pipeline ────────────────────────────────────────────────────────────

def run():
    log("=" * 60)
    log("SENTINEL SYNC — Starting")
    log(f"  Finnhub: {'OK' if FINNHUB_KEY else 'NO KEY'}")
    log(f"  FMP:     {'OK' if FMP_KEY else 'NO KEY'}")
    log(f"  Watchlist: {len(ALL_WATCHLIST)} tickers across {len(WATCHLIST)} categories")
    log("=" * 60)

    if not FINNHUB_KEY and not FMP_KEY:
        log("ERROR: No API keys. Set FINNHUB_API_KEY and/or FMP_API_KEY in .sentinel_env")
        sys.exit(1)

    mkt_finnhub = fetch_market_wide_insiders() if FINNHUB_KEY else []
    mkt_fmp = fetch_fmp_insider_market() if FMP_KEY else []
    wl_finnhub = fetch_watchlist_insiders_finnhub() if FINNHUB_KEY else []
    wl_fmp = fetch_watchlist_insiders_fmp() if FMP_KEY else []
    sentiment = fetch_insider_sentiment() if FINNHUB_KEY else []
    recs = fetch_recommendations() if FINNHUB_KEY else []
    earnings = fetch_earnings_calendar() if FINNHUB_KEY else []
    news = fetch_market_news()
    econ = fetch_economic_calendar() if FMP_KEY else []

    watchlist_signals = score_watchlist_signals(wl_finnhub, wl_fmp)
    discoveries = discovery_scan(mkt_finnhub, mkt_fmp)

    data = {
        "last_updated": datetime.utcnow().isoformat() + "Z",
        "sources": {"finnhub": bool(FINNHUB_KEY), "fmp": bool(FMP_KEY)},
        "watchlist_config": WATCHLIST,
        "watchlist_signals": watchlist_signals,
        "watchlist_buys": [s for s in watchlist_signals if s["signal_type"] in ("BUY", "STRONG_BUY")],
        "watchlist_sells": [s for s in watchlist_signals if s["signal_type"] == "SELL"],
        "discoveries": discoveries,
        "top_discoveries": discoveries[:10],
        "insider_sentiment": sentiment,
        "analyst_recommendations": recs,
        "earnings_calendar": earnings,
        "economic_calendar": econ,
        "market_news": news,
        "summary": {
            "total_market_txs": len(mkt_finnhub) + len(mkt_fmp),
            "watchlist_txs": len(wl_finnhub) + len(wl_fmp),
            "watchlist_signals": len(watchlist_signals),
            "watchlist_buys": len([s for s in watchlist_signals if s["signal_type"] in ("BUY", "STRONG_BUY")]),
            "watchlist_strong_buys": len([s for s in watchlist_signals if s["signal_type"] == "STRONG_BUY"]),
            "discoveries_found": len(discoveries),
            "cluster_discoveries": len([d for d in discoveries if d.get("signal_type") == "CLUSTER_BUY"]),
            "upcoming_earnings": len(earnings),
            "watchlist_tickers": len(ALL_WATCHLIST),
        },
    }

    data["watchlist_earnings"] = [
        e for e in earnings if e.get("symbol", "") in ALL_WATCHLIST
    ]

    # ── Build daily_digest for daily_briefing.py ─────────────────────────────
    strong_buys = data["watchlist_buys"]
    top_discs   = discoveries[:3]
    digest_parts = []
    for sig in strong_buys[:3]:
        sym       = sig.get("symbol", "?")
        sig_type  = sig.get("signal_type", "BUY")
        buy_count = sig.get("buy_count", 0)
        total_val = sig.get("total_buy_value", 0)
        val_str   = f"${total_val/1000:.0f}k" if total_val >= 1000 else f"${total_val:.0f}"
        cat       = sig.get("category", "")
        cat_str   = f" [{cat}]" if cat else ""
        digest_parts.append(f"{sym}{cat_str}: {sig_type} | {buy_count} insider(s) | {val_str}")
    if not digest_parts:
        for d in top_discs:
            sym       = d.get("symbol", "?")
            buy_count = d.get("buy_count", 0)
            val       = d.get("total_value", 0)
            val_str   = f"${val/1000:.0f}k" if val >= 1000 else f"${val:.0f}"
            digest_parts.append(f"{sym}: {buy_count} insider(s) {val_str} (discovery)")
    if digest_parts:
        data["daily_digest"] = " | ".join(digest_parts)
    else:
        data["daily_digest"] = "No notable insider signals today"

    os.makedirs(DASHBOARD_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)

    log("\n" + "=" * 60)
    log("SENTINEL SYNC — Complete")
    s = data["summary"]
    log(f"  Market transactions scanned: {s['total_market_txs']}")
    log(f"  Watchlist insider txs: {s['watchlist_txs']}")
    log(f"  Watchlist buy signals: {s['watchlist_buys']}")
    log(f"  Watchlist STRONG buys: {s['watchlist_strong_buys']}")
    log(f"  Discovery tickers found: {s['discoveries_found']}")
    log(f"  Cluster discoveries: {s['cluster_discoveries']}")
    log(f"  Upcoming earnings: {s['upcoming_earnings']}")
    if data["top_discoveries"]:
        log(f"  Top discovery: {data['top_discoveries'][0]['symbol']} (score {data['top_discoveries'][0]['score']})")
    log(f"  Output: {OUTPUT_FILE}")
    log("=" * 60)

if __name__ == "__main__":
    run()
