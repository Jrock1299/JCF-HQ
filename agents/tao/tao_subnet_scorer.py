"""
Tao Subnet Scorer — Phase 2
Scores active subnets for TAO allocation based on emission, TVL, volume, network size.
Runs daily at 06:00 UTC. Writes tao_subnet_scores.json.

Scoring factors (all normalized 0-100):
  Emission Share  25%  pending_alpha_emission relative to all subnets
  Subnet TVL      30%  tao_in (TAO liquidity in pool)
  Volume          25%  subnet_volume (alpha token trading activity)
  Network Size    20%  num_uids (registered miners + validators)

Data: single bulk call to sub.get_all_metagraphs_info()
"""

import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))
from tao_config import TaoConfig, DATA_DIR, MIN_SUBNET_SCORE

config = TaoConfig()

SUBNET_SCORES_FILE = DATA_DIR / "tao_subnet_scores.json"
MAX_TOP_SUBNETS = 7

# Fallback names for well-known subnets
KNOWN_SUBNETS = {
    0: "Root", 1: "Apex", 2: "DSperse", 3: "Templar", 4: "Targon",
    8: "Taoshi", 19: "Nineteen", 51: "Lium", 55: "Precog", 62: "Ridges",
    64: "Chutes", 68: "Nova", 75: "Hippius",
}


def normalize(values: list) -> list:
    """Normalize values to 0–100 scale (min-max). Returns 50s if all equal."""
    min_val = min(values)
    max_val = max(values)
    if max_val == min_val:
        return [50.0] * len(values)
    span = max_val - min_val
    return [(v - min_val) / span * 100.0 for v in values]


def score_subnets() -> dict:
    config.log("tao_subnet_scorer — connecting to subtensor (finney)")
    sub = config.get_subtensor()

    config.log("tao_subnet_scorer — fetching all metagraph info (bulk call)")
    metagraphs = sub.get_all_metagraphs_info()
    config.log(f"tao_subnet_scorer — received {len(metagraphs)} subnets from chain")

    # --- Parse raw metrics ---
    records = []
    for mg in metagraphs:
        netuid = mg.netuid

        if netuid == 0:
            continue  # Skip root — it's handled separately in DCA (always 50%)

        try:
            pending_emission = float(mg.pending_alpha_emission) if mg.pending_alpha_emission else 0.0
            tao_in          = float(mg.tao_in) if mg.tao_in else 0.0
            volume          = float(mg.subnet_volume) if mg.subnet_volume else 0.0
            num_uids        = int(mg.num_uids) if mg.num_uids else 0

            # Skip subnets with no meaningful liquidity (probably just registered)
            if tao_in < 500:
                continue

            # Resolve name: try MetagraphInfo.name, fall back to KNOWN_SUBNETS, then SN{netuid}
            name = getattr(mg, "name", None) or ""
            if not name or name.lower() in ("", "none"):
                name = KNOWN_SUBNETS.get(netuid, f"SN{netuid}")

            records.append({
                "netuid":           netuid,
                "name":             name,
                "pending_emission": pending_emission,
                "tao_in":           tao_in,
                "volume":           volume,
                "num_uids":         num_uids,
            })
        except Exception as e:
            config.log(f"WARN: tao_subnet_scorer — error parsing netuid {getattr(mg, 'netuid', '?')}: {e}")

    config.log(f"tao_subnet_scorer — {len(records)} subnets pass liquidity filter (tao_in >= 500)")

    if not records:
        config.log("ERROR: tao_subnet_scorer — no valid subnets found, aborting")
        return {}

    # --- Normalize each factor ---
    norm_emission = normalize([r["pending_emission"] for r in records])
    norm_tao_in   = normalize([r["tao_in"]           for r in records])
    norm_volume   = normalize([r["volume"]            for r in records])
    norm_uids     = normalize([r["num_uids"]          for r in records])

    # --- Compute weighted composite score ---
    total_emission = sum(r["pending_emission"] for r in records)
    for i, r in enumerate(records):
        r["score"] = round(
            norm_emission[i] * 0.25 +
            norm_tao_in[i]   * 0.30 +
            norm_volume[i]   * 0.25 +
            norm_uids[i]     * 0.20,
            1
        )
        r["emission_share_pct"] = round(
            r["pending_emission"] / total_emission * 100, 2
        ) if total_emission > 0 else 0.0

    # --- Sort descending, filter by min score, cap at 7 ---
    records.sort(key=lambda x: x["score"], reverse=True)
    top = [r for r in records if r["score"] >= MIN_SUBNET_SCORE][:MAX_TOP_SUBNETS]

    if not top:
        config.log(f"WARN: tao_subnet_scorer — no subnet scored >= {MIN_SUBNET_SCORE}, using top 3")
        top = records[:3]

    # --- Allocation percentages proportional to score ---
    total_score = sum(r["score"] for r in top)
    for r in top:
        r["alloc_pct"] = round(r["score"] / total_score * 100, 1)

    # Fix rounding so alloc_pct sums exactly to 100.0
    alloc_sum = round(sum(r["alloc_pct"] for r in top), 1)
    if alloc_sum != 100.0 and top:
        top[-1]["alloc_pct"] = round(top[-1]["alloc_pct"] + (100.0 - alloc_sum), 1)

    # --- Build and save output ---
    now = datetime.now(timezone.utc).isoformat()
    result = {
        "scored_at":              now,
        "total_subnets_analyzed": len(records),
        "top_subnets": [
            {
                "netuid":          r["netuid"],
                "name":            r["name"],
                "score":           r["score"],
                "alloc_pct":       r["alloc_pct"],
                "total_stake_tao": round(r["tao_in"], 2),
                "emission_share":  r["emission_share_pct"],
                "pending_emission": round(r["pending_emission"], 4),
                "volume":          round(r["volume"], 2),
                "num_uids":        r["num_uids"],
            }
            for r in top
        ],
        "notes": (
            f"Top {len(top)} subnets selected (min score {MIN_SUBNET_SCORE}). "
            f"Factors: Emission 25%, TVL 30%, Volume 25%, Network Size 20%. "
            f"Excluded: root(0) and subnets with tao_in < 500."
        ),
    }

    config.save_json(str(SUBNET_SCORES_FILE), result)
    config.log(f"tao_subnet_scorer — saved {len(top)} top subnets to {SUBNET_SCORES_FILE.name}")
    config.log("-" * 60)
    for r in top:
        config.log(
            f"  SN{r['netuid']:3d} {r['name']:<20} "
            f"score={r['score']:5.1f}  alloc={r['alloc_pct']:5.1f}%  "
            f"tao_in={r['tao_in']:>12,.0f}  emit={r['pending_emission']:.2f}  "
            f"vol={r['volume']:.0f}  uids={r['num_uids']}"
        )
    config.log("-" * 60)

    return result


if __name__ == "__main__":
    config.log("=== Subnet Scorer Start ===")
    result = score_subnets()

    if result:
        top = result.get("top_subnets", [])
        print()
        print("=" * 70)
        print(f"SUBNET SCORES  —  {result['scored_at']}")
        print(f"Analyzed {result['total_subnets_analyzed']} active subnets (tao_in >= 500)")
        print("=" * 70)
        print(f"{'#':>3}  {'Netuid':>6}  {'Name':<20}  {'Score':>7}  {'Alloc%':>7}  {'TAO_in':>14}  {'Emit':>8}  {'UIDs':>5}")
        print("-" * 70)
        for i, r in enumerate(top, 1):
            print(
                f"{i:>3}  {r['netuid']:>6}  {r['name']:<20}  "
                f"{r['score']:>7.1f}  {r['alloc_pct']:>7.1f}  "
                f"{r['total_stake_tao']:>14,.0f}  "
                f"{r['pending_emission']:>8.2f}  "
                f"{r['num_uids']:>5}"
            )
        print("=" * 70)
        print(f"Notes: {result['notes']}")
        print()
        import json
        print("JSON output written to:")
        print(f"  {SUBNET_SCORES_FILE}")
        print()
        print(json.dumps(result, indent=2))

    config.log("=== Subnet Scorer Complete ===")
