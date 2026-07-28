#!/usr/bin/env python3
"""live_turtle_first_fire.py — one-shot Telegram alert on the FIRST paper
trade each executor places.

Purpose. Cron scheduling is not proof the live loop works — a schedule can
fire without a signal, a signal can fire without an order, an order can be
placed without SL attached. This script watches the executor's own trade log
and Telegrams the moment each agent actually PLACES A PAPER TRADE, so Jase
knows the end-to-end wire (schedule → detection → OANDA order → SL+TP
brackets) is live.

Behaviour.
  - One alert per agent (blade, edge). After firing, the agent's flag is
    marked in dashboard/live_turtle_first_fire.json.
  - Subsequent invocations are a fast no-op — safe to cron every 5 min
    indefinitely.
  - Only alerts on `status == 'SIGNAL_FIRED'` records (dry-runs and
    OUT_OF_KILLZONE / NO_SIGNAL entries are ignored).
  - If Telegram fails, does NOT mark the flag so a retry alerts next tick.

Same pattern as scripts/lens_first_fire_check.sh (mentioned in the tree)
— minimal state, one shot per stream, fires exactly once.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


TRADES_PATH = Path('/root/.openclaw/dashboard/live_turtle_trades.json')
STATE_PATH  = Path('/root/.openclaw/dashboard/live_turtle_first_fire.json')
LOG_PATH    = Path('/root/.openclaw/logs/live_turtle_first_fire.log')

AGENTS = ('blade', 'edge')


def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {a: {'alerted': False} for a in AGENTS}
    try:
        d = json.loads(STATE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {a: {'alerted': False} for a in AGENTS}
    for a in AGENTS:
        d.setdefault(a, {'alerted': False})
    return d


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, indent=2, default=str))
    os.replace(tmp, STATE_PATH)


def _latest_fire(agent: str) -> dict | None:
    """Return the most recent SIGNAL_FIRED record for `agent`, or None."""
    if not TRADES_PATH.exists():
        return None
    try:
        store = json.loads(TRADES_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    for rec in reversed(store.get('records', [])):
        if rec.get('agent') != agent:
            continue
        if rec.get('status') != 'SIGNAL_FIRED':
            continue
        if rec.get('dry_run'):
            continue
        return rec
    return None


def _telegram(message: str) -> bool:
    """Best-effort Telegram send via scripts/telegram_personalities.wrap_message.
    Returns True on success. Never raises — a Telegram failure must NOT mark
    the agent as alerted (we want to retry next tick)."""
    try:
        sys.path.insert(0, '/root/.openclaw/scripts')
        from telegram_personalities import wrap_message
        from hub_post import add_hub_message as hub_post   # type: ignore
        wrapped = wrap_message('lens', message)
        hub_post(wrapped, target='797062420')
        return True
    except Exception as e:
        logging.warning(f'telegram send failed: {e}')
        # Fallback: raw HTTP if telegram-personalities isn't wired
        return _telegram_raw(message)


def _telegram_raw(message: str) -> bool:
    """Direct Bot API call. Requires TELEGRAM_BOT_TOKEN + TELEGRAM_UID in env."""
    import urllib.parse
    import urllib.request
    tok = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
    uid = os.getenv('TELEGRAM_UID', '797062420').strip()
    if not tok:
        return False
    url = f'https://api.telegram.org/bot{tok}/sendMessage'
    body = urllib.parse.urlencode({
        'chat_id': uid, 'text': message, 'parse_mode': 'Markdown',
    }).encode()
    try:
        with urllib.request.urlopen(url, data=body, timeout=15) as r:
            return r.status == 200
    except Exception as e:
        logging.warning(f'telegram raw send failed: {e}')
        return False


def _format_alert(agent: str, rec: dict) -> str:
    sig = rec.get('signal') or {}
    inst = rec.get('instrument', '?')
    direction = sig.get('direction', '?').upper()
    fill = sig.get('fill_price')
    stop_d = sig.get('stop_distance')
    tgt_d = sig.get('target_distance')
    realized_rr = sig.get('realized_rr')
    units = sig.get('units')
    tp_status = sig.get('tp_attach_status', 'unknown')
    hash_ = sig.get('library_content_hash', '?')

    lines = [
        f'*FIRST FIRE — {agent.upper()}*',
        f'Live paper loop confirmed end-to-end.',
        '',
        f'Instrument: `{inst}`',
        f'Direction:  {direction}   units {units}',
        f'Stop dist:  {stop_d}   Tgt dist: {tgt_d}   R:R {realized_rr or "pending"}',
    ]
    if fill is not None:
        lines.append(f'Fill:       {fill}')
        lines.append(f'TP attach:  {tp_status}')
    lines.extend([
        '',
        f'Library hash: `{hash_}`',
        f'Fired: {rec.get("timestamp")}',
        '',
        f'This alert fires once per agent. Silent from here.',
    ])
    return '\n'.join(lines)


def main() -> int:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(LOG_PATH), level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
    )

    state = _load_state()
    fired_now = []
    for agent in AGENTS:
        if state.get(agent, {}).get('alerted'):
            continue
        rec = _latest_fire(agent)
        if not rec:
            continue
        msg = _format_alert(agent, rec)
        ok = _telegram(msg)
        if not ok:
            logging.warning(f'{agent}: SIGNAL_FIRED detected but Telegram failed — will retry next tick')
            continue
        state[agent] = {
            'alerted':      True,
            'alerted_at':   datetime.now(timezone.utc).isoformat(),
            'first_signal': rec,
        }
        fired_now.append(agent)

    if fired_now:
        _save_state(state)
        for a in fired_now:
            logging.info(f'first-fire ALERTED for {a}')
            print(f'first-fire ALERTED for {a}')
    else:
        # Log a heartbeat every ~10 invocations so we can prove the monitor is
        # running (and not silently broken) without spamming the log every tick.
        heartbeat_marker = LOG_PATH.parent / '.first_fire_heartbeat'
        try:
            existing = int(heartbeat_marker.read_text().strip()) if heartbeat_marker.exists() else 0
        except (ValueError, OSError):
            existing = 0
        existing += 1
        heartbeat_marker.write_text(str(existing))
        if existing % 10 == 0:
            waiting = [a for a in AGENTS if not state.get(a, {}).get('alerted')]
            logging.info(f'heartbeat #{existing} — waiting on: {waiting or "nobody (all fired)"}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
