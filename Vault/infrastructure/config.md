# Centralized Config

Single tunable surface for the trading system. Created 2026-06-01.

## Files

### `dashboard/agent_strategies.json`
Per-agent risk knobs. Read by every agent at startup via
`scripts/agent_config.py:load_strategy(agent_name, defaults)`.

**Non-breaking by design:** if the file is missing or a key isn't present,
the agent falls back to its hardcoded defaults. No behavior change unless
you actively change the JSON.

```json
{
  "blade": {
    "RISK_PCT_PER_CLUSTER":      0.02,
    "POSITION_WEIGHTS":          {"pos1": 0.20, "pos2": 0.30, "pos3": 0.50},
    "TP_R_MULTIPLES":            {"pos1": 1.0,  "pos2": 2.0,  "pos3": null},
    "POS3_TRAIL":                true,
    "POS3_TRAIL_DISTANCE_R":     1.0,
    "DAILY_DD_HALT_PCT":         0.04,
    "STARTING_BALANCE_DEFAULT":  5000.0,
    "SL_BUFFER_POINTS":          3,
    "MIN_BALANCE":               100.0,
    // legacy fallbacks (unused under D3)
    "RISK_PCT":                  0.01,
    "TP_PIPS":                   {"pos1": 3, "pos2": 5, "pos3": 10}
  },
  "edge": {
    "MAX_DAILY_LOSSES":          5,
    "MAX_DAILY_LOSS_PCT":        2.0,
    "TP1_PTS":                   15,
    "TP2_PTS":                   25,
    "UNITS":                     2,
    "MARKET_OPEN_BLACKOUT_MIN":  15
  },
  "norman": {
    "MIN_TRADES_FOR_VERDICT":    20,
    "RUIN_DRAWDOWN_PCT":         0.50,
    "DOUBLE_TARGET_PCT":         1.00
  },
  "sentinel": {
    "WATCHLIST_PATH":            "/root/.openclaw/dashboard/watchlist.json"
  },
  "tao": {
    "TOTAL_DCA_ENTRIES":     5,
    "ROOT_STAKE_PCT":        50,
    "SUBNET_STAKE_PCT":      50,
    "DCA_COOLDOWN_HOURS":    48,
    "DCA_DIP_THRESHOLD_PCT": 2.0,
    "MIN_SUBNET_SCORE":      50
  }
}
```

Tao migrated from `.env` to the central file on 2026-06-01. Secrets (wallet
mnemonics, CoinGecko key, Telegram tokens) remain in `agents/tao/.env`.
`.env` overrides for the strategy knobs are still honored if a value is set
there — `os.getenv()` runs before the central JSON fallback.

See:
- [[../strategies/blade-d3-sizing]] for the D3 knob meanings
- [[../agents/edge]] for Edge knobs
- [[../agents/norman]] for verdict rules

### `dashboard/watchlist.json`
Jase's by-theme tickers (extracted from sentinel_sync.py hardcoded dict).
Read by [[../agents/sentinel|Sentinel]] with a hardcoded fallback.

```json
{
  "holdings":        ["NVDA","IREN","UUUU","IONQ","VST","TEM","SOFI","MSTR","USAR","OKLO"],
  "quantum_nuclear": ["RGTI","CCJ","QBTS","NLR","SMR"],
  "energy":          ["REMX","XLE","XOM","CVX"],
  "metals":          ["SCCO","IAU","URA","SLV","FCX","GLD"],
  "robotics_ai":     ["JOBY","NRSN","SYM","RR","ARBE"],
  "saudi":           ["FLSA","KSA"],
  "tech_semis":      ["AMD","ARM","PLTR","COIN","MARA"]
}
```

## The loader

`scripts/agent_config.py`:

```python
def load_strategy(agent_name: str, defaults: dict) -> dict:
    """Central file overrides; defaults fill gaps."""
    cfg = dict(defaults)
    try:
        with open('/root/.openclaw/dashboard/agent_strategies.json') as f:
            data = json.load(f)
        override = data.get(agent_name, {}) or {}
        for k, v in override.items():
            if not k.startswith('_'):
                cfg[k] = v
    except Exception as e:
        logging.warning(f"agent_config: could not load: {e}")
    return cfg
```

Keys starting with `_` (e.g. `_note`) are skipped — useful for adding
context to the JSON without breaking the load.

## Why this exists
Before 2026-06-01, every threshold was hardcoded in the agent's module.
Norman's "tighten X" recommendations were unactionable without a redeploy.
Now one file controls every tunable risk knob and we can ship a change
in seconds.

See [[../decisions/decision-log#centralized-agent_strategies-2026-06-01]].

## Editing rules
1. **JSON validity matters.** Bad JSON → agents fall back silently to
   hardcoded defaults. Lint before commit: `python3 -c "import json; json.load(open('dashboard/agent_strategies.json'))"`.
2. **Never put secrets in here.** It's tracked in git. Secrets go in
   `.env` (gitignored). See [[system-architecture#secret-hygiene]].
3. **Document changes in [[../decisions/decision-log]].** Future-Claude will
   want to know *why* a knob changed.
4. **Test before committing risk changes.** A bad weight in `POSITION_WEIGHTS`
   that doesn't sum to 1.0 will silently distort sizing rails.

## Related
- [[system-architecture]]
- [[../strategies/blade-d3-sizing]]
- [[../agents/sentinel]]
