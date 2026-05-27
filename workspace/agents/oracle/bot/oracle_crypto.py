#!/usr/bin/env python3
import os, time, base64, random
import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
def load_env():
    try:
        with open('/etc/environment') as f:
            for line in f:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass

load_env()

KALSHI_BASE = "https://trading-api.kalshi.com/trade-api/v2"
KALSHI_ENV = os.getenv("KALSHI_ENV", "prod")
KALSHI_KEY_ID = os.getenv("KALSHI_KEY_ID")
KALSHI_PRIVATE_KEY_PATH = os.getenv("KALSHI_PRIVATE_KEY_PATH") or "/root/.openclaw/kalshi_private_key.pem"


def get_auth_headers(method, path):
    timestamp = str(int(time.time() * 1000))
    msg = timestamp + method.upper() + path
    with open(KALSHI_PRIVATE_KEY_PATH, "rb") as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None, backend=default_backend())
    signature = private_key.sign(msg.encode(), padding.PKCS1v15(), hashes.SHA256())
    sig_b64 = base64.b64encode(signature).decode()
    return {
        "KALSHI-ACCESS-KEY": KALSHI_KEY_ID,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "KALSHI-ACCESS-SIGNATURE": sig_b64,
        "Content-Type": "application/json"
    }


if __name__ == "__main__":
    path = "/markets?limit=10&status=open"
    headers = get_auth_headers("GET", path)
    response = requests.get(f"{KALSHI_BASE}{path}", headers=headers)
    print(f"Status: {response.status_code}")
    print(response.text[:1000])
