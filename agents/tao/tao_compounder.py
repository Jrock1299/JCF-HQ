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
sys.path.insert(0, "/root/.openclaw/scripts")
from tao_config import (
    TaoConfig, DATA_DIR, TOTAL_DCA_ENTRIES, DCA_DIP_THRESHOLD_PCT,
)
from data_freshness import from_file, call_failed, contradicted, banner, summarize

config = TaoConfig()

PORTFOLIO_FILE     = Path("/root/.openclaw/dashboard/tao_portfolio.json")
DCA_STATE_FILE     = DATA_DIR / "tao_dca_state.json"
SUBNET_SCORES_FILE = DATA_DIR / "tao_subnet_scores.json"
SCORE_HISTORY_FILE = DATA_DIR / "tao_score_history.json"
PRICE_HISTORY_FILE = DATA_DIR / "tao_price_history.json"
SUBNET_DATA_FILE   = DATA_DIR / "tao_subnet_data.json"
WALLET_STATE_FILE  = DATA_DIR / "tao_wallet_state.json"

LOW_SCORE_WARN     = 40   # warn if held subnet drops below this
HIGH_SCORE_ADD     = 70   # suggest adding if new subnet scores this
CONSEC_WEEKS_WARN  = 2    # weeks below LOW_SCORE_WARN before suggesting exit

# The collector writes 3x/day and the scorer daily, so anything older than a
# few days means the pipeline is broken — not merely quiet. Kept at 7d so a
# single failed run doesn't cry wolf, but the months-long bittensor 10.2.0
# outage is impossible to miss.
STALE_AFTER_DAYS   = 7


# ---------------------------------------------------------------------------
# Source freshness
#
# Every one of these files is written by the data collector, which has been
# broken since the bittensor 10.2.0 API drift. The SDK migration is parked —
# this does NOT fix the collector, it just makes the breakage visible instead
# of letting April data render as current.
# ---------------------------------------------------------------------------

def assess_sources() -> dict:
    """Freshness of every file feeding the weekly report."""
    return {
        "portfolio":     from_file(PORTFOLIO_FILE,     STALE_AFTER_DAYS, ts_fields=("updated",)),
        "wallet_state":  from_file(WALLET_STATE_FILE,  STALE_AFTER_DAYS, ts_fields=("last_updated",)),
        "dca_state":     from_file(DCA_STATE_FILE,     STALE_AFTER_DAYS, ts_fields=("last_entry_time",)),
        "subnet_data":   from_file(SUBNET_DATA_FILE,   STALE_AFTER_DAYS),
        "subnet_scores": from_file(SUBNET_SCORES_FILE, STALE_AFTER_DAYS, ts_fields=("scored_at",)),
        "score_history": from_file(SCORE_HISTORY_FILE, STALE_AFTER_DAYS),
        "price_history": from_file(PRICE_HISTORY_FILE, STALE_AFTER_DAYS, ts_fields=("last_updated",)),
    }


# ---------------------------------------------------------------------------
# Emissions check
# ---------------------------------------------------------------------------

def _recorded_root_stake() -> float:
    """Root stake this wallet's own DCA history says was staked.

    Used only as a contradiction check against the live chain query — never as
    a substitute for it. If the chain says nothing and this says something, we
    report 'unverified', not either number.
    """
    dca = config.load_json(str(DCA_STATE_FILE)) or {}
    return sum(
        float(e.get("root_staked", 0) or 0)
        for e in dca.get("entry_history", [])
        if isinstance(e, dict)
    )


def check_emissions(portfolio: dict, portfolio_freshness=None) -> tuple[float, float, object]:
    """
    Compare on-chain root stake to last stored value → estimate weekly emissions.
    Root emissions compound automatically on-chain.

    Returns (current_root_tao, estimated_emissions_tao, freshness).

    The third element is the whole point. This call has been failing since the
    bittensor 10.2.0 drift, and the previous version returned `stored_root`
    bare — so an April snapshot rendered as a live number with no indicator.
    On failure the fallback value still comes back (callers need something to
    print) but it arrives tagged, and the report marks it.
    """
    stored_root = portfolio.get("root_staked_tao", 0.0)
    stored_as_of = portfolio.get("updated")
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

        # An EMPTY response is not the same as a verified zero.
        #
        # Under the bittensor 10.2.0 drift this query returns [] for a coldkey
        # whose own DCA history records root stake being funded. We cannot tell
        # "genuinely unstaked" from "this accessor no longer returns what it
        # used to" without the parked SDK migration — so we refuse to publish
        # 0.000000 as fact when recorded history disagrees.
        recorded_root = _recorded_root_stake()
        if not stake_info and recorded_root > 0:
            config.log(
                f"WARN: compounder — chain returned NO stake positions, but DCA "
                f"history records {recorded_root:.6f} τ staked to root. Reporting "
                f"root stake as UNVERIFIED rather than 0."
            )
            return (
                current_root,
                0.0,
                contradicted(
                    "on-chain root stake (get_stake_info_for_coldkey)",
                    f"chain returned 0 stake positions; DCA history records "
                    f"{recorded_root:.6f} τ staked to root. Cannot distinguish a real "
                    f"unstake from bittensor 10.2.0 accessor drift without the parked "
                    f"SDK migration.",
                    stale_after_days=STALE_AFTER_DAYS,
                ),
            )

        emissions = max(0.0, current_root - stored_root)
        config.log(
            f"compounder — root: stored={stored_root:.6f} τ "
            f"current={current_root:.6f} τ  emissions≈{emissions:.6f} τ"
        )
        fresh = from_file(PORTFOLIO_FILE, STALE_AFTER_DAYS, ts_fields=("updated",))
        # Live call succeeded AND returned positions — value is live regardless
        # of how old the portfolio file on disk is.
        fresh.ok, fresh.reason, fresh.basis = True, "fresh", "live_chain_query"
        return current_root, emissions, fresh
    except Exception as e:
        config.log(f"WARN: compounder — emissions check FAILED (value below is STALE): {e}")
        return (
            stored_root,
            0.0,
            call_failed("on-chain root stake (get_stake_info_for_coldkey)", e,
                        fallback_as_of=stored_as_of,
                        stale_after_days=STALE_AFTER_DAYS),
        )


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
                    emissions: float, tao_price: float,
                    sources: dict, root_freshness=None) -> str:
    now      = datetime.now(timezone.utc)
    date_str = now.strftime("%b %-d, %Y")

    pf_fresh    = sources.get("portfolio")
    dca_fresh   = sources.get("dca_state")
    score_fresh = sources.get("subnet_scores")

    def mark(fr) -> str:
        return f"  {fr.marker()}" if fr is not None and fr.stale else ""

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

    lines = [f"📊 TAO WEEKLY REPORT | {date_str}"]

    # Freshness banner first — a reader must know the report is partly historical
    # BEFORE reading any number in it.
    warn = banner(sources, "SOURCE DATA NOT CURRENT")
    if warn:
        lines += ["", warn,
                  "   Cause: data collector down (bittensor 10.2.0 API drift; SDK migration parked).",
                  "   Numbers marked ⚠️ below are last-known values, NOT current.", ""]

    lines += [
        f"Portfolio Value: {total_tao:.4f} τ (${total_usd:,.2f}){mark(pf_fresh)}",
        f"Cost Basis: {cost_tao:.3f} τ (${cost_usd:,.2f}){mark(pf_fresh)}",
        f"Total Return: {ret_sign}{ret_pct:.1f}%{mark(pf_fresh)}",
        f"",
    ]

    # Root stake gets its own treatment: when the chain response is
    # contradicted, printing "0.000000 τ" is worse than printing nothing —
    # it reads as a verified zero. Say what we actually know instead.
    if root_freshness is not None and root_freshness.reason == "contradicted":
        lines += [
            f"Root Stake: {root_freshness.marker()}",
            f"   Chain returned no stake positions; DCA history records "
            f"{_recorded_root_stake():.6f} τ staked to root.",
            f"   Treat as unknown, not zero. Emissions cannot be computed.",
        ]
    else:
        lines.append(
            f"Root Stake: {current_root:.6f} τ "
            f"(+{emissions:.6f} τ emissions this week){mark(root_freshness)}"
        )

    lines += [
        f"",
        f"Subnet Positions:{mark(pf_fresh)}",
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
    if positions and pf_fresh is not None and pf_fresh.stale:
        lines.append(
            f"  ↑ {len(positions)} position(s) above are an "
            f"{pf_fresh.as_of_str()} snapshot — current on-chain set may differ."
        )

    # Score changes
    sc = analysis.get("score_changes", [])
    if sc:
        lines += ["", f"Score Changes:{mark(score_fresh)}"]
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

    # Derive the next-entry line from actual state. This was previously the
    # hardcoded string "Entry 2 triggers when..." which contradicted the
    # "Entry 5/5 used" line printed directly above it — two numbers, one of
    # them a literal, disagreeing inside the same report.
    executed = dca_state.get("entries_executed") if dca_state else None
    planned  = dca_state.get("total_entries_planned", TOTAL_DCA_ENTRIES) if dca_state else TOTAL_DCA_ENTRIES
    if executed is None:
        next_line = "Next: DCA state unavailable — cannot determine next entry."
    elif executed >= planned:
        next_line = (
            f"Next: All {planned} DCA entries executed — no further entries pending. "
            f"Monitoring only."
        )
    else:
        next_line = (
            f"Next: Entry {executed + 1} of {planned} triggers when TAO drops "
            f"{DCA_DIP_THRESHOLD_PCT:.0f}%+ below the 7d MA."
        )
    if dca_fresh is not None and dca_fresh.stale:
        next_line += f"  {dca_fresh.marker()}"

    lines += [
        "",
        f"DCA Status: Entry {dca_used}/{planned} used | "
        f"{rem_tao:.3f} τ remaining{mark(dca_fresh)}",
        f"Profit Tiers: {tier_summary}{mark(pf_fresh)}",
        next_line,
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dashboard sync
# ---------------------------------------------------------------------------

def sync_dashboard(portfolio: dict, current_root: float,
                   analysis: dict, tao_price: float, sources: dict = None,
                   root_freshness=None):
    # Only advance root_staked_tao when the chain query actually succeeded.
    # Writing the fallback back over itself is harmless arithmetically but it
    # launders a stale number into looking like a fresh write.
    if root_freshness is None or root_freshness.ok:
        portfolio["root_staked_tao"] = current_root
    portfolio["tao_price_usd"]      = tao_price   # CoinGecko — independent of the chain
    portfolio["last_weekly_report"] = datetime.now(timezone.utc).isoformat()

    cs = analysis.get("current_scores", {})
    for pos in portfolio.get("subnet_positions", []):
        if pos["netuid"] in cs:
            pos["score"] = cs[pos["netuid"]].get("score", pos.get("score", 0))

    # Publish provenance so the dashboard can render the same warnings the
    # Telegram report carries, instead of re-deriving freshness from mtime.
    if sources:
        portfolio["_freshness"] = summarize(sources)

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

    sources = assess_sources()
    stale   = [k for k, v in sources.items() if v.stale]
    if stale:
        config.log(
            f"compounder — {len(stale)}/{len(sources)} sources STALE: {', '.join(sorted(stale))}"
        )
        for label in sorted(stale):
            config.log(f"compounder —   {label}: {sources[label].marker()}")
    else:
        config.log("compounder — all sources fresh")

    current_root, emissions, root_freshness = check_emissions(portfolio, sources.get("portfolio"))
    sources["root_stake_live"] = root_freshness
    analysis                   = analyze_scores(portfolio)

    warnings    = analysis.get("warnings", [])
    suggestions = analysis.get("suggestions", [])

    if warnings:
        config.log(f"compounder — {len(warnings)} score warning(s)")
    if suggestions:
        config.log(f"compounder — {len(suggestions)} add suggestion(s)")

    report = generate_report(portfolio, analysis, current_root, emissions, tao_price,
                             sources, root_freshness)

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

    sync_dashboard(portfolio, current_root, analysis, tao_price, sources, root_freshness)

    config.log("=== Tao Compounder Complete ===")


if __name__ == "__main__":
    main()
