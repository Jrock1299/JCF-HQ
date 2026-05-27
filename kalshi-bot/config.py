"""
config.py — Centralized settings and Kalshi API client base.

Kalshi uses RSA-PSS request signing, not simple bearer tokens:
  KALSHI_API_KEY    = Key ID (string from the Kalshi dashboard)
  KALSHI_API_SECRET = RSA private key, either:
                        - Raw PEM content (starts with -----BEGIN)
                        - Path to a .pem file
  ANTHROPIC_API_KEY = Anthropic API key
"""

import os
import time
import base64
from pathlib import Path

import requests
from dotenv import load_dotenv
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding

load_dotenv()

# ── API credentials ──────────────────────────────────────────────────────────

KALSHI_API_KEY    = os.environ["KALSHI_API_KEY"]
KALSHI_API_SECRET = os.environ["KALSHI_API_SECRET"]   # PEM content or file path
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

# ── Kalshi base URLs ─────────────────────────────────────────────────────────

KALSHI_BASE_URL  = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_DEMO_URL  = "https://demo-api.kalshi.co/trade-api/v2"

# Toggle: set KALSHI_DEMO=true in .env to use the sandbox
USE_DEMO = os.getenv("KALSHI_DEMO", "false").lower() == "true"
BASE_URL = KALSHI_DEMO_URL if USE_DEMO else KALSHI_BASE_URL

# ── Strategy settings ────────────────────────────────────────────────────────

# Scanner: only look at markets closing between MIN and MAX minutes from now
SCAN_CLOSE_MIN_MINUTES = 10
SCAN_CLOSE_MAX_MINUTES = 20

# Momentum window: how many minutes of trade history to load per market
MOMENTUM_WINDOW_MINUTES = 5

# Risk — tightened for Claude-brain era
RISK_PER_TRADE_PCT   = 0.05   # 5% of bankroll per trade (Kelly from brain, capped here)
MAX_DAILY_TRADES     = 10     # hard cap; brain recommends quality over quantity
DAILY_LOSS_LIMIT_PCT = 0.15   # stop trading if down 15% on the day
MAX_OPEN_POSITIONS   = 3      # max simultaneous positions

# Claude model to use for scoring
CLAUDE_MODEL = "claude-opus-4-6"

# Main loop interval (seconds)
LOOP_INTERVAL = 60

# ── Kalshi HTTP client ───────────────────────────────────────────────────────

def _load_private_key():
    """Load RSA private key from PEM string or file path."""
    secret = KALSHI_API_SECRET.strip()
    if secret.startswith("-----BEGIN"):
        pem_bytes = secret.encode()
    else:
        pem_bytes = Path(secret).read_bytes()
    return serialization.load_pem_private_key(pem_bytes, password=None)


_private_key = _load_private_key()


def _sign(timestamp_ms: str, method: str, path: str) -> str:
    """RSA-PSS sign the canonical message: timestamp + METHOD + path."""
    message = f"{timestamp_ms}{method.upper()}{path}".encode()
    sig = _private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH,
        ),
        hashes.SHA256(),
    )
    return base64.b64encode(sig).decode()


def _auth_headers(method: str, path: str) -> dict:
    """Return the three Kalshi auth headers for a request."""
    ts = str(int(time.time() * 1000))
    return {
        "KALSHI-ACCESS-KEY":       KALSHI_API_KEY,
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "KALSHI-ACCESS-SIGNATURE": _sign(ts, method, path),
        "Content-Type":            "application/json",
    }


def kalshi_get(path: str, params: dict = None) -> dict:
    """Authenticated GET against the Kalshi REST API.
    `path` must start with '/' and NOT include query params (e.g. '/markets').
    """
    url = f"{BASE_URL}{path}"
    resp = requests.get(url, headers=_auth_headers("GET", f"/trade-api/v2{path}"), params=params)
    resp.raise_for_status()
    return resp.json()


def kalshi_post(path: str, body: dict = None) -> dict:
    """Authenticated POST against the Kalshi REST API."""
    url = f"{BASE_URL}{path}"
    resp = requests.post(
        url,
        headers=_auth_headers("POST", f"/trade-api/v2{path}"),
        json=body or {},
    )
    resp.raise_for_status()
    return resp.json()
