#!/usr/bin/env python3
"""ict_strategies.py — ICT + ICC models codified as objective, testable rules.

EVERY term below is defined numerically. There is no "wait for a clean sweep"
or "strong displacement" — a rule that needs a human to interpret it cannot be
backtested, and a backtest of an interpretable rule measures the interpreter,
not the edge.

THE ONE NON-NEGOTIABLE: close[1], never close[0].
    Every confirmation reads the PREVIOUS CLOSED bar. The current bar is still
    forming: its high, low and close all still move, so a rule that reads it is
    reading a value that will change. In a backtest that is lookahead and the
    results are fiction; live it fires entries that un-trigger. Enforced
    structurally — the engine hands each strategy a window ending at the last
    closed bar, and `bars[-1]` IS close[1]. There is no access to close[0].

── DEFINITIONS (shared by all models) ───────────────────────────────────────

  SWING HIGH (index i, lookback k=2)
      high[i] > high[i±1..k]. Symmetric fractal. Confirmed only k bars later,
      so a swing is never known before bar i+k — the engine respects that lag.

  SWING LOW      mirror of the above.

  LIQUIDITY POOL
      The price of the most recent confirmed swing high (buy-side) or swing
      low (sell-side) within LOOKBACK_POOLS bars.

  LIQUIDITY SWEEP (bearish setup / buy-side sweep)
      bar.high > pool_high AND bar.close < pool_high.
      i.e. price traded THROUGH the pool and closed back below it — stops were
      taken and price rejected. A close beyond the pool is a breakout, not a
      sweep, and is explicitly excluded.

  DISPLACEMENT
      A bar whose body (|close-open|) >= DISPLACEMENT_ATR_MULT * ATR(14),
      closing in the direction of the intended trade. This is the objective
      stand-in for "energetic move".

  MARKET STRUCTURE SHIFT (MSS / BOS / CHoCH)
      After a buy-side sweep: close[1] < the most recent confirmed swing low
      that formed BETWEEN the sweep bar and now. Direction reverses for a
      sell-side sweep. This is the confirmation trigger and it reads close[1].

  FAIR VALUE GAP (FVG) — 3-bar imbalance
      Bearish FVG: low[n-2] > high[n]  -> gap zone (high[n], low[n-2])
      Bullish FVG: high[n-2] < low[n]  -> gap zone (high[n-2], low[n])
      Only FVGs created by the displacement leg are eligible for entry.

  ORDER BLOCK (ICT definition)
      The last opposing-direction candle before the displacement leg.
      Bearish OB = last up-close candle before a down displacement.
      Zone = that candle's (open, high) for bearish, (low, open) for bullish.

  INSTITUTIONAL CANDLE (ICC refinement — see ICC section below)
      An order block that ALSO satisfies both:
        (a) volume >= ICC_VOL_MULT * mean(volume, 20)
        (b) range  >= ICC_RANGE_ATR_MULT * ATR(14)
      i.e. the block was formed on genuine participation, not a quiet drift.

  KILLZONE (session filter, UTC)
      London 07:00-10:00, New York 12:00-15:00. ICT's own definitions.
      Silver Bullet uses the narrower NY 15:00-16:00 window.

── WHY EACH MODEL IS TESTED SEPARATELY ──────────────────────────────────────
Jase asked for the named variants as separate models. They are NOT stacked:
each is an independent hypothesis with its own entry logic, so the backtest
attributes edge to one mechanism rather than to a blend whose components
cannot be separated afterwards.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ── Tunables (single surface, so a sensitivity sweep can perturb them) ───────
PARAMS = {
    'SWING_K':                 2,
    'LOOKBACK_POOLS':          50,
    'DISPLACEMENT_ATR_MULT':   1.0,
    'ATR_PERIOD':              14,
    'FVG_MAX_AGE_BARS':        12,      # an unfilled FVG goes stale
    'MSS_MAX_BARS_AFTER_SWEEP': 20,     # sweep must resolve promptly
    'ENTRY_MAX_WAIT_BARS':     12,      # retrace must arrive promptly
    'STOP_BUFFER_ATR':         0.25,    # stop sits beyond the sweep extreme
    'MIN_STOP_ATR':            0.5,     # reject degenerate sub-0.5-ATR stops
    'MIN_RR':                  2.0,     # brief: min 1:2
    'RISK_PCT':                0.0075,  # 0.75% — midpoint of the 0.5-1% band
    'ICC_VOL_MULT':            1.5,
    'ICC_RANGE_ATR_MULT':      1.0,
}

KILLZONES = {
    'LONDON': (7, 10),
    'NY':     (12, 15),
    'NY_SB':  (15, 16),      # Silver Bullet's own hour
}


@dataclass
class StrategySpec:
    """A codified, objective rule set. No discretionary terms."""
    key: str
    name: str
    family: str                     # 'ICT' | 'ICT+ICC'
    hypothesis: str
    entry_zone: str                 # 'FVG' | 'OB' | 'ICC_OB' | 'IFVG'
    require_sweep: bool = True
    require_mss: bool = True
    require_displacement: bool = True
    killzones: tuple = ('LONDON', 'NY')
    htf_bias_required: bool = True
    reverse_on_sweep: bool = False  # Turtle Soup: trade INTO the rejection
    require_amd: bool = False       # Power of Three
    icc_filter: bool = False        # institutional-candle refinement
    notes: str = ''
    rules: list = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
# THE MODELS
# ══════════════════════════════════════════════════════════════════════════════

STRATEGIES: list[StrategySpec] = [

    StrategySpec(
        key='ict_core',
        name='ICT Core (sweep → displacement/MSS → FVG entry)',
        family='ICT',
        hypothesis=('Price sweeps a liquidity pool to fill institutional orders, '
                    'then displaces in the opposite direction. The imbalance left '
                    'by that displacement (FVG) is revisited before continuation.'),
        entry_zone='FVG',
        notes='The base model from the brief, steps 1-8, unmodified.',
        rules=[
            '1. HTF bias: H4 close[1] vs H4 EMA(50) — above = bullish, below = bearish.',
            '2. Sweep: M15 bar takes out a confirmed swing pool and CLOSES back inside it.',
            '3. Displacement: body >= 1.0 x ATR(14), closing in bias direction.',
            '4. MSS: close[1] breaks the intervening swing in bias direction.',
            '5. Entry: limit at the 50% level of the displacement-leg FVG.',
            '6. Stop: beyond the sweep extreme + 0.25 x ATR.',
            '7. Target: next opposing liquidity pool; reject setup if RR < 2.0.',
            '8. Sessions: London 07:00-10:00 and NY 12:00-15:00 UTC only.',
        ],
    ),

    StrategySpec(
        key='silver_bullet',
        name='Silver Bullet (NY 15:00-16:00 killzone FVG)',
        family='ICT',
        hypothesis=('A specific one-hour window concentrates algorithmic '
                    'repricing; an FVG formed inside it is unusually reliable.'),
        entry_zone='FVG',
        killzones=('NY_SB',),
        require_sweep=False,          # the window itself is the setup
        require_mss=False,
        notes='Tests whether the TIME WINDOW alone carries edge, so sweep/MSS '
              'are deliberately relaxed — otherwise it is just ict_core with a '
              'narrower clock and proves nothing about the Silver Bullet claim.',
        rules=[
            '1. Window: NY 15:00-16:00 UTC only.',
            '2. Displacement inside the window creates an FVG.',
            '3. Entry: limit at FVG 50%, in the direction of the displacement.',
            '4. Stop: beyond the displacement leg origin + 0.25 x ATR.',
            '5. Target: next opposing pool; RR >= 2.0.',
        ],
    ),

    StrategySpec(
        key='ifvg',
        name='IFVG (inverse FVG reversal)',
        family='ICT',
        hypothesis=('An FVG that fails — price closes fully through it — flips '
                    'polarity and becomes resistance/support on the retest.'),
        entry_zone='IFVG',
        require_sweep=False,
        notes='Entry is the RETEST of a violated FVG, trading the opposite way '
              'to the gap that failed.',
        rules=[
            '1. Identify an FVG. 2. Price closes fully through it (close[1] beyond '
            'the far edge) — the gap is now inverted.',
            '3. Entry: limit on the retest of the inverted zone.',
            '4. Stop: beyond the zone + 0.25 x ATR. 5. RR >= 2.0.',
            '6. Sessions: London + NY killzones.',
        ],
    ),

    StrategySpec(
        key='turtle_soup',
        name='Turtle Soup (sweep reversal, no MSS wait)',
        family='ICT',
        hypothesis=('The sweep rejection alone is the signal; waiting for MSS '
                    'gives up the best part of the move.'),
        entry_zone='OB',
        require_mss=False,
        require_displacement=False,
        reverse_on_sweep=True,
        notes='Deliberately the impatient sibling of ict_core. Comparing the two '
              'isolates what the MSS confirmation is actually worth.',
        rules=[
            '1. Sweep of a 20-bar extreme that closes back inside.',
            '2. Entry: market on close[1] confirmation of the rejection bar.',
            '3. Stop: beyond the sweep extreme + 0.25 x ATR.',
            '4. Target: opposing pool; RR >= 2.0.',
            '5. Sessions: London + NY killzones.',
        ],
    ),

    StrategySpec(
        key='power_of_three',
        name='Power of Three (Accumulation → Manipulation → Distribution)',
        family='ICT',
        hypothesis=('The session opens with a range (accumulation), fakes one '
                    'way (manipulation), then trends the other (distribution).'),
        entry_zone='FVG',
        require_amd=True,
        notes='AMD is codified as: first 4 M15 bars of the killzone define the '
              'accumulation range; a sweep of that range is the manipulation; '
              'entry is the distribution leg.',
        rules=[
            '1. Accumulation: first 4 M15 bars of the killzone form a range.',
            '2. Manipulation: a later bar sweeps that range and closes back inside.',
            '3. Distribution: displacement away from the swept side.',
            '4. Entry: FVG 50% of the distribution leg.',
            '5. Stop beyond the manipulation extreme + 0.25 x ATR. RR >= 2.0.',
        ],
    ),

    # ── ICC: folded in ALONGSIDE ICT, per the brief ─────────────────────────
    #
    # ICC (institutional concepts / order-flow) is not run as a separate track.
    # It is an ENTRY REFINEMENT inside the ICT structure: same sweep -> MSS
    # skeleton, but the entry zone must be an order block that shows genuine
    # institutional participation (volume + range thresholds) rather than any
    # order block. The pair below is deliberately identical except for that one
    # filter, which is what makes "does ICT+ICC beat ICT alone?" answerable.

    StrategySpec(
        key='ict_ob',
        name='ICT + order-block entry (ICC control)',
        family='ICT',
        hypothesis='Same as ict_core but entering at the order block rather '
                   'than the FVG. This is the CONTROL for the ICC test.',
        entry_zone='OB',
        notes='Exists so the ICC comparison isolates the institutional filter '
              'rather than the FVG-vs-OB choice.',
        rules=['As ict_core, but entry zone = order block (last opposing candle '
               'before displacement), no volume/range filter.'],
    ),

    StrategySpec(
        key='ict_icc',
        name='ICT + ICC (institutional order-block entry)',
        family='ICT+ICC',
        hypothesis=('Order blocks formed on above-average volume AND expanded '
                    'range represent genuine institutional positioning; entries '
                    'refined to those blocks should outperform ICT alone.'),
        entry_zone='ICC_OB',
        icc_filter=True,
        notes='THE combined model. Differs from ict_ob by exactly one condition '
              '(the institutional filter), so any performance delta is '
              'attributable to ICC and nothing else.',
        rules=[
            '1-4. As ict_core (bias, sweep, displacement, MSS).',
            '5. Entry zone = order block that ALSO has volume >= 1.5 x mean(vol,20) '
            'AND range >= 1.0 x ATR(14).',
            '6. Stop beyond sweep extreme + 0.25 x ATR. 7. RR >= 2.0.',
            '8. Sessions: London + NY killzones.',
        ],
    ),
]

BY_KEY = {s.key: s for s in STRATEGIES}


def describe() -> str:
    out = []
    for s in STRATEGIES:
        out.append(f'── {s.key}  [{s.family}]\n   {s.name}\n   {s.hypothesis}')
        for r in s.rules:
            out.append(f'     {r}')
        if s.notes:
            out.append(f'   note: {s.notes}')
        out.append('')
    return '\n'.join(out)


if __name__ == '__main__':
    print(describe())
    print(f'{len(STRATEGIES)} models codified')
    print('\nParams:')
    for k, v in PARAMS.items():
        print(f'  {k:28} {v}')
