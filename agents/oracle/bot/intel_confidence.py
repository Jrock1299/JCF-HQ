#!/usr/bin/env python3
"""
intel_confidence.py — Layer 5: Confidence scoring & tiering.
Combines EV + all context edge signals into a single confidence score.
Determines pick tier and adjusts Kelly sizing accordingly.
"""

# Signal weights (sum to 1.0)
WEIGHTS = {
    'ev':            0.40,
    'injury':        0.25,
    'rest':          0.15,
    'weather':       0.10,
    'line_movement': 0.10,
}

# Tier thresholds
TIER_HIGH   = 0.7
TIER_MEDIUM = 0.4
TIER_LOW    = 0.2
# Below TIER_LOW → SKIP

# Tier bankroll caps (% of bankroll)
TIER_CAPS = {
    'HIGH':   0.030,   # up to 3.0%
    'MEDIUM': 0.015,   # up to 1.5%
    'LOW':    0.0075,  # up to 0.75%
    'SKIP':   0.0,
}

# Kelly multipliers by tier
TIER_KELLY_MULT = {
    'HIGH':   1.0,
    'MEDIUM': 0.5,
    'LOW':    0.25,
    'SKIP':   0.0,
}


def calc_confidence(
    raw_ev_pct:          float,
    injury_edge:         float,
    rest_edge:           float,
    weather_edge:        float,
    line_movement_edge:  float,
) -> tuple[float, str]:
    """
    Compute a confidence score from all signals.

    raw_ev_pct:  EV as a percentage (e.g. 4.2 for 4.2%).
                 Internally normalized: 5%+ EV → 1.0 signal strength.

    All edge values: -1.0 to 1.0.

    Returns: (confidence_score: float, tier: str)
    """
    # Normalize EV to [-1, 1]: 5% EV = 1.0, 0% = 0.0, negative EV = negative
    ev_signal = max(-1.0, min(1.0, raw_ev_pct / 5.0))

    score = (
        ev_signal           * WEIGHTS['ev'] +
        injury_edge         * WEIGHTS['injury'] +
        rest_edge           * WEIGHTS['rest'] +
        weather_edge        * WEIGHTS['weather'] +
        line_movement_edge  * WEIGHTS['line_movement']
    )

    score = round(max(-0.5, min(1.0, score)), 3)

    if score >= TIER_HIGH:
        tier = 'HIGH'
    elif score >= TIER_MEDIUM:
        tier = 'MEDIUM'
    elif score >= TIER_LOW:
        tier = 'LOW'
    else:
        tier = 'SKIP'

    return score, tier


def get_kelly_sizing(
    confidence_tier: str,
    base_kelly_full_pct: float,
    bankroll: float,
) -> tuple[float, float]:
    """
    Compute adjusted kelly_pct and suggested_bet based on confidence tier.

    base_kelly_full_pct: full-Kelly percentage (before fractional reduction, e.g. 8.5).
    bankroll: current bankroll in dollars.

    Returns: (final_kelly_pct: float, suggested_bet: float)
    """
    mult = TIER_KELLY_MULT.get(confidence_tier, 0.0)
    cap  = TIER_CAPS.get(confidence_tier, 0.0)

    if mult == 0.0 or cap == 0.0:
        return 0.0, 0.0

    # Apply Kelly fraction (0.25) then tier multiplier
    kelly_frac = 0.25
    adjusted_pct = base_kelly_full_pct * kelly_frac * mult   # as percentage
    cap_pct      = cap * 100                                  # cap as percentage
    final_pct    = min(adjusted_pct, cap_pct)

    suggested_bet = round(bankroll * final_pct / 100, 2)
    suggested_bet = max(5.0, suggested_bet)

    return round(final_pct, 2), suggested_bet


def build_reasoning(
    pick:               dict,
    injury_edge:        float,
    rest_edge:          float,
    weather_edge:       float,
    line_movement_edge: float,
) -> str:
    """
    Build a 1–2 sentence human-readable reasoning string for Telegram / dashboard.
    """
    ev = pick.get('ev', 0)
    sport = pick.get('sport', '')
    parts = [f"EV {ev:+.1f}%"]

    if abs(injury_edge) >= 0.2:
        if injury_edge > 0:
            parts.append("injury edge favors our side")
        else:
            parts.append("injury concerns on our pick")

    if abs(rest_edge) >= 0.2:
        if rest_edge > 0:
            parts.append("rest advantage")
        elif rest_edge < -0.3:
            parts.append("back-to-back fatigue risk")
        else:
            parts.append("slight rest disadvantage")

    if abs(weather_edge) >= 0.2 and sport == 'MLB':
        if weather_edge >= 0.5:
            parts.append("strong wind blowing out")
        elif weather_edge >= 0.2:
            parts.append("mild wind-out conditions")
        elif weather_edge <= -0.5:
            parts.append("wind blowing in + cold weather")
        else:
            parts.append("mild weather suppression")

    if abs(line_movement_edge) >= 0.2:
        if line_movement_edge > 0:
            parts.append("line moved our way (possible sharp action)")
        else:
            parts.append("line drifted against our side")

    # Append notable context flags (first 2 only)
    flags = pick.get('context_flags', [])
    if flags:
        # Strip leading emoji chars for inline readability
        notable = []
        for f in flags[:2]:
            stripped = f.strip()
            # Remove leading emoji cluster (everything before first letter)
            import re
            clean = re.sub(r'^[^\w]+', '', stripped).strip()
            if clean:
                notable.append(clean)
        if notable:
            parts.append(' | '.join(notable))

    return '. '.join(parts) + '.'


if __name__ == '__main__':
    score, tier = calc_confidence(4.5, 0.6, 0.3, 0.8, 0.2)
    print(f'Score: {score} | Tier: {tier}')
    score2, tier2 = calc_confidence(0.5, -0.4, -0.3, 0.0, -0.1)
    print(f'Score: {score2} | Tier: {tier2}')
