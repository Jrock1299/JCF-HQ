"""
Tao DCA Engine — Phase 2
Core execution script: evaluates entry conditions and stakes TAO via btcli.

Strategy:
  Entry 1/5  — executes IMMEDIATELY on first run (get capital working)
  Entries 2-5 — require: price 2%+ below 7d MA AND 48h cooldown since last entry

Each entry: 50% to root staking (netuid 0), 50% split across top scored subnets

Usage:
  python3 tao_dca_engine.py             # normal run
  python3 tao_dca_engine.py --simulate  # print commands, don't execute
"""

import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).parent))
from tao_config import (
    TaoConfig, DATA_DIR,
    WALLET_NAME, HOTKEY_NAME,
    TOTAL_DCA_ENTRIES, ROOT_STAKE_PCT, SUBNET_STAKE_PCT,
    DCA_COOLDOWN_HOURS, DCA_DIP_THRESHOLD_PCT, MIN_SUBNET_SCORE,
)

config = TaoConfig()

# File paths
DCA_STATE_FILE    = DATA_DIR / "tao_dca_state.json"
PRICE_HISTORY_FILE = DATA_DIR / "tao_price_history.json"
SUBNET_SCORES_FILE = DATA_DIR / "tao_subnet_scores.json"
PORTFOLIO_FILE    = Path("/root/.openclaw/dashboard/tao_portfolio.json")

SIMULATE = "--simulate" in sys.argv


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def load_state() -> dict:
    state = config.load_json(str(DCA_STATE_FILE))
    if not state:
        config.log("tao_dca_engine — no state file found, will initialize on first run")
    return state


def init_state(tao_balance: float) -> dict:
    """Create initial state using current wallet balance."""
    tao_per_entry = round(tao_balance / TOTAL_DCA_ENTRIES, 6)
    state = {
        "total_entries_planned": TOTAL_DCA_ENTRIES,
        "entries_executed":      0,
        "entry_history":         [],
        "last_entry_time":       None,
        "initial_tao_balance":   tao_balance,
        "tao_per_entry":         tao_per_entry,
    }
    config.save_json(str(DCA_STATE_FILE), state)
    config.log(
        f"tao_dca_engine — state initialized: "
        f"balance={tao_balance:.6f} TAO, "
        f"tao_per_entry={tao_per_entry:.6f} TAO, "
        f"entries={TOTAL_DCA_ENTRIES}"
    )
    return state


def save_state(state: dict):
    config.save_json(str(DCA_STATE_FILE), state)


# ---------------------------------------------------------------------------
# Entry condition checks
# ---------------------------------------------------------------------------

def check_price_dip() -> tuple[bool, float, float, float]:
    """
    Returns (dip_ok, current_price, ma7, dip_pct).
    dip_ok = True if current price is DCA_DIP_THRESHOLD_PCT% below 7d MA.
    """
    history = config.load_json(str(PRICE_HISTORY_FILE))
    if not history:
        config.log("WARN: tao_dca_engine — no price history file, fetching live price")
        price = config.get_tao_price_usd()
        return False, price or 0.0, 0.0, 0.0

    current_price = history.get("latest_price", 0.0)
    ma7           = history.get("ma7", 0.0)

    if not current_price:
        # Fallback: fetch live
        live = config.get_tao_price_usd()
        if live:
            current_price = live
        else:
            return False, 0.0, ma7, 0.0

    if ma7 <= 0:
        config.log("WARN: tao_dca_engine — no 7d MA available, skipping dip check")
        return False, current_price, ma7, 0.0

    dip_pct = (ma7 - current_price) / ma7 * 100  # positive = below MA
    dip_ok  = dip_pct >= DCA_DIP_THRESHOLD_PCT

    config.log(
        f"tao_dca_engine — price check: "
        f"${current_price:.2f} | 7d MA ${ma7:.2f} | "
        f"dip={dip_pct:.2f}% | threshold={DCA_DIP_THRESHOLD_PCT}% | "
        f"{'PASS' if dip_ok else 'FAIL'}"
    )
    return dip_ok, current_price, ma7, dip_pct


def check_cooldown(state: dict) -> tuple[bool, float]:
    """Returns (cooldown_ok, hours_since_last)."""
    last = state.get("last_entry_time")
    if not last:
        return True, 999.0

    last_dt = datetime.fromisoformat(last)
    now     = datetime.now(timezone.utc)
    hours_elapsed = (now - last_dt).total_seconds() / 3600

    ok = hours_elapsed >= DCA_COOLDOWN_HOURS
    config.log(
        f"tao_dca_engine — cooldown check: "
        f"{hours_elapsed:.1f}h elapsed | threshold={DCA_COOLDOWN_HOURS}h | "
        f"{'PASS' if ok else 'FAIL'}"
    )
    return ok, hours_elapsed


def load_subnet_scores() -> list:
    """Load top subnets from scorer output. Returns list or empty list."""
    scores = config.load_json(str(SUBNET_SCORES_FILE))
    if not scores or "top_subnets" not in scores:
        config.log("WARN: tao_dca_engine — no subnet scores file found")
        return []
    top = scores["top_subnets"]
    config.log(f"tao_dca_engine — loaded {len(top)} scored subnets from {SUBNET_SCORES_FILE.name}")
    return top


# ---------------------------------------------------------------------------
# btcli execution
# ---------------------------------------------------------------------------

def run_btcli_stake(amount: float, netuid: int, simulate: bool = False) -> tuple[bool, str]:
    """
    Run: btcli stake add --wallet-name tao_main --hotkey staker
                         --amount X --netuid Y --no-prompt --unsafe

    Wallet coldkey is stored unencrypted — no password prompt needed.
    --unsafe skips rate tolerance check so automation is never blocked by slippage.

    Returns (success, output_str).
    """
    cmd = [
        "btcli", "stake", "add",
        "--wallet-name", WALLET_NAME,
        "--hotkey",      HOTKEY_NAME,
        "--amount",      f"{amount:.6f}",
        "--netuid",      str(netuid),
        "--no-prompt",
        "--unsafe",
    ]
    cmd_str = " ".join(cmd)

    if simulate:
        print(f"  [SIMULATE] {cmd_str}")
        config.log(f"[SIMULATE] btcli: {cmd_str}")
        return True, "[simulated]"

    config.log(f"tao_dca_engine — executing: {cmd_str}")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = (result.stdout + result.stderr).strip()
        success = result.returncode == 0

        if success:
            config.log(f"tao_dca_engine — btcli SUCCESS netuid={netuid} amount={amount:.6f}")
        else:
            config.log(f"tao_dca_engine — btcli FAILED netuid={netuid} rc={result.returncode}")
        config.log(f"  btcli output: {output[:400]}")

        return success, output
    except subprocess.TimeoutExpired:
        config.log(f"ERROR: btcli timed out for netuid={netuid}")
        return False, "timeout"
    except Exception as e:
        config.log(f"ERROR: btcli subprocess error: {e}")
        return False, str(e)


# ---------------------------------------------------------------------------
# Core entry execution
# ---------------------------------------------------------------------------

def execute_entry(entry_number: int, tao_amount: float, tao_price: float, simulate: bool = False) -> bool:
    """
    Execute one DCA entry.
      entry_number : 1-5
      tao_amount   : TAO to deploy this entry
      tao_price    : current TAO/USD price
      simulate     : if True, print btcli commands but don't run them
    """
    root_amount   = round(tao_amount * (ROOT_STAKE_PCT   / 100), 6)
    subnet_amount = round(tao_amount * (SUBNET_STAKE_PCT / 100), 6)
    usd_value     = round(tao_amount * tao_price, 2)

    config.log(
        f"tao_dca_engine — ENTRY {entry_number}/{TOTAL_DCA_ENTRIES}: "
        f"total={tao_amount:.6f} TAO (${usd_value:.2f}) | "
        f"root={root_amount:.6f} TAO | subnet={subnet_amount:.6f} TAO"
    )

    # --- Load subnet allocation ---
    top_subnets = load_subnet_scores()
    if not top_subnets:
        config.log("WARN: tao_dca_engine — no subnet scores available, skipping subnet allocation")
        subnet_stakes = []
    else:
        subnet_stakes = []
        for sn in top_subnets:
            alloc_pct  = sn["alloc_pct"] / 100.0
            sn_amount  = round(subnet_amount * alloc_pct, 6)
            if sn_amount < 0.0001:
                config.log(f"  Skipping SN{sn['netuid']} — amount {sn_amount:.6f} TAO too small")
                continue
            subnet_stakes.append({
                "netuid":   sn["netuid"],
                "name":     sn["name"],
                "amount":   sn_amount,
                "alloc_pct": sn["alloc_pct"],
                "score":    sn.get("score", 0),
            })

    # --- Print execution plan ---
    print()
    print(f"{'='*60}")
    print(f"DCA ENTRY {entry_number}/{TOTAL_DCA_ENTRIES}  —  {'SIMULATE' if simulate else 'LIVE'}")
    print(f"{'='*60}")
    print(f"  Total:         {tao_amount:.6f} TAO  (${usd_value:.2f} @ ${tao_price:.2f})")
    print(f"  Root stake:    {root_amount:.6f} TAO  (netuid 0)")
    if subnet_stakes:
        print(f"  Subnet total:  {subnet_amount:.6f} TAO across {len(subnet_stakes)} subnets")
        for sn in subnet_stakes:
            print(f"    SN{sn['netuid']:3d} {sn['name']:<20} {sn['amount']:.6f} TAO  ({sn['alloc_pct']:.1f}%)")
    else:
        print("  Subnet stakes: NONE (no scored subnets available)")
    print()
    print("  btcli commands to execute:")

    # --- Execute / simulate ---
    entry_results = []
    all_ok = True

    # 1. Root stake
    ok, out = run_btcli_stake(root_amount, netuid=0, simulate=simulate)
    entry_results.append({"netuid": 0, "name": "Root", "amount": root_amount, "success": ok, "output": out[:200]})
    if not ok:
        config.log(f"ERROR: root stake failed — aborting entry {entry_number}")
        all_ok = False
        if not simulate:
            return False

    # 2. Subnet stakes
    for sn in subnet_stakes:
        ok, out = run_btcli_stake(sn["amount"], netuid=sn["netuid"], simulate=simulate)
        entry_results.append({
            "netuid":  sn["netuid"],
            "name":    sn["name"],
            "amount":  sn["amount"],
            "success": ok,
            "output":  out[:200],
        })
        if not ok:
            config.log(f"WARN: subnet stake SN{sn['netuid']} failed, continuing")
            all_ok = False

    if simulate:
        print()
        print("  [SIMULATE complete — no transactions submitted]")
        return True

    # --- Update state ---
    return all_ok, entry_results, root_amount, subnet_stakes, usd_value


def update_state_and_portfolio(
    state: dict,
    entry_number: int,
    tao_amount: float,
    tao_price: float,
    root_amount: float,
    subnet_stakes: list,
    usd_value: float,
    entry_results: list,
):
    now = datetime.now(timezone.utc).isoformat()

    entry_record = {
        "entry_number": entry_number,
        "executed_at":  now,
        "tao_amount":   tao_amount,
        "usd_value":    usd_value,
        "tao_price":    tao_price,
        "root_staked":  root_amount,
        "subnet_stakes": [
            {"netuid": sn["netuid"], "name": sn["name"], "amount": sn["amount"]}
            for sn in subnet_stakes
        ],
        "results": entry_results,
    }

    state["entries_executed"] += 1
    state["last_entry_time"]   = now
    state["entry_history"].append(entry_record)
    save_state(state)
    config.log(f"tao_dca_engine — state updated: entries_executed={state['entries_executed']}")

    # --- Update portfolio file ---
    portfolio = config.load_json(str(PORTFOLIO_FILE)) or {}

    # Accumulate root staked
    prev_root = portfolio.get("root_staked_tao", 0.0)
    new_root  = round(prev_root + root_amount, 6)

    # Accumulate subnet positions
    prev_positions = {p["netuid"]: p for p in portfolio.get("subnet_positions", [])}
    for sn in subnet_stakes:
        netuid = sn["netuid"]
        prev   = prev_positions.get(netuid, {"netuid": netuid, "name": sn["name"], "staked_tao": 0.0, "cost_basis_usd": 0.0, "score": sn.get("score", 0)})
        prev["staked_tao"]    = round(prev["staked_tao"] + sn["amount"], 6)
        prev["cost_basis_usd"] = round(prev["cost_basis_usd"] + sn["amount"] * tao_price, 2)
        prev["score"]          = sn.get("score", prev.get("score", 0))
        prev_positions[netuid] = prev

    total_invested_tao = sum(e["tao_amount"] for e in state["entry_history"])
    total_invested_usd = sum(e["usd_value"]  for e in state["entry_history"])

    portfolio.update({
        "updated":             now,
        "tao_price_usd":       tao_price,
        "root_staked_tao":     new_root,
        "subnet_positions":    list(prev_positions.values()),
        "total_invested_tao":  round(total_invested_tao, 6),
        "total_invested_usd":  round(total_invested_usd, 2),
        "dca_entries_used":    state["entries_executed"],
        "dca_entries_remaining": TOTAL_DCA_ENTRIES - state["entries_executed"],
    })

    PORTFOLIO_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.save_json(str(PORTFOLIO_FILE), portfolio)
    config.log(f"tao_dca_engine — portfolio updated: {PORTFOLIO_FILE}")


def send_entry_alert(entry_number: int, tao_amount: float, tao_price: float, root_amount: float, subnet_stakes: list, usd_value: float, entries_remaining: int):
    lines = [
        f"🟢 <b>TAO DCA ENTRY {entry_number}/{TOTAL_DCA_ENTRIES}</b>",
        f"TAO Price: <b>${tao_price:,.2f}</b>",
        f"Deployed: <b>{tao_amount:.4f} TAO</b> (${usd_value:.2f})",
        f"Root Staked: {root_amount:.4f} TAO",
    ]
    if subnet_stakes:
        lines.append("Subnets:")
        for sn in subnet_stakes:
            lines.append(f"  SN{sn['netuid']} {sn['name']}: {sn['amount']:.4f} TAO ({sn['alloc_pct']:.0f}%)")
    entries_remaining_after = entries_remaining - 1
    lines.append(f"Entries remaining: {entries_remaining_after}/{TOTAL_DCA_ENTRIES}")
    if entries_remaining_after > 0:
        lines.append(f"Next entry: {DCA_COOLDOWN_HOURS}h cooldown + price must be {DCA_DIP_THRESHOLD_PCT}%+ below 7d MA")
    else:
        lines.append("All entries complete — DCA fully deployed!")

    config.send_telegram("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    config.log("=== DCA Engine Start ===")
    if SIMULATE:
        config.log("tao_dca_engine — SIMULATE mode: commands printed, not executed")
        print("\n[SIMULATE MODE — no real transactions]\n")

    # --- Get current price ---
    tao_price = config.get_tao_price_usd()
    if not tao_price:
        config.log("WARN: could not fetch TAO price, trying price history")
        ph = config.load_json(str(PRICE_HISTORY_FILE))
        tao_price = ph.get("latest_price", 0.0)
    if not tao_price:
        config.log("ERROR: TAO price unavailable, cannot proceed")
        sys.exit(1)
    config.log(f"tao_dca_engine — TAO price: ${tao_price:.2f}")

    # --- Get wallet balance ---
    try:
        sub    = config.get_subtensor()
        wallet = config.get_wallet()
        bal    = sub.get_balance(address=wallet.coldkeypub.ss58_address)
        wallet_balance = float(bal.tao) if bal else 0.0
    except Exception as e:
        config.log(f"WARN: could not fetch wallet balance: {e}, using 0")
        wallet_balance = 0.0
    config.log(f"tao_dca_engine — wallet balance: {wallet_balance:.6f} TAO")

    # --- Load or initialize state ---
    state = load_state()
    if not state:
        state = init_state(wallet_balance)

    entries_executed = state["entries_executed"]
    entries_planned  = state["total_entries_planned"]
    tao_per_entry    = state["tao_per_entry"]

    config.log(
        f"tao_dca_engine — state: {entries_executed}/{entries_planned} entries done, "
        f"{tao_per_entry:.6f} TAO per entry"
    )

    # --- Check if all entries done ---
    if entries_executed >= entries_planned:
        config.log("tao_dca_engine — all entries complete, nothing to do")
        print("\nAll DCA entries complete. Nothing to execute.")
        sys.exit(0)

    # --- Entry 1: execute immediately ---
    if entries_executed == 0:
        config.log("tao_dca_engine — Entry 1: executing immediately (initial deployment)")
        print("\n[Entry 1 of 5 — Immediate execution, no conditions required]")
    else:
        # --- Entries 2-5: check conditions ---
        cooldown_ok, hours_elapsed = check_cooldown(state)
        dip_ok, current_price, ma7, dip_pct = check_price_dip()
        tao_price = current_price if current_price else tao_price  # use freshest price

        print(f"\n[Entry {entries_executed + 1} of {entries_planned} — checking conditions]")
        print(f"  Cooldown:   {hours_elapsed:.1f}h elapsed / {DCA_COOLDOWN_HOURS}h required  →  {'✓ PASS' if cooldown_ok else '✗ FAIL'}")
        print(f"  Price dip:  ${tao_price:.2f} vs 7d MA ${ma7:.2f} ({dip_pct:+.2f}%)  →  {'✓ PASS' if dip_ok else '✗ FAIL (need {:.1f}%+ dip)'.format(DCA_DIP_THRESHOLD_PCT)}")

        if not cooldown_ok:
            hours_remaining = DCA_COOLDOWN_HOURS - hours_elapsed
            config.log(f"tao_dca_engine — cooldown not met, {hours_remaining:.1f}h remaining")
            print(f"\nNot executing. Wait {hours_remaining:.1f}h more for cooldown.")
            sys.exit(0)

        if not dip_ok:
            needed = ma7 * (1 - DCA_DIP_THRESHOLD_PCT / 100)
            config.log(
                f"tao_dca_engine — price dip not met: "
                f"${tao_price:.2f} needs to reach ${needed:.2f} (7d MA ${ma7:.2f})"
            )
            print(f"\nNot executing. TAO needs to drop to ${needed:.2f} (currently ${tao_price:.2f}).")
            sys.exit(0)

    # --- All conditions met → execute ---
    entry_number = entries_executed + 1

    if SIMULATE:
        # Simulate: show commands and exit
        execute_entry(entry_number, tao_per_entry, tao_price, simulate=True)
        print("\n[End of simulate — no state changes written]")
        sys.exit(0)

    # Live execution
    result = execute_entry(entry_number, tao_per_entry, tao_price, simulate=False)
    if result is True:
        # Returned True means simulate path (shouldn't reach here in live)
        sys.exit(0)

    exec_ok, entry_results, root_amount, subnet_stakes, usd_value = result

    # Update state and portfolio
    update_state_and_portfolio(
        state, entry_number, tao_per_entry, tao_price,
        root_amount, subnet_stakes, usd_value, entry_results
    )

    # Send Telegram alert
    entries_remaining = entries_planned - state["entries_executed"]
    send_entry_alert(
        entry_number, tao_per_entry, tao_price,
        root_amount, subnet_stakes, usd_value,
        entries_remaining + 1  # pass pre-decrement count
    )

    status = "SUCCESS" if exec_ok else "PARTIAL (some stakes failed — check tao.log)"
    config.log(f"tao_dca_engine — Entry {entry_number} complete: {status}")
    print(f"\nEntry {entry_number}/{entries_planned} complete: {status}")
    print(f"Entries remaining: {entries_remaining}/{entries_planned}")

    config.log("=== DCA Engine Complete ===")
