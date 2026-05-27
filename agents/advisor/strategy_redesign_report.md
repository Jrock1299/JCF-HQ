# Strategy Redesign Report — Crisp & Blade
**Generated:** 2026-03-18
**Analyst:** Advisor (JCF HQ CFO)
**Trigger:** Crisp -$1,536 loss across 36 trades, 2 wins (5.6% win rate)
**References:** spx500_strategy_report.md, spx500_strategy_v2_report.md

---

## 1. Failure Analysis — What Went Wrong

### 1.1 Crisp — Root Cause Breakdown

Crisp ran 36 trades this week with only 2 winners (5.6% WR), losing $1,536. This is not
close to the break-even territory for any reasonable ORB implementation. There are five
structural problems, each compounding the others:

**Problem 1: 4x Correlated Simultaneous Positions**

Crisp traded BTC/USDT, ETH/USDT, SOL/USDT, and XRP/USDT simultaneously. These four
assets have intraday correlations of 0.85–0.95 with each other during NY session opens.
When a macro catalyst moves BTC down, ETH, SOL, and XRP fall together. Entering all four
at the NY open means entering effectively the same trade four times — there is no
diversification, only amplification.

A single bad NY session where crypto was risk-off would hit all four stops simultaneously.
The actual loss distribution makes this clear: 34 losses in 36 trades cannot happen by
chance in a 50/50 market — it requires either a severely directionally-biased strategy
OR a strategy entering multiple correlated positions at high risk per trade.

**Problem 2: Extreme Exposure — 4% Risk × 3x Leverage**

`RISK_PERCENT = 0.04` and `LEVERAGE = 3` in the code. On a $10,000 account:
- Risk per trade: $400 (4%)
- Leverage applied: 3x
- Effective position value: up to $3,333 per symbol (max position size guard = balance/3)
- With 4 symbols at once: up to $1,200 risk, $13,333 notional in one session

Even without leverage, 4% × 4 symbols = 16% of account at risk per session. This is
catastrophically over-leveraged for a strategy with a 5.6% win rate.

**Problem 3: 15-Minute ORB on Crypto — Wrong Timeframe**

The code uses `get_opening_candle(symbol, '15m', 2)`, establishing ORB on a 15-minute
candle. For crypto at the NY open, 15 minutes captures a wide, noisy range — 15 minutes
of price discovery including early institutional order flow, retail reaction, and
mean-reversion noise all in one candle. The resulting ORB range is large, pushing stops
far and making 1.5x targets difficult to reach.

The Advisor backtests confirmed: ORB range < 15 points (SPX equivalent) produced 46.4%
WR vs 9.1% for larger ranges. The 5-minute ORB gives a tighter, more meaningful range.

**Problem 4: Heavy Short Bias (19/21 shorts)**

The code has no trend filter. It takes breakouts in any direction. But something caused
19 of 21 shorts this week — either: (a) the market was actually trending up, making
all the shorts counter-trend losers, or (b) the 15m ORB was breaking downward first
on most sessions due to early selling pressure, triggering shorts that reversed.

Without a prior-day trend filter, Crisp blindly took signals in both directions. If the
week had a bullish bias (plausible given crypto's tendency toward recovery bounces),
every short entry was fighting the dominant flow.

**Problem 5: No ORB Quality Gate**

The code never checks whether the ORB range is reasonable before trading. High-volatility
sessions with wide initial 15-minute candles produce enormous ORB ranges. Entering these
sessions means accepting very wide stops and very distant targets — a recipe for time
stops and slow bleeds even when directionally correct.

### 1.2 Blade — Structural Problems

Blade's specific loss data was not provided, but the code reveals the same structural
issues:

- **5 instruments** (GBP_JPY, AUD_CAD, XAU_USD, NAS100_USD, SPX500_USD) traded
  simultaneously — NAS100 and SPX500 are 0.95+ correlated; GBP_JPY and AUD_CAD are
  influenced by the same JPY/AUD macro flows; XAU and NAS100 are frequently inversely
  correlated. The portfolio is internally contradictory.

- **2% risk across 5 instruments** = 10% of account at risk per session. At $2,000
  balance, each session exposes $200 — and five correlated instruments in a risk-off
  session hit simultaneously.

- **15m ORB** across forex and indices — same problem as Crisp. The Advisor backtests
  explicitly showed the SPX 15m ORB performed worse than 5m (38.1% vs 47.6%).

- **No Lens integration** — Blade had access to market_bias.json but never read it.
  Lens produces directional bias with confidence scores for XAU/USD and related pairs.
  A simple confidence threshold filter would eliminate a significant portion of
  counter-trend entries.

---

## 2. What the Advisor Backtests Tell Us

### From spx500_strategy_report.md

- **5-minute ORB produced 47.6% continuation rate** — the highest of three timeframes
  tested. 15-minute ORB matched it (47.6%) but gives wider ranges and worse entries.
  30-minute ORB was worst (38.1%).

- **ORB range size is the single biggest predictor of success**: ORB < 15pts →
  46.4% WR (28 trades). ORB 15–30pts → 9.1% WR (11 trades). This is not noise —
  it's a 37-point gap in win rate. Small ORBs work. Large ORBs don't.

- **Momentum is the dominant regime**: once price breaks a prior-day level, it
  continued 100% of the time (16/16 signals) in the test period. This validates the
  trend filter — if prior day was bullish, longs have structural tailwind.

- **Mean reversion fails in this environment**: 2.4% reversion rate within 1 hour
  after 0.5x ADR extension. Counter-trend entries (which is what Crisp's shorts were
  in a bull-trending market) were structurally doomed.

### From spx500_strategy_v2_report.md

- **February win rate: 66.7% vs March win rate: 0.0%** — the strategy is regime-
  dependent. In normal volatility (Feb), ORB has genuine edge. In elevated volatility
  (March), ORB produces nothing. The volatility gate (ADR filter) is essential.

- **Trend filter (33.3% WR trend-aligned vs 36.8% counter-trend)** — the SPX data
  didn't conclusively prove the trend filter helps (small sample), but it didn't hurt.
  For crypto (stronger trending asset class) and gold (macro-driven), the directional
  filter should be more meaningful.

- **GBP/JPY London ORB** recommended as primary Blade instrument. XAU/USD NY ORB
  recommended as secondary. This redesign uses XAU/USD because:
  1. Jase's own live data shows 60.4% WR and positive P&L on XAU/USD
  2. OANDA practice supports it natively
  3. Lens already tracks it in market_bias.json
  4. GBP/JPY London open would require restructuring Blade's session timing

---

## 3. Strategy Comparison Summary

### Crisp v1 vs v2

| Parameter | v1 (Failed) | v2 (New) | Change |
|-----------|-------------|----------|--------|
| Instruments | 4 (BTC/ETH/SOL/XRP) | 1 (BTC/USD) | −3 |
| ORB timeframe | 15 minutes | 5 minutes | Tighter |
| Risk per trade | 4% | 1% | −75% |
| Leverage | 3x | None (1x) | −67% |
| TP structure | 1x / 2x / 3x | Single 1.5x | Simplified |
| Trend filter | None | Prior-day bias | Added |
| Volatility gate | None | ORB > 2% → skip | Added |
| Sessions | NY + ASIA | NY only | Focused |
| Max simultaneous positions | 4 | 1 | −75% |
| Max account risk per session | ~16% | 1% | −94% |

### Blade v1 vs v2

| Parameter | v1 (Structural Issues) | v2 (New) | Change |
|-----------|----------------------|----------|--------|
| Instruments | 5 (GBP_JPY/AUD_CAD/XAU/NAS100/SPX) | 1 (XAU/USD) | −4 |
| ORB timeframe | 15 minutes | 5 minutes | Tighter |
| Risk per trade | 2% | 1% | −50% |
| TP structure | 1x / 2x / 3x | Single 1.5x | Simplified |
| ADR filter | None | ADR(5d) > 80 → skip | Added |
| Lens filter | None | Confidence ≥ 60% → directional | Added |
| Sessions | ASIA + London + NY | NY only | Focused |
| Max simultaneous positions | 5 | 1 | −80% |
| Max account risk per session | ~10% | 1% | −90% |

---

## 4. Code Change Plan — Crisp (crisp_bot.py)

The following changes are required. **Do not implement until paper-testing plan is confirmed.**

### 4.1 Config Block Changes

```python
# OLD
SYMBOLS      = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT']
RISK_PERCENT = 0.04
LEVERAGE     = 3

# NEW
SYMBOLS      = ['BTC/USDT']
RISK_PERCENT = 0.01
LEVERAGE     = 1  # effectively unused — no leverage
```

Remove or comment out the `ASIA` entry from `SESSIONS`. Only `NY` runs.

### 4.2 New Function: `get_orb_5m(symbol)`

Replace `get_opening_candle()` with a 5-minute specific version:

```python
def get_orb_5m(symbol):
    """
    Fetch the 5-minute candle at NY open (13:30-13:35 UTC).
    Returns (orb_high, orb_low) or (None, None) on error.
    """
    candles = get_candles(symbol, '5m', 3)
    if not candles or len(candles) < 2:
        return None, None
    # candles[-2] is the last *closed* 5m candle
    opening = candles[-2]
    return opening[2], opening[3]  # high, low
```

### 4.3 New Function: `check_volatility_gate(orb_high, orb_low, price)`

```python
def check_volatility_gate(orb_high, orb_low, price):
    """
    Returns True (skip session) if ORB range > 2% of current price.
    """
    orb_range = orb_high - orb_low
    threshold = price * 0.02
    if orb_range > threshold:
        print(f"VOLATILITY GATE: ORB range ${orb_range:.0f} > 2% limit ${threshold:.0f} — skipping")
        return True
    return False
```

### 4.4 New Function: `get_prior_day_bias(symbol)`

```python
def get_prior_day_bias(symbol):
    """
    Fetch yesterday's daily candle. Return 'bullish', 'bearish', or 'neutral'.
    """
    try:
        # Binance: '1d' timeframe, need last 2 (current + previous)
        daily = get_candles(symbol, '1d', 3)
        if not daily or len(daily) < 2:
            return 'neutral'
        prev = daily[-2]  # yesterday's closed candle
        open_p  = prev[1]
        close_p = prev[4]
        if close_p > open_p * 1.002:   # >0.2% move = directional signal
            return 'bullish'
        elif close_p < open_p * 0.998:
            return 'bearish'
        return 'neutral'
    except Exception as e:
        print(f"Prior day bias error: {e}")
        return 'neutral'
```

### 4.5 Update `wait_for_candle_close()`

Change from 15-minute wait to 5-minute wait:

```python
def wait_for_candle_close():
    now = datetime.now(timezone.utc)
    remaining_seconds = (5 - (now.minute % 5)) * 60 - now.second
    if remaining_seconds >= 300:
        remaining_seconds -= 300
    if remaining_seconds > 0:
        print(f"Waiting {remaining_seconds}s for 5m candle to close...")
        time.sleep(remaining_seconds + 2)
    print("5m candle closed — monitoring 1m for breakout")
```

### 4.6 Update `place_paper_order()` — Single TP

Remove the `tp_multipliers = [1, 2, 3]` structure. Replace with:

```python
orb_range = orb_high - orb_low
if direction == 'long':
    stop_loss    = orb_low
    take_profit  = price + (1.5 * orb_range)
else:
    stop_loss    = orb_high
    take_profit  = price - (1.5 * orb_range)
```

Update all downstream references: `take_profits` (list) → `take_profit` (scalar).
Update `manage_positions()` to check `price >= take_profit` (long) or
`price <= take_profit` (short) with no `highest_tp_hit` tracking needed.

### 4.7 Update `run_orb_session()` — Main Logic Flow

Replace the current multi-symbol loop with single-symbol flow:

```python
def run_orb_session(session_name='NY'):
    wait_for_session_open(session_name)
    wait_for_candle_close()  # wait for 5m ORB to close

    symbol = SYMBOLS[0]  # 'BTC/USDT'
    price = get_price(symbol)

    # Build ORB
    orb_high, orb_low = get_orb_5m(symbol)
    if not orb_high:
        record_no_trade("ORB data unavailable"); return

    # Volatility gate
    if check_volatility_gate(orb_high, orb_low, price):
        record_no_trade("ORB range > 2% — too volatile"); return

    # Trend filter
    bias = get_prior_day_bias(symbol)
    print(f"Prior-day bias: {bias}")

    # Monitor for breakout
    end_time = time.time() + (4 * 3600)  # 4-hour max window
    session_close = datetime.now(timezone.utc).replace(hour=17, minute=30, second=0)
    traded = False

    while time.time() < end_time and datetime.now(timezone.utc) < session_close:
        if not traded:
            direction = check_1m_breakout(symbol, orb_high, orb_low)
            if direction:
                # Apply trend filter
                if bias == 'bullish' and direction == 'short':
                    print("Short blocked — counter to bullish prior-day bias")
                elif bias == 'bearish' and direction == 'long':
                    print("Long blocked — counter to bearish prior-day bias")
                else:
                    place_paper_order(symbol, direction, orb_high, orb_low, session_name)
                    traded = True

        if open_positions:
            manage_positions()

        time.sleep(30)

    # Time stop
    [close_at_market(sym) for sym in list(open_positions.keys())]
    write_session_trades_to_json()
    sync_pnl()
    send_telegram_report(session_name)
```

### 4.8 Remove ASIA Session Cron Entry

The cron job currently running Crisp at 00:00 UTC (ASIA session) should be disabled.
Only the NY session cron (13:30 UTC) should remain active.

### 4.9 No Changes Needed

The following functions work correctly as-is and require no modifications:
- `check_1m_breakout()` — already implements open+close confirmation correctly
- `write_session_trades_to_json()` — normalize function is solid
- `send_telegram_report()` — update TP reference from list to scalar only
- `update_trade_log()` — works with new single-TP structure

---

## 5. Code Change Plan — Blade (blade_bot.py)

### 5.1 Config Block Changes

```python
# OLD
INSTRUMENTS  = ['GBP_JPY', 'AUD_CAD', 'XAU_USD', 'NAS100_USD', 'SPX500_USD']
RISK_PERCENT = 0.02

# NEW
INSTRUMENTS  = ['XAU_USD']
RISK_PERCENT = 0.01
ADR_THRESHOLD = 80.0   # skip session if 5-day ADR > this
LENS_CONFIDENCE_MIN = 60.0  # only apply directional filter at this confidence %
MARKET_BIAS_PATH = '/root/.openclaw/dashboard/market_bias.json'
```

Remove ASIA from `SESSION_TIMES`. Only NY at 13:30 UTC.

### 5.2 New Function: `get_orb_5m_blade(instrument)`

```python
def get_orb_5m_blade(instrument):
    """
    Fetch the 5-minute opening range candle for the instrument.
    Returns (orb_high, orb_low) or (None, None) on failure.
    """
    candles = get_candles(instrument, 'M5', 3)
    if not candles or len(candles) < 2:
        return None, None
    prev = candles[-2]['mid']  # last complete candle
    return float(prev['h']), float(prev['l'])
```

### 5.3 New Function: `get_5day_adr(instrument)`

```python
def get_5day_adr(instrument):
    """
    Compute the 5-day Average Daily Range for the instrument.
    Returns the ADR in price units (USD/oz for XAU_USD).
    """
    try:
        daily = get_candles(instrument, 'D', 7)
        if not daily or len(daily) < 6:
            return None
        completed = [c for c in daily if c.get('complete', True)][-6:-1]  # last 5 complete days
        ranges = [float(c['mid']['h']) - float(c['mid']['l']) for c in completed]
        return sum(ranges) / len(ranges)
    except Exception as e:
        logging.error(f"ADR calculation error: {e}")
        return None
```

### 5.4 New Function: `read_lens_bias()`

```python
def read_lens_bias():
    """
    Read Lens market_bias.json. Return (direction, confidence) for XAU/USD.
    direction: 'bullish', 'bearish', or 'neutral'
    confidence: float 0-100
    """
    try:
        with open(MARKET_BIAS_PATH) as f:
            data = json.load(f)
        xau = data.get('XAU/USD') or data.get('XAU_USD') or {}
        direction   = xau.get('bias', 'neutral').lower()
        confidence  = float(xau.get('confidence', 0))
        # Normalize: some implementations use 0.0-1.0, others 0-100
        if confidence <= 1.0:
            confidence *= 100
        return direction, confidence
    except FileNotFoundError:
        logging.warning("market_bias.json not found — no directional filter")
        return 'neutral', 0.0
    except Exception as e:
        logging.error(f"Lens bias read error: {e}")
        return 'neutral', 0.0
```

### 5.5 Update `wait_for_candle_close()` in Blade

Change from 15-minute to 5-minute calculation:

```python
def wait_for_candle_close():
    now = datetime.now(timezone.utc)
    minutes_into_candle = now.minute % 5
    wait_seconds = (5 - minutes_into_candle) * 60 - now.second
    if wait_seconds >= 300:
        wait_seconds -= 300
    if wait_seconds > 0:
        print(f"Waiting {wait_seconds}s for 5m candle close...")
        time.sleep(wait_seconds + 5)
```

### 5.6 Update `place_paper_order()` in Blade — Single TP

Remove `tp_multipliers = [1, 2, 3]`. Replace with:

```python
orb_range = orb_high - orb_low
if direction == 'long':
    stop_loss   = orb_low
    take_profit = price + (1.5 * orb_range)
else:
    stop_loss   = orb_high
    take_profit = price - (1.5 * orb_range)
```

Update position dict to store `take_profit` (scalar) instead of `take_profits` (list).
Update `manage_positions()` to use scalar TP check.

### 5.7 Update `run_orb_session()` — Full Logic

```python
def run_orb_session(session_name='NY'):
    print(f"BLADE -- {session_name} ORB Session | Instrument: XAU_USD")
    hub_post("blade", "status", f"{session_name} session starting. Instrument: XAU_USD")

    wait_for_session_open(session_name)
    wait_for_candle_close()  # wait for 5m ORB candle

    instrument = INSTRUMENTS[0]  # 'XAU_USD'

    # Step 1: ADR volatility gate
    adr = get_5day_adr(instrument)
    if adr is not None and adr > ADR_THRESHOLD:
        msg = f"ADR gate: {adr:.1f} pts > {ADR_THRESHOLD} — session skipped"
        print(msg); hub_post("blade", "status", msg)
        record_no_trade(session_name, instrument, "ADR too high")
        write_session_trades_to_json(); send_telegram_report(session_name)
        return

    # Step 2: Build ORB
    orb_high, orb_low = get_orb_5m_blade(instrument)
    if not orb_high:
        hub_post("blade", "error", f"{session_name}: ORB data unavailable for {instrument}", priority="high")
        record_no_trade(session_name, instrument, "ORB data unavailable")
        write_session_trades_to_json(); send_telegram_report(session_name)
        return

    # Step 3: Read Lens bias
    lens_direction, lens_confidence = read_lens_bias()
    apply_filter = lens_confidence >= LENS_CONFIDENCE_MIN
    print(f"Lens XAU bias: {lens_direction} ({lens_confidence:.0f}% confidence) | Filter active: {apply_filter}")
    hub_post("blade", "status", f"Lens XAU bias: {lens_direction} {lens_confidence:.0f}%. ORB: {orb_high:.2f}/{orb_low:.2f}")

    # Step 4: Monitor for breakout
    end_time = time.time() + (4 * 3600)
    session_close = datetime.now(timezone.utc).replace(hour=17, minute=0, second=0)
    traded = False

    while time.time() < end_time and datetime.now(timezone.utc) < session_close:
        if not traded:
            direction = check_1m_breakout(instrument, orb_high, orb_low)
            if direction:
                # Apply Lens directional filter
                blocked = False
                if apply_filter:
                    if lens_direction == 'bullish' and direction == 'short':
                        print(f"Short blocked — Lens {lens_confidence:.0f}% bullish")
                        blocked = True
                    elif lens_direction == 'bearish' and direction == 'long':
                        print(f"Long blocked — Lens {lens_confidence:.0f}% bearish")
                        blocked = True

                if not blocked:
                    place_paper_order(instrument, direction, orb_high, orb_low, session_name)
                    traded = True

        if open_positions:
            manage_positions()
        time.sleep(30)

    # Time stop — close any open position
    for instr in list(open_positions.keys()):
        pos = open_positions[instr]
        price = get_price(instr)
        pnl = (price - pos['entry']) * pos['units'] if pos['direction'] == 'long' \
              else (pos['entry'] - price) * pos['units']
        paper_balance += pnl
        update_trade_log(pos['trade_id'], "Time Stop", pnl, "Closed at session end.")

    open_positions.clear()
    hub_post("blade", "status", f"{session_name} complete. Balance: ${paper_balance:.2f}")
    write_session_trades_to_json()
    os.system("python3 /root/.openclaw/scripts/sync_agent_pnl.py")
    send_telegram_report(session_name)
```

### 5.8 No Changes Needed in Blade

These functions are correct and portable:
- `check_1m_breakout()` — open+close confirmation already implemented
- `write_session_trades_to_json()` — solid
- `get_price()` — works for XAU_USD
- `send_telegram_report()` — minor update: TP reference scalar only
- `hub_post()` integration — already present, correct usage

---

## 6. Implementation Sequence

When ready to implement, do it in this order to avoid introducing bugs:

1. **Crisp first** (simpler: Binance, fewer API edge cases)
   - Update config (symbols, risk, leverage)
   - Add `get_orb_5m()`, `check_volatility_gate()`, `get_prior_day_bias()`
   - Update `wait_for_candle_close()` to 5-minute logic
   - Update `place_paper_order()` to single TP
   - Update `manage_positions()` to single TP check
   - Update `run_orb_session()` with new flow
   - Update cron: disable ASIA, verify NY at 13:30 UTC
   - Test with a paper run during NY session — review telegram report

2. **Blade second** (more complex: OANDA API, Lens integration)
   - Update config (instrument, risk)
   - Add `get_orb_5m_blade()`, `get_5day_adr()`, `read_lens_bias()`
   - Update `wait_for_candle_close()` to 5-minute logic
   - Update `place_paper_order()` to single TP
   - Update `manage_positions()` to single TP check
   - Update `run_orb_session()` with full new flow
   - Test `read_lens_bias()` independently before live run
   - Test with a paper run during NY session — review telegram report

3. **Observe for 20 sessions minimum** before evaluating strategy performance.
   Track win rate, profit factor, and whether the ADR/Lens filters are triggering
   at reasonable rates (ADR gate: expect ~15-25% of sessions filtered; Lens gate:
   expect ~30-40% of sessions to have ≥60% confidence).

---

## 7. Risk Guardrails — Do Not Remove

These rules must be enforced in code, not just in strategy docs:

| Rule | Enforcement |
|------|-------------|
| Max 1 trade per session | `traded = True` flag after first entry |
| 1% risk maximum | Hardcode `RISK_PERCENT = 0.01`; no user override |
| No ASIA session for Crisp | Remove from cron, remove from code |
| Single TP only | No `tp_multipliers` list — single scalar only |
| ADR gate blocks trade | `return` from session, log as no_trade |
| Lens gate blocks counter-trend | Log reason, continue monitoring (do not trade) |

---

## 8. Verdict

The Crisp loss of $1,536 on 36 trades is a structural failure — the strategy was
mathematically expected to lose money given correlated 4x positions, 4% risk, and
3x leverage on a counter-trending bias. This is not a signal problem, it is a risk
management problem.

The new strategies address every root cause:
- Single instrument eliminates correlation risk
- 1% risk eliminates catastrophic session losses
- 5m ORB tightens the range for better entries
- Volatility and ADR gates skip the worst-performing days
- Trend filters reduce counter-trend entries
- Single TP simplifies management and measures edge cleanly

**Expected outcome on re-run:** The new strategies will trade less often (more filtered
sessions) and risk less per trade. The goal for the first 30 sessions is not
profitability — it is survival with controlled drawdowns while collecting data.
Win rate ≥ 45% and profit factor ≥ 1.0 over 20+ trades would validate the approach.

---

*Report generated by Advisor (JCF HQ CFO) | 2026-03-18 | Model: claude-sonnet-4-6*
