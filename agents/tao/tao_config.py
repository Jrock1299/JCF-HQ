"""
Tao Agent — Shared Configuration and Utilities
Imported by all tao_*.py scripts.
"""

import os
import json
import logging
import requests
import sys
sys.path.insert(0, "/root/.openclaw/scripts")
from telegram_personalities import wrap_message as _wrap_tg
import tempfile
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Load .env from this script's directory
_DIR = Path(__file__).parent
load_dotenv(_DIR / ".env")

# Paths
DATA_DIR = _DIR / "data"
LOG_FILE = _DIR / "tao.log"
DATA_DIR.mkdir(exist_ok=True)

# Env values
WALLET_NAME = os.getenv("WALLET_NAME", "tao_main")
HOTKEY_NAME = os.getenv("HOTKEY_NAME", "staker")
SUBTENSOR_NETWORK = os.getenv("SUBTENSOR_NETWORK", "finney")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "797062420")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "")

# Strategy config
TOTAL_DCA_ENTRIES = int(os.getenv("TOTAL_DCA_ENTRIES", "5"))
ROOT_STAKE_PCT = int(os.getenv("ROOT_STAKE_PCT", "50"))
SUBNET_STAKE_PCT = int(os.getenv("SUBNET_STAKE_PCT", "50"))
DCA_COOLDOWN_HOURS = int(os.getenv("DCA_COOLDOWN_HOURS", "48"))
DCA_DIP_THRESHOLD_PCT = float(os.getenv("DCA_DIP_THRESHOLD_PCT", "2.0"))
MIN_SUBNET_SCORE = int(os.getenv("MIN_SUBNET_SCORE", "50"))


class TaoConfig:
    """Shared configuration and utilities for Tao agent."""

    def __init__(self):
        self._setup_logging()

    def _setup_logging(self):
        logging.basicConfig(
            filename=str(LOG_FILE),
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        # Also log to stdout for cron visibility
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logging.getLogger().addHandler(console)

    def get_wallet(self):
        """Return bittensor Wallet object."""
        from bittensor_wallet import Wallet
        return Wallet(name=WALLET_NAME, hotkey=HOTKEY_NAME)

    def get_subtensor(self):
        """Return Subtensor connection to finney network."""
        import bittensor
        return bittensor.Subtensor(network=SUBTENSOR_NETWORK)

    def send_telegram(self, message: str):
        """Send Telegram alert via bot API."""
        if not TELEGRAM_BOT_TOKEN:
            self.log("WARN: TELEGRAM_BOT_TOKEN not set, skipping alert")
            return
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        wrapped = _wrap_tg('tao', message)
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": wrapped,
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
        except Exception as e:
            self.log(f"WARN: Telegram send failed: {e}")

    def get_tao_price_usd(self) -> float | None:
        """Get current TAO/USD price from CoinGecko."""
        try:
            url = "https://api.coingecko.com/api/v3/simple/price"
            params = {"ids": "bittensor", "vs_currencies": "usd"}
            headers = {}
            if COINGECKO_API_KEY:
                headers["x-cg-demo-api-key"] = COINGECKO_API_KEY
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return float(data["bittensor"]["usd"])
        except Exception as e:
            self.log(f"WARN: CoinGecko price fetch failed: {e}")
            return None

    def load_json(self, filepath: str) -> dict:
        """Load JSON data file with fallback to empty dict."""
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def save_json(self, filepath: str, data: dict):
        """Save JSON data file atomically."""
        path = Path(filepath)
        tmp = path.parent / (path.name + ".tmp")
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, default=str)
        tmp.replace(path)

    def log(self, message: str):
        """Log to tao.log with timestamp."""
        logging.info(message)
