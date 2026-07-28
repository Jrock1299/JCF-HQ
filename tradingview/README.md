# TradingView indicators

Pine v5 ports of validated JCF HQ strategies. **Ports, not sources of truth**
— if the Python code and Pine code disagree, the Python is authoritative
(`agents/lens/ict_strategies.py`, `agents/lens/ict_backtest.py`,
`dashboard/strategy_library.json`). Every Pine file here MUST be updated in
the same PR as any material change to the underlying Python strategy.

## Files

- **`meanrev_sweep_fade.pine`** — the deployable mean-reversion post-sweep-fade
  strategy (library id `ict.turtle_soup.{SPX500_USD, DE30_EUR, XAU_USD}`).
  Prints BUY / SELL signals on chart with stop and target lines. Alerts
  supported.

## How to install (one-time)

1. TradingView → open a chart on one of the validated symbols (see mapping
   in each `.pine` file header).
2. Bottom of chart → **Pine Editor** tab.
3. Paste the entire contents of the `.pine` file into the editor.
4. **Save** (give it a name), then **Add to Chart**.
5. To enable phone / email alerts: right-click the indicator → **Add Alert…**
   → pick "Mean-Rev BUY" or "Mean-Rev SELL" from the Condition dropdown.
   Set frequency to **Once Per Bar Close** (not "Once Per Bar") — otherwise
   you'll be alerted before the bar closes and could act on a signal that
   hasn't confirmed yet.

## No-repaint guarantee

Every `.pine` file includes a header block explaining exactly which
mechanisms it uses to avoid repainting (confirmed-bar checks, non-lookahead
security calls, pivot-with-K-delay). The signals here print at the same bar
the Python backtest would have entered — not shifted forward after the
fact. If you compare a live signal to the same signal 10 bars later, it
must be at the same bar.

## TradingView symbol mapping (validated OANDA → TV)

Each Pine file lists its own mapping. In general prefer the `OANDA:*` symbols
on TradingView — they use the same feed the Python backtest ran against, so
the fine-grained bar timing matches.
