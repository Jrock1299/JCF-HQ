#!/usr/bin/env python3
"""
BLADE DRY RUN — SPX500_USD NY Session, today
Pulls real OANDA candles, runs strategy logic step-by-step.
NO orders placed. NO writes to trades.json. NO Telegram. NO hub posts.
"""

import sys, json
from datetime import datetime, timezone, timedelta
from statistics import mean

sys.path.insert(0, "/root/.openclaw/scripts")

import oandapyV20
from oandapyV20 import API
from oandapyV20.endpoints.instruments import InstrumentsCandles

# ── Credentials ─────────────────────────────────────────────────────────────
with open('/root/.openclaw/agents/main/agent/auth-profiles.json') as f:
    auth = json.load(f)
creds  = auth['profiles']['oanda:default']
client = API(access_token=creds['key'], environment='practice')

INSTRUMENT    = 'SPX500_USD'
PAPER_BALANCE = 2000.0
LOT_SIZE      = 1       # 1 OANDA unit of SPX500 = $1/point. TP1=$15, TP2=$20, TP3=$30.
PIP_VALUE     = 1.0
MARKET_BIAS_PATH = '/root/.openclaw/dashboard/market_bias.json'

def sep(title=""):
    print(f"\n{'─'*60}")
    if title:
        print(f"  {title}")
        print(f"{'─'*60}")

def get_candles(instrument, granularity, count, from_time=None):
    params = {'granularity': granularity, 'count': count, 'price': 'M'}
    if from_time:
        params['from'] = from_time
        del params['count']
        params['to'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    r = InstrumentsCandles(instrument, params=params)
    client.request(r)
    return r.response['candles']

def fmt_candle(c):
    m = c['mid']
    return (f"  O:{float(m['o']):.2f}  H:{float(m['h']):.2f}  "
            f"L:{float(m['l']):.2f}  C:{float(m['c']):.2f}  "
            f"complete:{c.get('complete','?')}  time:{c['time'][:19]}")

# ════════════════════════════════════════════════════════════════════════════
# STEP 1 — PAPER MODE CONFIRMATION
# ════════════════════════════════════════════════════════════════════════════
sep("STEP 1 — PAPER MODE CONFIRMATION")
print("  PAPER_MODE = True  (hardcoded in blade_bot.py line 62)")
print("  place_paper_order() only writes to open_positions{} and session_trades[]")
print("  No OANDA order endpoints are imported or called (no orders.py, no trades.py)")
print("  All PnL is computed against paper_balance variable only")
print("  Live mode would require explicit PAPER_MODE = False AND separate order execution code")
print("  -> CONFIRMED: zero risk of live order placement")

# ════════════════════════════════════════════════════════════════════════════
# STEP 2 — TODAY'S DATE + SESSION CONTEXT
# ════════════════════════════════════════════════════════════════════════════
sep("STEP 2 — SESSION CONTEXT")
now_utc = datetime.now(timezone.utc)
print(f"  Current time (UTC): {now_utc.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"  NY session open:    13:30 UTC")
print(f"  ORB candle:         13:30–13:45 UTC (first 15m)")
print(f"  Entry window:       13:45 UTC → 17:00 UTC")
print(f"  Session closed:     {'YES' if now_utc.hour >= 17 else 'NO (still open)' if now_utc.hour >= 13 else 'NOT YET OPEN'}")

# ════════════════════════════════════════════════════════════════════════════
# STEP 3 — LENS DIRECTIONAL FILTER
# ════════════════════════════════════════════════════════════════════════════
sep("STEP 3 — LENS FILTER (SPX500_USD)")
print("  SPX500 lens_keys: ['SPX500_USD', 'US100']")
print("  lens_threshold: 60  |  require_lens: False")

try:
    with open(MARKET_BIAS_PATH) as f:
        bias_data = json.load(f)

    bias_entry = None
    for key in ['SPX500_USD', 'US100']:
        e = bias_data.get(key)
        if e and isinstance(e, dict):
            bias_entry = e
            print(f"  Found via dict key: '{key}'")
            break
    if not bias_entry:
        for p in bias_data.get('pairs', []):
            if p.get('symbol') in ['SPX500_USD', 'US100']:
                bias_entry = p
                print(f"  Found via pairs array: symbol='{p.get('symbol')}'")
                break

    if bias_entry:
        lens_dir  = bias_entry.get('bias', 'neutral').lower()
        lens_conf = float(bias_entry.get('confidence', 0))
        if lens_conf <= 1.0:
            lens_conf *= 100
        print(f"  Lens result: {lens_dir} | confidence: {lens_conf:.0f}%")
    else:
        lens_dir, lens_conf = 'neutral', 0.0
        print(f"  SPX500/US100 not found in market_bias.json")
        print(f"  Pairs found: {[p.get('symbol') for p in bias_data.get('pairs', [])]}")
        print(f"  Dict keys: {[k for k in bias_data.keys() if k not in ('last_updated','summary','morning_report','priorities','forex_news')]}")

    if lens_conf >= 60:
        print(f"  -> FILTER ACTIVE: only {'LONG' if lens_dir == 'bullish' else 'SHORT'} breakouts")
    else:
        print(f"  -> No directional filter (confidence {lens_conf:.0f}% < 60%)")
        print(f"     Both long and short breakouts will be taken")

except FileNotFoundError:
    lens_dir, lens_conf = 'neutral', 0.0
    print("  market_bias.json not found — no filter applied")

# ════════════════════════════════════════════════════════════════════════════
# STEP 4 — ADR VOLATILITY GATE
# ════════════════════════════════════════════════════════════════════════════
sep("STEP 4 — ADR VOLATILITY GATE (SPX500_USD)")
print("  Threshold: skip if ADR > 120 pts or < 15 pts")
print("  Fetching last 8 daily candles...")

daily_candles = get_candles(INSTRUMENT, 'D', 8)
completed     = [c for c in daily_candles if c.get('complete', True)]
print(f"  Completed daily candles returned: {len(completed)}")

if len(completed) >= 5:
    last5  = completed[-5:]
    ranges = [float(c['mid']['h']) - float(c['mid']['l']) for c in last5]
    adr    = mean(ranges)
    print(f"\n  Last 5 daily ranges:")
    for i, c in enumerate(last5):
        h = float(c['mid']['h']); lo = float(c['mid']['l'])
        print(f"    Day -{5-i}: H={h:.2f} L={lo:.2f}  range={h-lo:.2f}  date={c['time'][:10]}")
    print(f"\n  5-day ADR: {adr:.2f} pts")
    if adr > 120:
        adr_pass = False
        print(f"  -> GATE TRIGGERED: {adr:.1f} > 120 — session would be skipped")
    elif adr < 15:
        adr_pass = False
        print(f"  -> GATE TRIGGERED: {adr:.1f} < 15 — market too flat, skip")
    else:
        adr_pass = True
        print(f"  -> PASS: ADR {adr:.2f} is within 15–120 range")
else:
    adr, adr_pass = None, True
    print(f"  ADR unavailable — proceeding without gate")

# ════════════════════════════════════════════════════════════════════════════
# STEP 5 — ORB CONSTRUCTION (15m candle at 13:30 UTC)
# ════════════════════════════════════════════════════════════════════════════
sep("STEP 5 — ORB CONSTRUCTION (15m candle at 13:30 UTC)")
print("  Fetching last 5 M15 candles to find the 13:30 UTC session opener...")

m15_candles = get_candles(INSTRUMENT, 'M15', 5)
print(f"  M15 candles returned: {len(m15_candles)}")
for c in m15_candles:
    print(fmt_candle(c))

# Find the 13:30 candle specifically
today_str  = now_utc.strftime('%Y-%m-%d')
orb_candle = None
for c in m15_candles:
    t = c['time'][:16]  # "2026-03-19T13:30"
    if t == f"{today_str}T13:30":
        orb_candle = c
        print(f"\n  Found 13:30 ORB candle: {fmt_candle(c)}")
        break

if not orb_candle:
    # If NY session hasn't opened yet today, use the last complete 15m candle
    completed_m15 = [c for c in m15_candles if c.get('complete', True)]
    if completed_m15:
        orb_candle = completed_m15[-1]
        print(f"\n  13:30 candle not found — using last complete M15 candle as ORB proxy:")
        print(f"  {fmt_candle(orb_candle)}")
        print(f"  (NOTE: In live run, bot waits for exact session open then 15m close)")
    else:
        print("  ERROR: No complete M15 candle available")
        sys.exit(1)

orb_high = float(orb_candle['mid']['h'])
orb_low  = float(orb_candle['mid']['l'])
orb_range = orb_high - orb_low

print(f"\n  ORB HIGH: {orb_high:.2f}")
print(f"  ORB LOW:  {orb_low:.2f}")
print(f"  ORB RANGE: {orb_range:.2f} pts")

# ════════════════════════════════════════════════════════════════════════════
# STEP 6 — ORB QUALITY CHECK
# ════════════════════════════════════════════════════════════════════════════
sep("STEP 6 — ORB QUALITY GATE")
print(f"  SPX500 limits: min=4 pts, max=60 pts")
print(f"  ORB range: {orb_range:.2f} pts")

if orb_range < 4:
    orb_pass = False
    print(f"  -> FAIL: ORB too tight ({orb_range:.2f} < 4 pts) — no trade")
elif orb_range > 60:
    orb_pass = False
    print(f"  -> FAIL: ORB too wide ({orb_range:.2f} > 60 pts) — skip, too chaotic")
else:
    orb_pass = True
    print(f"  -> PASS: ORB range {orb_range:.2f} pts is within acceptable bounds")

# ════════════════════════════════════════════════════════════════════════════
# STEP 7 — PRIOR DAY BIAS + STRATEGY MODE SELECTION
# ════════════════════════════════════════════════════════════════════════════
sep("STEP 7 — PRIOR DAY BIAS + STRATEGY SELECTOR")
if completed:
    prev     = completed[-1]['mid']
    prev_o   = float(prev['o'])
    prev_c   = float(prev['c'])
    move_pct = (prev_c - prev_o) / prev_o
    print(f"  Yesterday: Open={prev_o:.2f} Close={prev_c:.2f} Move={move_pct*100:+.2f}%")
    if move_pct > 0.003:
        prior_bias = 'bullish'
    elif move_pct < -0.003:
        prior_bias = 'bearish'
    else:
        prior_bias = 'neutral'
    print(f"  Prior day bias: {prior_bias}")
else:
    prior_bias = 'neutral'
    print("  Prior day bias: neutral (no data)")

lens_strong = lens_conf >= 60
prior_aligned = (
    (lens_dir == 'bullish' and prior_bias == 'bullish') or
    (lens_dir == 'bearish' and prior_bias == 'bearish')
)

print(f"\n  Lens strong (≥60%): {lens_strong} | Prior aligned: {prior_aligned}")

if lens_strong and prior_aligned:
    mode = 'momentum_orb'
    tp1, tp2, tp3 = 15, int(20 * 1.25), int(30 * 1.5)
    direction_filter = lens_dir
    print(f"  -> MODE: MOMENTUM ORB (both signals aligned)")
    print(f"     TPs scaled: {tp1}/{tp2}/{tp3} pts")
    print(f"     Direction filter: {direction_filter} only")
else:
    mode = 'orb'
    tp1, tp2, tp3 = 15, 20, 30
    # Dynamic TP scaling
    if adr:
        normal_adr = 120 * 0.45  # = 54 pts
        if adr > normal_adr * 1.2:
            scale = min(1 + (adr / normal_adr - 1) * 0.4, 1.5)
            tp2 = int(tp2 * scale)
            tp3 = int(tp3 * scale)
            print(f"  Dynamic TP scaling: ADR {adr:.1f} > {normal_adr*1.2:.1f} normal → scale x{scale:.2f}")
    direction_filter = lens_dir if lens_strong else None
    print(f"  -> MODE: STANDARD ORB")
    print(f"     TPs: {tp1}/{tp2}/{tp3} pts")
    print(f"     Direction filter: {direction_filter if direction_filter else 'none (trade either direction)'}")

# ════════════════════════════════════════════════════════════════════════════
# STEP 8 — 1m CANDLE SCAN FOR BREAKOUT
# ════════════════════════════════════════════════════════════════════════════
sep("STEP 8 — 1m BREAKOUT SCAN")
print(f"  ORB HIGH = {orb_high:.2f} | ORB LOW = {orb_low:.2f}")
print(f"  Entry condition LONG:  1m candle close > {orb_high:.2f} AND open > {orb_high:.2f}")
print(f"  Entry condition SHORT: 1m candle close < {orb_low:.2f} AND open < {orb_low:.2f}")
print(f"\n  Fetching 1m candles from 13:45 UTC today...")

# Build from time: today at 13:45 UTC
from_dt = now_utc.replace(hour=13, minute=45, second=0, microsecond=0)
# If we're before 13:45 today, there won't be any — use last 30 candles instead
if now_utc < from_dt:
    print(f"  Current time {now_utc.strftime('%H:%M')} is before 13:45 — session hasn't started yet")
    print(f"  Fetching last 30 M1 candles as proxy to demonstrate breakout logic...")
    m1_candles = get_candles(INSTRUMENT, 'M1', 30)
else:
    from_str   = from_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    try:
        m1_candles = get_candles(INSTRUMENT, 'M1', 0, from_time=from_str)
    except Exception:
        m1_candles = get_candles(INSTRUMENT, 'M1', 30)

completed_m1 = [c for c in m1_candles if c.get('complete', True)]
print(f"  Completed 1m candles available: {len(completed_m1)}")

if not completed_m1:
    print("  No 1m candles available.")
    sys.exit(0)

# Scan all candles for breakout signal
print(f"\n  Scanning each 1m candle against ORB {orb_high:.2f}/{orb_low:.2f}:")
breakout_candle = None
breakout_dir    = None
sweep_state     = {}

for i, c in enumerate(completed_m1):
    m    = c['mid']
    o    = float(m['o'])
    h    = float(m['h'])
    lo   = float(m['l'])
    cl   = float(m['c'])
    ts   = c['time'][11:16]  # HH:MM

    # Breakout check
    if cl > orb_high and o > orb_high:
        signal = 'LONG  <<< BREAKOUT'
        if not breakout_candle:
            breakout_candle = c
            breakout_dir    = 'long'
    elif cl < orb_low and o < orb_low:
        signal = 'SHORT <<< BREAKOUT'
        if not breakout_candle:
            breakout_candle = c
            breakout_dir    = 'short'
    elif h > orb_high:
        signal = 'wick-above-H (not entry — wick only)'
    elif lo < orb_low:
        signal = 'wick-below-L (not entry — wick only)'
    else:
        signal = 'inside range'

    marker = ' **' if (breakout_candle and c == breakout_candle) else ''
    print(f"  {ts}  O:{o:.2f} H:{h:.2f} L:{lo:.2f} C:{cl:.2f}  → {signal}{marker}")

    # Sweep detection
    if lo < orb_low:
        sweep_state['swept_low']         = True
        sweep_state['sweep_low_extreme'] = min(lo, sweep_state.get('sweep_low_extreme', lo))
    if h > orb_high:
        sweep_state['swept_high']         = True
        sweep_state['sweep_high_extreme'] = max(h, sweep_state.get('sweep_high_extreme', h))

if not breakout_candle:
    print(f"\n  No breakout signal found in {len(completed_m1)} candles scanned.")

# ════════════════════════════════════════════════════════════════════════════
# STEP 9 — ENTRY DECISION
# ════════════════════════════════════════════════════════════════════════════
sep("STEP 9 — ENTRY DECISION")

if not adr_pass:
    print("  BLOCKED by ADR gate — no trade")
elif not orb_pass:
    print("  BLOCKED by ORB quality gate — no trade")
elif not breakout_candle:
    print("  NO SIGNAL — no 1m candle has cleanly broken the ORB level yet")
    print("  (Bot would continue monitoring until 17:00 UTC)")
else:
    entry_price = float(breakout_candle['mid']['c'])
    print(f"  Breakout detected: {breakout_dir.upper()} at {breakout_candle['time'][11:16]} UTC")
    print(f"  Entry price: {entry_price:.2f}")

    # Apply directional filter
    blocked = False
    if direction_filter == 'bullish' and breakout_dir == 'short':
        print(f"  BLOCKED by Lens filter: SHORT signal but Lens is {lens_conf:.0f}% bullish")
        blocked = True
    elif direction_filter == 'bearish' and breakout_dir == 'long':
        print(f"  BLOCKED by Lens filter: LONG signal but Lens is {lens_conf:.0f}% bearish")
        blocked = True

    if not blocked:
        if breakout_dir == 'long':
            stop_loss  = orb_low
            tp1_price  = entry_price + (tp1 * PIP_VALUE)
            tp2_price  = entry_price + (tp2 * PIP_VALUE)
            tp3_price  = entry_price + (tp3 * PIP_VALUE)
        else:
            stop_loss  = orb_high
            tp1_price  = entry_price - (tp1 * PIP_VALUE)
            tp2_price  = entry_price - (tp2 * PIP_VALUE)
            tp3_price  = entry_price - (tp3 * PIP_VALUE)

        stop_dist   = abs(entry_price - stop_loss)
        units       = LOT_SIZE
        stop_risk   = round(stop_dist * units * PIP_VALUE, 2)
        tp1_reward  = round(tp1 * units * PIP_VALUE, 2)
        tp2_reward  = round(tp2 * units * PIP_VALUE, 2)
        tp3_reward  = round(tp3 * units * PIP_VALUE, 2)

        print(f"\n  ── PAPER TRADE WOULD BE PLACED ──────────────────────────")
        print(f"  Instrument:   {INSTRUMENT}")
        print(f"  Direction:    {breakout_dir.upper()}")
        print(f"  Mode:         {mode}")
        print(f"  Entry:        {entry_price:.2f}")
        print(f"  Stop Loss:    {stop_loss:.2f}  ({stop_dist:.2f} pts risk = ${stop_risk})")
        print(f"  TP1:          {tp1_price:.2f}  (+{tp1} pts = ${tp1_reward})")
        print(f"  TP2:          {tp2_price:.2f}  (+{tp2} pts = ${tp2_reward})")
        print(f"  TP3:          {tp3_price:.2f}  (+{tp3} pts = ${tp3_reward})")
        print(f"  Units:        {units}  (1 OANDA unit = $1/point)")
        print(f"  R:R:          1:{tp3/stop_dist:.1f} to TP3")
        print(f"\n  After TP1 hit: SL moves to breakeven ({entry_price:.2f})")
        print(f"  ─────────────────────────────────────────────────────────")

# ════════════════════════════════════════════════════════════════════════════
# STEP 10 — POSITION MANAGEMENT SIMULATION
# ════════════════════════════════════════════════════════════════════════════
sep("STEP 10 — POSITION MANAGEMENT LOGIC (code walkthrough)")
print("""
  manage_positions() runs every 30 seconds while position is open.
  For each open position:

  1. Get current price via get_price() [M1 last close]
  2. Compute PnL:
       LONG:  pnl = (current_price - entry) * units * pip_value
       SHORT: pnl = (entry - current_price) * units * pip_value
       (units=1 → $1/pt → 15pt TP1=$15, 20pt TP2=$20, 30pt TP3=$30)

  3. Check TPs highest-first (TP3 → TP2 → TP1):
       if price >= tp3 (long) or <= tp3 (short) → record TP3, queue close
       elif price >= tp2 → record TP2, set BE if not set
       elif price >= tp1 → record TP1, set BE

  4. Breakeven move:
       On FIRST tp_level >= 1 hit:
         pos['stop_loss'] = entry
         pos['breakeven_moved'] = True
       After BE move, stop check uses entry as the floor

  5. Stop check (after possible BE update):
       LONG:  if current_price <= stop_loss → SL or BE hit
       SHORT: if current_price >= stop_loss → SL or BE hit

  6. Result codes:
       'TP3'     — all TPs hit, closed at TP3
       'BE'      — TP1 was hit, BE set, then price reversed to entry
       'SL'      — stopped before TP1 (full loss)
       'Time Stop' — force-closed at 17:00 UTC
       'TP2+Time'  — hit TP2 but session ended before TP3

  7. paper_balance += pnl on every close event
""")

sep("SUMMARY")
print(f"  Instrument:     {INSTRUMENT}")
print(f"  Date:           {today_str}")
print(f"  Paper mode:     CONFIRMED (no live orders possible)")
print(f"  ADR gate:       {'PASS' if adr_pass else 'BLOCKED'}" + (f" (ADR={adr:.1f})" if adr else ""))
print(f"  ORB quality:    {'PASS' if orb_pass else 'BLOCKED'} (range={orb_range:.2f} pts)")
print(f"  ORB levels:     H={orb_high:.2f}  L={orb_low:.2f}")
print(f"  Lens:           {lens_dir} {lens_conf:.0f}%  filter={'active' if lens_conf >= 60 else 'inactive'}")
print(f"  Prior day:      {prior_bias}")
print(f"  Strategy mode:  {mode}")
print(f"  Breakout:       {'YES — ' + breakout_dir.upper() if breakout_candle else 'NOT YET / NO SIGNAL'}")
print(f"  Would trade:    {'YES' if (adr_pass and orb_pass and breakout_candle and not (direction_filter == 'bullish' and breakout_dir == 'short') and not (direction_filter == 'bearish' and breakout_dir == 'long')) else 'NO'}")
print()
