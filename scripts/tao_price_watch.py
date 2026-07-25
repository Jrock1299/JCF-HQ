#!/usr/bin/env python3
"""
TAO price watcher — the ONLY Tao component that runs while the agent is parked.

WHY THIS EXISTS
---------------
2026-07-25: all 5 Tao cron jobs were #HOLD'd after taostats confirmed that
nothing was ever staked — the DCA engine logged 5 successful entries while
zero extrinsics landed, burning 0.056408 τ in fees. Jase's call: Tao does
nothing until TAO crosses $393 (bear market; stake with momentum on the way
back up, not into declining subnets).

This script is the entire Tao surface until then.

WHAT IT DOES — AND DELIBERATELY DOES NOT
----------------------------------------
Does:      one CoinGecko price read per day; one Telegram alert if TAO > $393.
Does NOT:  call an LLM, import bittensor, open a chain connection, read a
           wallet, stake, DCA, or take ANY action. It cannot move funds —
           there is no code path here that could.

Cost profile: one HTTPS GET per day. Effectively free to run for months.

Silence by default: below threshold it writes nothing — no Telegram, no log
line, no state churn. Only a threshold crossing or an error produces output.
Alerts fire ONCE (guarded by a sentinel file), not daily.

Usage:
  python3 tao_price_watch.py            # normal daily run
  python3 tao_price_watch.py --status   # print current state, send nothing
  python3 tao_price_watch.py --reset    # clear the sentinel (re-arm the alert)
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

# ── Config ───────────────────────────────────────────────────────────────────
THRESHOLD_USD = 393.0
STATE_FILE    = Path("/root/.openclaw/dashboard/tao_price_watch.json")
LOG_FILE      = Path("/root/.openclaw/logs/tao_price_watch.log")
TIMEOUT       = 15

# Same source tao_price_history.json already used — the one Tao component that
# was actually working throughout the outage.
COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"

# Read straight from the environment; no tao_config import, so this stays
# independent of the parked agent (and creates no tao.log noise).
def _env(name: str, default: str = "") -> str:
    v = os.getenv(name, "")
    if v:
        return v
    # .env fallback — the run wrapper sources it, but be robust if invoked bare.
    for envfile in (Path("/root/.openclaw/.env"), Path("/root/.openclaw/agents/tao/.env")):
        if envfile.exists():
            for line in envfile.read_text().splitlines():
                if line.startswith(f"{name}="):
                    return line.split("=", 1)[1].strip().strip("'\"")
    return default


def log(msg: str) -> None:
    """Append-only log. Called sparingly — silence is the default."""
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a") as f:
            f.write(f"{ts} {msg}\n")
    except Exception:
        pass  # logging must never be the thing that breaks a price check


def get_price() -> float | None:
    try:
        headers = {}
        key = _env("COINGECKO_API_KEY")
        if key:
            headers["x-cg-demo-api-key"] = key
        r = requests.get(
            COINGECKO_URL,
            params={"ids": "bittensor", "vs_currencies": "usd"},
            headers=headers,
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return float(r.json()["bittensor"]["usd"])
    except Exception as e:
        log(f"WARN price fetch failed: {e}")
        return None


def send_telegram(text: str) -> bool:
    token = _env("TELEGRAM_BOT_TOKEN")
    chat  = _env("TELEGRAM_ALERT_CHAT_ID") or _env("TELEGRAM_CHAT_ID") or "797062420"
    if not token:
        log("ERROR TELEGRAM_BOT_TOKEN unset — alert not delivered")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text, "parse_mode": "HTML"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        log(f"ERROR telegram send failed: {e}")
        return False


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(d: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2))
    tmp.replace(STATE_FILE)


# The gate text lives in the alert itself, so the message that wakes Jase up
# months from now carries its own preconditions — no memory required.
ALERT = """☯️ <b>TAO THRESHOLD CROSSED</b>

TAO = <b>${price:,.2f}</b>  (threshold ${threshold:,.2f})
Holding: <b>3.288561 τ</b> — entirely UNSTAKED
Value: ~${value:,.2f}

<b>Threshold crossed. Do NOT stake until the execution path is verified.</b>

Crossing $393 does not authorize staking. All three must be true first:

1. The DCA silent-failure bug is fixed — the path that logged 5 successful
   entries while zero extrinsics landed (0.056408 τ burned in fees).
2. The bittensor 10.2.0 SDK migration is done.
3. A SMALL test stake is verified ON-CHAIN via taostats before any larger
   amount follows.

All 5 Tao crons remain #HOLD'd. This watcher takes no action and cannot
stake — it is alert-only.

taostats.io/account/5FPP7TKkkY4JpoobgELRcUajUzw1t3KcAfPKQ5yEw11UgVS8

— this alert fires once; re-arm with tao_price_watch.py --reset"""


def main() -> int:
    state = load_state()

    if "--reset" in sys.argv:
        state.pop("alert_sent_at", None)
        state.pop("alert_sent_price", None)
        save_state(state)
        print("Sentinel cleared — alert re-armed.")
        return 0

    price = get_price()

    if "--status" in sys.argv:
        print(f"threshold      : ${THRESHOLD_USD:,.2f}")
        print(f"current price  : {f'${price:,.2f}' if price else 'unavailable'}")
        print(f"alert sent     : {state.get('alert_sent_at') or 'no (armed)'}")
        print(f"last checked   : {state.get('last_checked_at') or 'never'}")
        print(f"last price seen: {state.get('last_price') or 'n/a'}")
        return 0

    if price is None:
        return 1  # already logged; cron surfaces nothing

    now = datetime.now(timezone.utc).isoformat()
    state.update({"last_checked_at": now, "last_price": price,
                  "threshold_usd": THRESHOLD_USD})

    # Below threshold: stay completely silent. No Telegram, no log line.
    if price <= THRESHOLD_USD:
        save_state(state)
        return 0

    # Above threshold but already alerted: stay silent too.
    if state.get("alert_sent_at"):
        save_state(state)
        return 0

    # Cross — fire exactly once.
    msg = ALERT.format(price=price, threshold=THRESHOLD_USD,
                       value=price * 3.288561)
    if send_telegram(msg):
        state["alert_sent_at"] = now
        state["alert_sent_price"] = price
        log(f"ALERT SENT — TAO ${price:,.2f} crossed ${THRESHOLD_USD:,.2f}")
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
