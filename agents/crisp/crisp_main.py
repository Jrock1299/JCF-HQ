#!/usr/bin/env python3
"""
crisp_main.py — Crisp v5 Main Loop

Persistent process (runs via systemd). Orchestrates all 5 layers:
  Layer 1: Market structure map (hourly)
  Layer 2: Signal detection (every scan)
  Layer 3: Confluence scoring (every scan)
  Layer 4: Position management (every scan)
  Layer 5: Learning engine (Saturday 09:00 UTC)

Tiered polling: 5min during active sessions, 15min off-peak.
Paper trading only. Starting balance: $10,000.
"""

import logging
import signal
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, '/root/.openclaw/agents/crisp')

from crisp_config import (
    setup_logging, init_data_files,
    SCAN_INTERVAL_ACTIVE, SCAN_INTERVAL_QUIET,
    STRUCTURE_UPDATE_INTERVAL,
    MAX_DAILY_LOSS_PCT, MAX_CONSECUTIVE_LOSS,
    AGENT_NAME, send_telegram, hub_post,
    PAPER_BALANCE_START,
)
from market_data import warm_cache, get_current_price
from structure_engine import build_structure_map, load_structure_map
from signal_detector import detect_all_signals
from confluence_scorer import evaluate_trade_decision, get_current_session
from position_manager import (
    load_position, save_position,
    open_position, manage_position,
    load_paper_balance, save_paper_balance,
    send_entry_alert,
)
from learning_engine import append_signal_log, run_weekly_learning

# ─────────────────────────────────────────────────────────────────────────────
# STATE
# ─────────────────────────────────────────────────────────────────────────────

_running = True
_structure_map: dict = {}
_last_structure_update: float = 0.0
_last_loss_ts: float = None
_consecutive_losses: int = 0
_daily_start_balance: float = 0.0
_daily_start_ts: float = 0.0
_pause_until_ts: float = 0.0  # pause trading until this timestamp
_observation_mode: bool = False  # Phase D: detect but don't trade
_learning_ran_today: bool = False  # prevent duplicate Saturday runs


def _shutdown(signum, frame):
    global _running
    logging.info("Shutdown signal received — stopping gracefully")
    _running = False


signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT, _shutdown)


# ─────────────────────────────────────────────────────────────────────────────
# TIMING HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _is_active_session() -> bool:
    """True if current UTC hour is within a high-activity window."""
    h = datetime.now(timezone.utc).hour
    # London: 6-8, NY open: 13-16, NY PM: 17-20, Asia: 23-1
    return (6 <= h < 8) or (13 <= h < 16) or (17 <= h < 20) or (h >= 23 or h < 1)


def _get_session_open_hour() -> int | None:
    """Return the open hour of the current session if we're at the open."""
    now = datetime.now(timezone.utc)
    h, m = now.hour, now.minute
    # NY open: 13:30 UTC
    if h == 13 and m <= 45:
        return 13
    # Asia open: 00:00 UTC
    if h == 0 and m <= 45:
        return 0
    return None


def _scan_interval() -> int:
    return SCAN_INTERVAL_ACTIVE if _is_active_session() else SCAN_INTERVAL_QUIET


def _needs_structure_update() -> bool:
    return (time.time() - _last_structure_update) >= STRUCTURE_UPDATE_INTERVAL


def _is_saturday_morning() -> bool:
    now = datetime.now(timezone.utc)
    return now.weekday() == 5 and 9 <= now.hour < 10


# ─────────────────────────────────────────────────────────────────────────────
# RISK CONTROLS
# ─────────────────────────────────────────────────────────────────────────────

def _check_daily_loss_limit(balance: float) -> bool:
    """Returns True if daily loss limit has been hit (stop trading)."""
    global _daily_start_balance, _daily_start_ts
    now = time.time()
    # Reset daily stats at midnight UTC
    if now - _daily_start_ts > 86400:
        _daily_start_balance = balance
        _daily_start_ts = now
        return False
    loss = (_daily_start_balance - balance) / _daily_start_balance
    if loss >= MAX_DAILY_LOSS_PCT:
        logging.warning(f"Daily loss limit hit: {loss*100:.1f}% — pausing 24h")
        send_telegram(
            f"🛑 CRISP v5 — DAILY LOSS LIMIT\n"
            f"Down {loss*100:.1f}% today (limit: {MAX_DAILY_LOSS_PCT*100:.0f}%).\n"
            f"Trading paused for 24 hours."
        )
        return True
    return False


def _check_consecutive_losses() -> bool:
    """Returns True if consecutive loss threshold hit (pause)."""
    global _pause_until_ts, _consecutive_losses
    if _consecutive_losses >= MAX_CONSECUTIVE_LOSS:
        pause_end = time.time() + 43200  # 12h
        _pause_until_ts = pause_end
        _consecutive_losses = 0
        send_telegram(
            f"⚠️ CRISP v5 — {MAX_CONSECUTIVE_LOSS} consecutive losses\n"
            f"Pausing for 12 hours. Will resume at "
            f"{datetime.fromtimestamp(pause_end, tz=timezone.utc).strftime('%H:%M UTC')}"
        )
        return True
    return False


def _is_paused() -> bool:
    return time.time() < _pause_until_ts


def _check_extreme_volatility() -> bool:
    """Skip scan if M15 ATR is > 3x the daily average ATR."""
    try:
        from market_data import get_candles_as_dicts, calculate_atr
        m15 = get_candles_as_dicts('15m', limit=100)
        if len(m15) < 30:
            return False
        current_atr = calculate_atr(m15[-15:], 14)
        daily_avg_atr = calculate_atr(m15[-100:], 14)
        if daily_avg_atr > 0 and current_atr > daily_avg_atr * 3:
            logging.warning(f"Extreme volatility: M15 ATR ${current_atr:.0f} > "
                            f"3x avg ${daily_avg_atr:.0f} — skipping scan")
            return True
    except Exception:
        pass
    return False


# ─────────────────────────────────────────────────────────────────────────────
# MAIN SCAN CYCLE
# ─────────────────────────────────────────────────────────────────────────────

def run_scan_cycle():
    """
    One complete scan: update structure (if needed) → detect signals →
    score → decide → open/manage position.
    """
    global _structure_map, _last_structure_update
    global _last_loss_ts, _consecutive_losses
    global _learning_ran_today

    try:
        # --- Layer 1: Structure map (hourly) ---
        if _needs_structure_update():
            _structure_map = build_structure_map()
            _last_structure_update = time.time()
        elif not _structure_map:
            _structure_map = load_structure_map()

        if not _structure_map:
            logging.warning("No structure map available — skipping scan")
            return

        # --- Load current state ---
        balance    = load_paper_balance()
        active_pos = load_position()
        session    = get_current_session()

        # --- Risk gate ---
        if _check_daily_loss_limit(balance):
            return
        if _is_paused():
            return
        if _check_extreme_volatility():
            return

        current_price = get_current_price()

        # --- Layer 4: Manage open position ---
        if active_pos and active_pos.get('active'):
            active_pos, balance, events = manage_position(
                active_pos, current_price, balance
            )
            for event in events:
                logging.info(f"Position event: {event}")
                # Track losses for consecutive loss counter
                if 'SL_HIT' in event:
                    _consecutive_losses += 1
                    _last_loss_ts = time.time()
                    _check_consecutive_losses()
                elif 'TP' in event or 'TRAIL' in event:
                    _consecutive_losses = 0
            # Don't enter new trade if a position is still open
            if active_pos and active_pos.get('active'):
                return

        # --- Layer 2: Detect signals ---
        session_open_hour = _get_session_open_hour()
        signals = detect_all_signals(_structure_map, session_open_hour)

        # Log all detected signals (traded or not)
        # We'll update outcomes after the fact in the learning engine
        for sig in signals:
            append_signal_log(sig, traded=False)  # mark as untaken initially

        # --- Layer 3: Score and decide ---
        if not signals:
            return

        decision = evaluate_trade_decision(
            signals,
            session=session,
            last_loss_ts=_last_loss_ts,
        )
        rec = decision.get('recommendation')
        score = decision.get('total_score', 0)

        logging.info(
            f"Scan: price=${current_price:,.2f} | "
            f"session={session} | "
            f"{len(signals)} signal(s) | "
            f"score={score} | {rec} "
            f"(threshold={decision.get('threshold')})"
        )

        if rec != 'TRADE' or _observation_mode:
            if _observation_mode and rec == 'TRADE':
                logging.info(
                    f"OBSERVATION MODE — would trade: "
                    f"{decision.get('direction')} @ ${decision.get('best_signal',{}).get('entry_price',0):,.2f} "
                    f"score={score}"
                )
                send_telegram(
                    f"👁️ CRISP v5 [OBS] — {decision.get('direction','?').upper()} signal\n"
                    f"Score: {score}/100 | {decision.get('primary_signal','?')}\n"
                    f"Entry: ${decision.get('best_signal',{}).get('entry_price',0):,.2f}\n"
                    f"Would trade but observation mode active."
                )
            return

        # --- Layer 4: Execute entry ---
        best_sig = decision.get('best_signal')
        if not best_sig:
            return

        # Override raw_score with the full confluence score
        best_sig['raw_score'] = score

        pos = open_position(best_sig, balance)
        if pos:
            # Mark this specific signal as traded in the log
            from learning_engine import update_signal_outcome
            # Update the log entry to mark as traded
            try:
                with open('/root/.openclaw/agents/crisp/data/signal_log.json') as f:
                    import json
                    log_data = json.load(f)
                for entry in reversed(log_data['signals']):
                    if entry['signal_id'] == best_sig['signal_id']:
                        entry['traded'] = True
                        entry['trade_id'] = pos['trade_id']
                        break
                with open('/root/.openclaw/agents/crisp/data/signal_log.json', 'w') as f:
                    json.dump(log_data, f, indent=2)
            except Exception as e:
                logging.warning(f"Could not mark signal as traded: {e}")

            save_position(pos)
            send_entry_alert(pos)
            hub_post(AGENT_NAME, 'trade_open',
                     f"New {pos['direction']} trade opened @ ${pos['entry_price']:,.2f} "
                     f"score={score}",
                     tags=['crisp_v5', 'entry'])

    except Exception as e:
        logging.error(f"Scan cycle error: {e}", exc_info=True)


# ─────────────────────────────────────────────────────────────────────────────
# STARTUP
# ─────────────────────────────────────────────────────────────────────────────

def startup():
    global _daily_start_balance, _daily_start_ts, _observation_mode

    setup_logging()
    init_data_files()
    warm_cache()

    balance = load_paper_balance()
    _daily_start_balance = balance
    _daily_start_ts = time.time()

    # Check for --observe flag (observation mode — no live trades)
    if '--observe' in sys.argv:
        _observation_mode = True
        logging.info("OBSERVATION MODE ACTIVE — signals detected but no trades placed")

    logging.info(
        f"Crisp v5 starting | "
        f"Balance: ${balance:,.2f} | "
        f"Mode: {'OBSERVATION' if _observation_mode else 'PAPER TRADING'}"
    )

    send_telegram(
        f"🚀 CRISP v5 {'[OBSERVATION]' if _observation_mode else '[PAPER]'} STARTED\n"
        f"Balance: ${balance:,.2f} | BTC/USDT 24/7\n"
        f"Scan: 5min (active) / 15min (quiet)"
    )
    hub_post(AGENT_NAME, 'startup',
             f"Crisp v5 started. Balance: ${balance:,.2f}",
             tags=['crisp_v5', 'startup'])


# ─────────────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────────────────────────────────────

def main():
    global _learning_ran_today

    startup()

    while _running:
        loop_start = time.time()

        # Saturday 09:00 UTC → run weekly learning engine
        now_utc = datetime.now(timezone.utc)
        if _is_saturday_morning() and not _learning_ran_today:
            logging.info("Saturday morning — running weekly learning engine")
            try:
                run_weekly_learning()
            except Exception as e:
                logging.error(f"Learning engine error: {e}", exc_info=True)
            _learning_ran_today = True

        # Reset learning flag on non-Saturday
        if now_utc.weekday() != 5:
            _learning_ran_today = False

        # Run the scan
        run_scan_cycle()

        # Sleep until next scan
        interval = _scan_interval()
        elapsed  = time.time() - loop_start
        sleep_for = max(1, interval - elapsed)
        time.sleep(sleep_for)


if __name__ == '__main__':
    main()
