"""
dry_run.py — Simulate the full trading pipeline without placing any orders.

Pipeline:
  1. Initialise RiskManager (reads live balance from Kalshi)
  2. Scan 15M markets and score with strategy.py
  3. Check risk gate
  4. Print what trades WOULD be placed
"""

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)-12s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("dry_run")

SEP  = "─" * 68
SEP2 = "═" * 68


def _header(n: int, title: str):
    print(f"\n{'─'*3} Step {n}: {title} {'─'*(56 - len(title))}")


def main():
    print(SEP2)
    print("  KALSHI 15M BOT — DRY RUN  (no orders will be placed)")
    print(SEP2)

    # ── Step 1: Risk manager ──────────────────────────────────────────────────
    _header(1, "Initialise risk manager")
    try:
        from risk import RiskManager
        rm = RiskManager()
    except Exception as exc:
        print(f"  FATAL: Could not initialise RiskManager: {exc}")
        sys.exit(1)

    s = rm.status()
    print(f"  Bankroll         : ${s['bankroll']:.2f}")
    print(f"  Daily P&L        : ${s['daily_pnl']:+.2f}")
    print(f"  Daily loss limit : ${s['loss_limit']:.2f}")
    print(f"  Trades today     : {s['trades_today']} / 15 used, "
          f"{s['trades_remaining']} remaining")
    print(f"  Open positions   : {s['open_positions']} / 5")
    if s['open_tickers']:
        print(f"  Open tickers     : {', '.join(s['open_tickers'])}")
    print(f"  Next trade size  : ${s['next_size_dollars']:.2f}  "
          f"(2% of ${s['bankroll']:.2f}, clamped $1–$50)")

    # ── Step 2: Scan + score ──────────────────────────────────────────────────
    _header(2, "Scan 15M markets and score")
    try:
        from strategy import analyze_15m_markets, SERIES_15M, SCORE_THRESHOLD
    except Exception as exc:
        print(f"  FATAL: Could not import strategy: {exc}")
        sys.exit(1)

    print(f"  Series  : {', '.join(SERIES_15M)}")
    print(f"  Threshold: {SCORE_THRESHOLD}/100")
    print(f"  Fetching orderbooks and scoring...")

    signals = analyze_15m_markets()

    if not signals:
        print("\n  No markets scored above threshold right now.")
        print("  Possible reasons:")
        print("    • No 15M contracts expire in the next 4–18 minutes")
        print("    • All markets are near 50¢ fair value (flat momentum)")
        print("    • Orderbooks are too thin for liquidity score")
    else:
        print(f"\n  {len(signals)} signal(s) above {SCORE_THRESHOLD}:\n")
        print(f"  {'TICKER':<28} {'DIR':<4} {'SCORE':>5} {'MID':>6} {'ENTRY':>6} {'MIN LEFT':>9}")
        print(f"  {SEP}")
        for sig in signals:
            print(
                f"  {sig.ticker:<28} {sig.direction:<4} {sig.score:>5}/100"
                f"  {sig.mid_price:>5.1f}¢  {sig.entry_price:>5}¢"
                f"  {sig.minutes_left:>7.1f}m"
            )
        print()
        for sig in signals:
            print(f"  [{sig.ticker}]")
            print(f"    {sig.reasoning}")

    # ── Step 3: Risk gate ─────────────────────────────────────────────────────
    _header(3, "Risk gate check")
    can_trade, gate_reason = rm.can_trade()
    gate_label = "OPEN  ✓" if can_trade else f"CLOSED  ✗  ({gate_reason})"
    print(f"  Risk gate: {gate_label}")

    # ── Step 4: Simulated order summary ──────────────────────────────────────
    _header(4, "Simulated trade summary")

    if not signals:
        print("  0 signals — nothing to simulate.")

    elif not can_trade:
        print(f"  Risk gate blocked all trades: {gate_reason}")
        print(f"  0 trades would be placed.")

    else:
        print(f"\n  {'#':<3} {'TICKER':<28} {'DIR':<4} {'SCORE':>5} "
              f"{'ENTRY':>6} {'SIZE':>7} {'CONTRACTS':>10}")
        print(f"  {SEP}")

        placed   = 0
        blocked  = 0
        total_usd = 0.0

        for i, sig in enumerate(signals, 1):
            ok, reason = rm.can_trade()
            if not ok:
                print(f"  {i:<3} {sig.ticker:<28} BLOCKED — {reason}")
                blocked += 1
                continue

            size          = rm.position_size()
            entry_dollars = sig.entry_price / 100.0
            contracts     = size / entry_dollars if entry_dollars > 0 else 0
            total_usd    += size

            print(
                f"  {i:<3} {sig.ticker:<28} {sig.direction:<4} {sig.score:>5}/100"
                f"  {sig.entry_price:>5}¢  ${size:>5.2f}  {contracts:>9.1f}x"
            )

            # Simulate the open so subsequent can_trade() calls see the position
            rm.record_open(sig.ticker, sig.direction, size, sig.entry_price)
            placed += 1

        print(f"\n  Summary: {placed} trade(s) placed, {blocked} blocked")
        if placed:
            print(f"  Total capital committed: ${total_usd:.2f}")
            print(f"  Remaining bankroll:      ${rm.current_bankroll:.2f}")
            print(f"  Open positions:          {len(rm.open_positions)}/{5}")

    print()
    print(SEP2)
    print("  DRY RUN COMPLETE — no real orders were submitted")
    print(SEP2)
    print()


if __name__ == "__main__":
    main()
