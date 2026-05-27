"""
Tao Data Collector
Runs 3x daily (03:00, 11:00, 19:00 UTC).
Pulls TAO price from CoinGecko and subnet metrics from Bittensor subtensor.
Stores data in data/ directory.
"""

import sys
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from tao_config import TaoConfig, DATA_DIR

config = TaoConfig()

PRICE_HISTORY_FILE = DATA_DIR / "tao_price_history.json"
SUBNET_DATA_FILE = DATA_DIR / "tao_subnet_data.json"
WALLET_STATE_FILE = DATA_DIR / "tao_wallet_state.json"


def collect_price():
    """Get TAO/USD price and append to price history (keeps 90 days)."""
    price = config.get_tao_price_usd()
    if price is None:
        config.log("WARN: collect_price — could not fetch price, skipping")
        return

    history = config.load_json(str(PRICE_HISTORY_FILE))
    if not isinstance(history, dict):
        history = {}

    entries = history.get("prices", [])
    now = datetime.now(timezone.utc).isoformat()
    entries.append({"timestamp": now, "price": price})

    # Trim to last 90 days
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    entries = [
        e for e in entries
        if datetime.fromisoformat(e["timestamp"]) > cutoff
    ]

    # Calculate 7-day moving average
    week_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    week_prices = [
        e["price"] for e in entries
        if datetime.fromisoformat(e["timestamp"]) > week_cutoff
    ]
    ma7 = round(sum(week_prices) / len(week_prices), 4) if week_prices else price

    history["prices"] = entries
    history["latest_price"] = price
    history["ma7"] = ma7
    history["last_updated"] = now

    config.save_json(str(PRICE_HISTORY_FILE), history)
    config.log(f"collect_price — TAO=${price:.2f} | 7d MA=${ma7:.2f} | {len(entries)} data points")


def collect_subnet_metrics():
    """Query subtensor for all subnet data using all_subnets() -> list[DynamicInfo]."""
    try:
        sub = config.get_subtensor()
        config.log("collect_subnet_metrics — connected to subtensor")

        subnets = sub.all_subnets()
        if not subnets:
            config.log("WARN: collect_subnet_metrics — no subnets returned")
            return

        subnet_records = []
        for info in subnets:
            try:
                record = {
                    "netuid": info.netuid,
                    "subnet_name": getattr(info, "subnet_name", ""),
                    "symbol": getattr(info, "symbol", ""),
                    "emission_tao": float(info.emission.tao) if info.emission else 0.0,
                    "alpha_in": float(info.alpha_in.tao) if info.alpha_in else 0.0,
                    "alpha_out": float(info.alpha_out.tao) if info.alpha_out else 0.0,
                    "tao_in": float(info.tao_in.tao) if info.tao_in else 0.0,
                    "price_tao": float(info.price.tao) if info.price else 0.0,
                    "moving_price": getattr(info, "moving_price", 0.0),
                    "is_dynamic": getattr(info, "is_dynamic", False),
                    "tempo": getattr(info, "tempo", 0),
                    "subnet_volume": float(info.subnet_volume.tao) if info.subnet_volume else 0.0,
                }
                if info.subnet_identity:
                    record["description"] = getattr(info.subnet_identity, "description", "")
                subnet_records.append(record)
            except Exception as e:
                config.log(f"WARN: collect_subnet_metrics — error parsing netuid {getattr(info, 'netuid', '?')}: {e}")

        now = datetime.now(timezone.utc).isoformat()
        data = {
            "last_updated": now,
            "subnet_count": len(subnet_records),
            "subnets": subnet_records,
        }
        config.save_json(str(SUBNET_DATA_FILE), data)
        config.log(f"collect_subnet_metrics — saved {len(subnet_records)} subnets")

    except Exception as e:
        config.log(f"WARN: collect_subnet_metrics failed: {e}")
        config.log(traceback.format_exc())


def collect_wallet_balance():
    """Check current wallet balance and staking positions."""
    try:
        sub = config.get_subtensor()
        wallet = config.get_wallet()

        coldkey_ss58 = wallet.coldkeypub.ss58_address
        balance = sub.get_balance(address=coldkey_ss58)
        free_tao = float(balance.tao) if balance else 0.0

        # Get stake info for coldkey
        stake_info = sub.get_stake_info_for_coldkey(coldkey_ss58=coldkey_ss58)

        stakes = []
        total_staked = 0.0
        if stake_info:
            for s in stake_info:
                try:
                    stake_tao = float(s.stake.tao) if hasattr(s, "stake") else 0.0
                    total_staked += stake_tao
                    stakes.append({
                        "hotkey_ss58": s.hotkey_ss58 if hasattr(s, "hotkey_ss58") else str(s),
                        "netuid": getattr(s, "netuid", 0),
                        "stake_tao": stake_tao,
                    })
                except Exception as e:
                    config.log(f"WARN: stake parse error: {e}")

        now = datetime.now(timezone.utc).isoformat()
        data = {
            "last_updated": now,
            "coldkey_ss58": coldkey_ss58,
            "free_tao": free_tao,
            "total_staked_tao": total_staked,
            "total_tao": free_tao + total_staked,
            "stakes": stakes,
        }
        config.save_json(str(WALLET_STATE_FILE), data)
        config.log(f"collect_wallet_balance — free={free_tao:.4f} TAO | staked={total_staked:.4f} TAO | positions={len(stakes)}")

    except Exception as e:
        config.log(f"WARN: collect_wallet_balance failed: {e}")
        config.log(traceback.format_exc())


if __name__ == "__main__":
    config.log("=== Data Collection Start ===")
    collect_price()
    collect_subnet_metrics()
    collect_wallet_balance()
    config.log("=== Data Collection Complete ===")
