"""
Tao Compounder — Phase 3
Runs weekly Saturday 08:00 UTC.
Checks root emissions, re-scores subnets, sends weekly report to Telegram.
Suggests (but does NOT auto-execute) rebalancing moves — Jase makes the call.

Usage:
  python3 tao_compounder.py
"""

import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))
from tao_config import TaoConfig, DATA_DIR

config = TaoConfig()

PORTFOLIO_FILE     = Path("/root/.openclaw/dashboard/tao_portfolio.json")
DCA_STATE_FILE     = DATA_DIR / "tao_dca_state.json"
SUBNET_SCORES_FILE = DATA_DIR / "tao_subnet_scores.json"
SCORE_HISTORY_FILE = DATA_DIR / "tao_score_history.json"
PRICE_HISTORY_FILE = DATA_DIR / "tao_price_history.json"

LOW_SCORE_WARN     = 40   # warn if held subnet drops below this
HIGH_SCORE_ADD     = 70   # suggest adding if new subnet scores this
CONSEC_WEEKS_WARN  = 2    # weeks below LOW_SCORE_WARN before suggesting exit


# ---------------------------------------------------------------------------
# Emissions check
# ---------------------------------------------------------------------------

def check_emissions(portfolio: dict) -> tuple[float, float]:
    """
    Compare on-chain root stake to last stored value → estimate weekly emissions.
    Root emissions compound automatically on-chain.
    Returns (current_root_tao, estimated_emissions_tao).
    """
    stored_root = portfolio.get("root_staked_tao", 0.0)
    try:
        sub          = config.get_subtensor()
        wallet       = config.get_wallet()
        coldkey_ss58 = wallet.coldkeypub.ss58_address

        stake_info   = sub.get_stake_info_for_coldkey(coldkey_ss58=coldkey_ss58)
        current_root = 0.0
        if stake_info:
            for s in stake_info:
                if getattr(s, "netuid", -1) == 0:
                    current_root += float(s.stake.tao) if hasattr(s, "stake") else 0.0

        emissions = max(0.0, current_root - stored_root)
        config.log(
            f"compounder — root: stored={stored_root:.6f} τ "
            f"current={current_root:.6f} τ  emissions≈{emissions:.6f} τ"
        )
        return current_root, emissions
    except Exception as e:
        config.log(f"WARN: compounder — emissions check failed: {e}")
        return stored_root, 0.0


# ---------------------------------------------------------------------------
# Score tracking + analysis
# ---------------------------------------------------------------------------

def load_score_history() -> dict:
    return config.load_json(str(SCORE_HISTORY_FILE)) or {"weeks": []}


def analyze_scores(portfolio: dict) -> dict:
    """
    Load latest scores, compare to held positions, update score history.
    Returns dict with: score_changes, warnings, suggestions, current_scores.
    """
    scores_data = config.load_json(str(SUBNET_SCORES_FILE))
    history     = load_score_history()

    top_subnets    = scores_data.get("top_subnets", []) if scores_data else []
    current_scores = {s["netuid"]: s for s in top_subnets}

    held_netuids = {p["netuid"] for p in portfolio.get("subnet_positions", [])}

    # --- Update weekly score history ---
    now          = datetime.now(timezone.utc)
    year, week, _ = now.isocalendar()
    week_key     = f"{year}-W{week:02d}"
    weeks        = history.get("weeks", [])

    if not any(w.get("week_key") == week_key for w in weeks):
        weeks.append({
            "week_key": week_key,
            "date": now.date().isoformat(),
            "scores": {str(s["netuid"]): s.get("score", 0) for s in top_subnets},
        })
        weeks = weeks[-12:]
        history["weeks"] = weeks
        config.save_json(str(SCORE_HISTORY_FILE), history)

    # --- Score changes for held positions ---
    score_changes = []
    warnings      = []

    for pos in portfolio.get("subnet_positions", []):
        netuid       = pos["netuid"]
        name         = pos.get("name", f"SN{netuid}")
        stored_score = pos.get("score", 0)
        cur_data     = current_scores.get(netuid, {})
        cur_score    = cur_data.get("score", 0)

        if stored_score and cur_score:
            delta = round(cur_score - stored_score, 1)
            score_changes.append({
                "netuid":    netuid,
                "name":      name,
                "old_score": stored_score,
                "new_score": cur_score,
                "change":    delta,
                "direction": "↑" if delta > 0 else ("↓" if delta < 0 else "→"),
            })

        if cur_score:
            pos["score"] = cur_score  # update in-place for portfolio sync

        # Warn if current score is low
        if 0 < cur_score < LOW_SCORE_WARN:
            low_count = sum(
                1 for w in weeks
                if w.get("scores", {}).get(str(netuid), 100) < LOW_SCORE_WARN
            )
            warnings.append({
                "netuid":       netuid,
                "name":         name,
                "score":        cur_score,
                "consec_weeks": low_count,
                "suggest_exit": low_count >= CONSEC_WEEKS_WARN,
            })

    # --- Suggestions: new top scorers not in portfolio ---
    suggestions = []
    for sn in top_subnets:
        if sn["netuid"] in held_netuids:
            continue
        score = sn.get("score", 0)
        if score >= HIGH_SCORE_ADD:
            high_count = sum(
                1 for w in weeks
                if w.get("scores", {}).get(str(sn["netuid"]), 0) >= HIGH_SCORE_ADD
            )
            if high_count >= CONSEC_WEEKS_WARN:
                suggestions.append({
                    "netuid":       sn["netuid"],
                    "name":         sn.get("name", f"SN{sn['netuid']}"),
                    "score":        score,
                    "consec_weeks": high_count,
                })

    return {
        "score_changes":   score_changes,
        "warnings":        warnings,
        "suggestions":     suggestions,
        "current_scores":  current_scores,
    }


# ---------------------------------------------------------------------------
# Weekly report
# ---------------------------------------------------------------------------

def generate_report(portfolio: dict, analysis: dict, current_root: float,
                    emissions: float, tao_price: float) -> str:
    now      = datetime.now(timezone.utc)
    date_str = now.strftime("%b %-d, %Y")

    # Totals
    positions   = portfolio.get("subnet_positions", [])
    subnet_tao  = sum(p.get("current_value_tao", p.get("staked_tao", 0)) for p in positions)
    total_tao   = current_root + subnet_tao
    total_usd   = total_tao * tao_price

    cost_tao    = portfolio.get("total_invested_tao", 0.0)
    cost_usd    = portfolio.get("total_invested_usd", 0.0)
    ret_pct     = (total_tao - cost_tao) / cost_tao * 100 if cost_tao > 0 else 0.0
    ret_sign    = "+" if ret_pct >= 0 else ""

    # DCA state
    dca_state   = config.load_json(str(DCA_STATE_FILE))
    dca_used    = portfolio.get("dca_entries_used", 1)
    dca_rem     = portfolio.get("dca_entries_remaining", 4)
    per_entry   = dca_state.get("tao_per_entry", 0.0) if dca_state else 0.0
    rem_tao     = round(per_entry * dca_rem, 4)

    lines = [
        f"📊 TAO WEEKLY REPORT | {date_str}",
        f"Portfolio Value: {total_tao:.4f} τ (${total_usd:,.2f})",
        f"Cost Basis: {cost_tao:.3f} τ (${cost_usd:,.2f})",
        f"Total Return: {ret_sign}{ret_pct:.1f}%",
        f"",
        f"Root Stake: {current_root:.6f} τ (+{emissions:.6f} τ emissions this week)",
        f"",
        f"Subnet Positions:",
    ]

    for pos in positions:
        cur   = pos.get("current_value_tao", pos.get("staked_tao", 0))
        cost  = pos.get("staked_tao", 0)
        pnl   = pos.get("pnl_pct", ((cur - cost) / cost * 100 if cost > 0 else 0))
        sign  = "+" if pnl >= 0 else ""
        tiers = pos.get("tiers_hit", [])
        tier_tag = f" [T{''.join(str(t) for t in tiers)}]" if tiers else ""
        lines.append(
            f"SN{pos['netuid']} {pos.get('name','')}: "
            f"{cur:.4f} τ ({sign}{pnl:.1f}%){tier_tag}"
        )

    # Score changes
    sc = analysis.get("score_changes", [])
    if sc:
        lines += ["", "Score Changes:"]
        for c in sc:
            lines.append(
                f"SN{c['netuid']} {c['name']}: "
                f"{c['old_score']:.1f} → {c['new_score']:.1f} ({c['direction']})"
            )

    # Warnings & suggestions (brief in main report)
    for w in analysis.get("warnings", []):
        lines.append(
            f"\n⚠️  SN{w['netuid']} {w['name']} score={w['score']:.1f} "
            f"(below {LOW_SCORE_WARN} for {w['consec_weeks']} wk)"
            + (" — consider exit" if w["suggest_exit"] else "")
        )
    for s in analysis.get("suggestions", []):
        lines.append(
            f"\n🔭 SN{s['netuid']} {s['name']} score={s['score']:.1f} "
            f"({s['consec_weeks']} strong weeks) — consider adding"
        )

    # Footer
    tiers_triggered = [p for p in positions if p.get("tiers_hit")]
    tier_summary = (
        ", ".join(f"SN{p['netuid']} T{p['tiers_hit']}" for p in tiers_triggered)
        if tiers_triggered else "None triggered yet"
    )

    lines += [
        "",
        f"DCA Status: Entry {dca_used}/5 used | {rem_tao:.3f} τ remaining",
        f"Profit Tiers: {tier_summary}",
        f"Next: Monitoring continues. Entry 2 triggers when TAO drops 2%+ below 7d MA.",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dashboard sync
# ---------------------------------------------------------------------------

def sync_dashboard(portfolio: dict, current_root: float,
                   analysis: dict, tao_price: float):
    portfolio["root_staked_tao"]      = current_root
    portfolio["tao_price_usd"]        = tao_price
    portfolio["last_weekly_report"]   = datetime.now(timezone.utc).isoformat()

    cs = analysis.get("current_scores", {})
    for pos in portfolio.get("subnet_positions", []):
        if pos["netuid"] in cs:
            pos["score"] = cs[pos["netuid"]].get("score", pos.get("score", 0))

    config.save_json(str(PORTFOLIO_FILE), portfolio)
    config.log("compounder — dashboard synced")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    config.log("=== Tao Compounder Start ===")

    portfolio = config.load_json(str(PORTFOLIO_FILE))
    if not portfolio:
        config.log("ERROR: compounder — no portfolio file")
        sys.exit(1)

    tao_price = config.get_tao_price_usd() or portfolio.get("tao_price_usd", 0.0)
    config.log(f"compounder — TAO price: ${tao_price:.2f}")

    current_root, emissions = check_emissions(portfolio)
    analysis                = analyze_scores(portfolio)

    warnings    = analysis.get("warnings", [])
    suggestions = analysis.get("suggestions", [])

    if warnings:
        config.log(f"compounder — {len(warnings)} score warning(s)")
    if suggestions:
        config.log(f"compounder — {len(suggestions)} add suggestion(s)")

    report = generate_report(portfolio, analysis, current_root, emissions, tao_price)

    print("\n" + "=" * 65)
    print("WEEKLY REPORT")
    print("=" * 65)
    print(report)
    print("=" * 65 + "\n")

    config.send_telegram(report)
    config.log("compounder — weekly report sent via Telegram")

    # Separate alert for each exit warning
    for w in warnings:
        if w["suggest_exit"]:
            config.send_telegram(
                f"⚠️ TAO EXIT SUGGESTION\n"
                f"SN{w['netuid']} {w['name']} score={w['score']:.1f} "
                f"below {LOW_SCORE_WARN} for {w['consec_weeks']} consecutive weeks\n"
                f"→ Consider unstaking. Your call, Jase."
            )

    # Separate alert for each strong new subnet
    for s in suggestions:
        config.send_telegram(
            f"🔭 TAO NEW OPPORTUNITY\n"
            f"SN{s['netuid']} {s['name']} scored {s['score']:.1f} "
            f"for {s['consec_weeks']}+ weeks\n"
            f"→ Consider adding to portfolio. Your call, Jase."
        )

    sync_dashboard(portfolio, current_root, analysis, tao_price)

    config.log("=== Tao Compounder Complete ===")


if __name__ == "__main__":
    main()
