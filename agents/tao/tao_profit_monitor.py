"""
Tao Profit Monitor — Phase 3
Runs every 6 hours. Checks if any subnet position has hit a profit-taking tier.

Profit Tiers:
  Tier 1: +50%  → unstake 20% of position → TAO
  Tier 2: +100% → unstake 25% of remaining → TAO
  Tier 3: +200% → unstake 25% of remaining → TAO
  Tier 4: +500% → unstake 25% of remaining → TAO
  Hold:         → keep final ~25% forever (moonbag)

Profit routing:
  50% → root stake (netuid 0)
  50% → highest-scoring subnet from latest scores

Usage:
  python3 tao_profit_monitor.py           # live
  python3 tao_profit_monitor.py --simulate # print commands, don't execute
"""

import sys
import subprocess
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))
from tao_config import TaoConfig, DATA_DIR, WALLET_NAME, HOTKEY_NAME

config = TaoConfig()

PORTFOLIO_FILE     = Path("/root/.openclaw/dashboard/tao_portfolio.json")
SUBNET_SCORES_FILE = DATA_DIR / "tao_subnet_scores.json"

SIMULATE = "--simulate" in sys.argv

# Tier: (tier_number, pnl_threshold_pct, unstake_fraction_of_position)
PROFIT_TIERS = [
    (1, 50.0,  0.20),
    (2, 100.0, 0.25),
    (3, 200.0, 0.25),
    (4, 500.0, 0.25),
]


# ---------------------------------------------------------------------------
# Stake value query
# ---------------------------------------------------------------------------

def get_current_stake_values() -> dict:
    """
    Query current TAO-equivalent stake values per netuid.
    Primary: subtensor SDK. Fallback: btcli wallet overview parse.
    Returns {netuid: current_value_tao}.
    """
    config.log("profit_monitor — querying current stake values via SDK")
    try:
        sub    = config.get_subtensor()
        wallet = config.get_wallet()
        coldkey_ss58 = wallet.coldkeypub.ss58_address

        stake_info = sub.get_stake_info_for_coldkey(coldkey_ss58=coldkey_ss58)
        if stake_info:
            values = {}
            for s in stake_info:
                netuid = getattr(s, "netuid", None)
                if netuid is None:
                    continue
                val = float(s.stake.tao) if hasattr(s, "stake") else 0.0
                if val > 0:
                    values[netuid] = values.get(netuid, 0.0) + val
            if values:
                config.log(f"profit_monitor — SDK query OK: {len(values)} positions")
                return values
    except Exception as e:
        config.log(f"WARN: profit_monitor — SDK query failed: {e}, falling back to btcli")

    return _parse_btcli_overview()


def _parse_btcli_overview() -> dict:
    """Parse btcli wallet overview --all to extract per-netuid stake values."""
    import re
    try:
        result = subprocess.run(
            ["btcli", "wallet", "overview", "--wallet-name", WALLET_NAME, "--all"],
            capture_output=True, text=True, timeout=60,
        )
        output = result.stdout + result.stderr
        config.log(f"profit_monitor — btcli wallet overview output: {len(output)} chars")

        values = {}
        for line in output.split("\n"):
            # Match: netuid (1-3 digits) + a TAO amount somewhere on the same line
            m = re.search(r"\b(\d{1,3})\b.*?(\d+\.\d{4,})", line)
            if m:
                try:
                    netuid = int(m.group(1))
                    amount = float(m.group(2))
                    if 0 <= netuid <= 300 and amount > 0:
                        values[netuid] = max(values.get(netuid, 0.0), amount)
                except ValueError:
                    pass

        if values:
            config.log(f"profit_monitor — btcli parse OK: {len(values)} positions")
            return values

        config.log(f"WARN: profit_monitor — btcli parse found nothing. Output preview:\n{output[:600]}")
        return {}
    except Exception as e:
        config.log(f"ERROR: profit_monitor — btcli fallback failed: {e}")
        return {}


# ---------------------------------------------------------------------------
# btcli helpers
# ---------------------------------------------------------------------------

def _run_btcli(cmd: list, label: str, simulate: bool) -> tuple[bool, str]:
    cmd_str = " ".join(cmd)
    if simulate:
        print(f"  [SIMULATE] {cmd_str}")
        config.log(f"[SIMULATE] {label}: {cmd_str}")
        return True, "[simulated]"
    config.log(f"profit_monitor — {label}: {cmd_str}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        ok  = r.returncode == 0
        config.log(f"profit_monitor — {label} {'OK' if ok else 'FAILED'} | {out[:300]}")
        return ok, out
    except subprocess.TimeoutExpired:
        config.log(f"ERROR: {label} timed out")
        return False, "timeout"
    except Exception as e:
        config.log(f"ERROR: {label}: {e}")
        return False, str(e)


def unstake(amount: float, netuid: int, simulate: bool) -> tuple[bool, str]:
    return _run_btcli(
        ["btcli", "stake", "remove", "--wallet-name", WALLET_NAME,
         "--hotkey", HOTKEY_NAME, "--amount", f"{amount:.6f}",
         "--netuid", str(netuid), "--no-prompt", "--unsafe"],
        f"unstake SN{netuid}",
        simulate,
    )


def restake(amount: float, netuid: int, simulate: bool) -> tuple[bool, str]:
    return _run_btcli(
        ["btcli", "stake", "add", "--wallet-name", WALLET_NAME,
         "--hotkey", HOTKEY_NAME, "--amount", f"{amount:.6f}",
         "--netuid", str(netuid), "--no-prompt", "--unsafe"],
        f"restake SN{netuid}",
        simulate,
    )


def get_top_subnet_for_reinvest() -> dict | None:
    scores = config.load_json(str(SUBNET_SCORES_FILE))
    if not scores or not scores.get("top_subnets"):
        return None
    return max(scores["top_subnets"], key=lambda s: s.get("score", 0))


# ---------------------------------------------------------------------------
# Tier checking
# ---------------------------------------------------------------------------

def check_and_execute_tiers(portfolio: dict, current_values: dict) -> dict:
    tao_price = config.get_tao_price_usd() or portfolio.get("tao_price_usd", 0.0)
    positions = portfolio.get("subnet_positions", [])

    for pos in positions:
        netuid     = pos["netuid"]
        name       = pos.get("name", f"SN{netuid}")
        cost_basis = pos.get("staked_tao", 0.0)

        if cost_basis <= 0:
            continue

        cur_val = current_values.get(netuid, pos.get("current_value_tao", cost_basis))
        pnl_pct = (cur_val - cost_basis) / cost_basis * 100

        tiers_hit          = pos.get("tiers_hit", [])
        total_profit_taken = pos.get("total_profit_taken_tao", 0.0)

        pos["current_value_tao"] = round(cur_val, 6)
        pos["pnl_pct"]           = round(pnl_pct, 2)

        trend = "▲" if pnl_pct >= 0 else "▼"
        print(
            f"  SN{netuid:3d} {name:<18} "
            f"basis={cost_basis:.6f} τ  "
            f"current={cur_val:.6f} τ  "
            f"{trend}{abs(pnl_pct):.1f}%  "
            f"tiers={tiers_hit or '—'}"
        )
        config.log(
            f"profit_monitor — SN{netuid} {name}: "
            f"basis={cost_basis:.6f} cur={cur_val:.6f} pnl={pnl_pct:+.1f}% tiers={tiers_hit}"
        )

        for tier_num, threshold_pct, unstake_frac in PROFIT_TIERS:
            if tier_num in tiers_hit:
                continue
            if pnl_pct < threshold_pct:
                continue

            # Tier triggered
            unstake_amt   = round(cur_val * unstake_frac, 6)
            remaining_amt = round(cur_val - unstake_amt, 6)

            tier_label = {1: "Tier 1 (+50%)", 2: "Tier 2 (+100%)",
                          3: "Tier 3 (+200%)", 4: "Tier 4 (+500%)"}[tier_num]

            config.log(
                f"profit_monitor — *** {tier_label} TRIGGERED SN{netuid} {name} "
                f"+{pnl_pct:.1f}% >= +{threshold_pct:.0f}% | "
                f"unstaking {unstake_frac*100:.0f}% = {unstake_amt:.6f} τ ***"
            )
            print(f"\n  *** {tier_label} TRIGGERED — SN{netuid} {name} +{pnl_pct:.1f}% ***")
            print(f"      Unstaking {unstake_frac*100:.0f}% = {unstake_amt:.6f} τ  remaining={remaining_amt:.6f} τ")

            ok, _ = unstake(unstake_amt, netuid, SIMULATE)
            if not ok:
                config.log(f"ERROR: profit_monitor — unstake failed SN{netuid} tier {tier_num}")
                continue

            # Route profit: 50% root / 50% top subnet
            root_amt   = round(unstake_amt * 0.5, 6)
            reinv_amt  = round(unstake_amt * 0.5, 6)
            top_sn     = get_top_subnet_for_reinvest()
            reinv_uid  = top_sn["netuid"] if top_sn else 0
            reinv_name = top_sn.get("name", "Root") if top_sn else "Root"

            print(f"      Routing: {root_amt:.6f} τ → Root | {reinv_amt:.6f} τ → SN{reinv_uid} {reinv_name}")

            restake(root_amt,  netuid=0,        simulate=SIMULATE)
            restake(reinv_amt, netuid=reinv_uid, simulate=SIMULATE)

            tiers_hit.append(tier_num)
            total_profit_taken    += unstake_amt
            pos["staked_tao"]     = round(max(0.0, cost_basis - unstake_amt), 6)
            pos["current_value_tao"] = remaining_amt
            cur_val               = remaining_amt
            # Recalculate pnl_pct on updated cost basis for next tier check
            new_cost = pos["staked_tao"]
            pnl_pct = (cur_val - new_cost) / new_cost * 100 if new_cost > 0 else 0.0

            msg = (
                f"💰 TAO PROFIT TAKE — {tier_label}\n"
                f"SN{netuid} {name}: +{pnl_pct:.1f}% from cost basis\n"
                f"Unstaked: {unstake_amt:.6f} τ ({unstake_frac*100:.0f}% of position)\n"
                f"Remaining position: {remaining_amt:.6f} τ\n"
                f"Profit routed:\n"
                f"→ Root stake: {root_amt:.6f} τ\n"
                f"→ SN{reinv_uid} {reinv_name} (top scorer): {reinv_amt:.6f} τ"
            )
            if SIMULATE:
                print(f"\n  [SIMULATE] Telegram alert:\n{msg}\n")
            # else:
            #     config.send_telegram(msg)  # Commented out — profit tier alerts handled by daily briefing

        pos["tiers_hit"]             = tiers_hit
        pos["total_profit_taken_tao"] = round(total_profit_taken, 6)

    portfolio["subnet_positions"]  = positions
    portfolio["tao_price_usd"]     = tao_price
    portfolio["last_profit_check"] = datetime.now(timezone.utc).isoformat()
    return portfolio


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    config.log("=== Tao Profit Monitor Start ===")

    if SIMULATE:
        config.log("profit_monitor — SIMULATE mode active")
        print("\n[SIMULATE MODE — no transactions will execute]\n")

    portfolio = config.load_json(str(PORTFOLIO_FILE))
    if not portfolio:
        config.log("ERROR: profit_monitor — portfolio file missing, run tao_dca_engine.py first")
        print("ERROR: No portfolio file found. Run tao_dca_engine.py first.")
        sys.exit(1)

    positions = portfolio.get("subnet_positions", [])
    if not positions:
        config.log("profit_monitor — no subnet positions to monitor")
        print("No subnet positions found.")
        sys.exit(0)

    print()
    print("=" * 70)
    print("TAO PROFIT MONITOR")
    print(f"Positions: {len(positions)}  |  Mode: {'SIMULATE' if SIMULATE else 'LIVE'}")
    print("=" * 70)
    print()
    print(f"  {'SN':<6} {'Name':<18} {'Cost Basis':<18} {'Current':<18} {'PnL%':<10} Tiers")
    print(f"  {'-'*6} {'-'*18} {'-'*18} {'-'*18} {'-'*10} {'-'*8}")

    current_values = get_current_stake_values()

    if not current_values:
        config.log("WARN: profit_monitor — no live values available, using stored portfolio values")
        print("\nWARN: Could not query live stake values — using stored values.\n")
        for pos in positions:
            current_values[pos["netuid"]] = pos.get("current_value_tao", pos.get("staked_tao", 0.0))

    updated = check_and_execute_tiers(portfolio, current_values)

    if not SIMULATE:
        config.save_json(str(PORTFOLIO_FILE), updated)
        config.log("profit_monitor — portfolio saved")

    # Summary
    root_tao           = updated.get("root_staked_tao", 0.0)
    subnet_cost        = sum(p.get("staked_tao", 0) for p in updated["subnet_positions"])
    subnet_cur         = sum(p.get("current_value_tao", p.get("staked_tao", 0)) for p in updated["subnet_positions"])
    total_profit_taken = sum(p.get("total_profit_taken_tao", 0) for p in updated["subnet_positions"])
    subnet_pnl         = (subnet_cur - subnet_cost) / subnet_cost * 100 if subnet_cost > 0 else 0.0
    tao_price          = updated.get("tao_price_usd", 0.0)

    print()
    print("-" * 70)
    print(f"  Root stake:          {root_tao:.6f} τ")
    print(f"  Subnet cost basis:   {subnet_cost:.6f} τ  (${subnet_cost * tao_price:,.2f})")
    print(f"  Subnet current val:  {subnet_cur:.6f} τ  (${subnet_cur * tao_price:,.2f})")
    print(f"  Subnet PnL:          {subnet_pnl:+.2f}%")
    print(f"  Total profit taken:  {total_profit_taken:.6f} τ")
    print(f"  TAO price:           ${tao_price:.2f}")
    print("-" * 70)
    print()

    config.log("=== Tao Profit Monitor Complete ===")


if __name__ == "__main__":
    main()
