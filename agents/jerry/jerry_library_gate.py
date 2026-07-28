"""jerry_library_gate.py — the "no un-validated strategy" gate for Jerry.

Written 2026-07-28 as part of the 'validated strategies only' rollout. The
principle from the deploy brief: Jerry does NOT trade equities live-paper on
the failed strategy (Victoria graded FAIL, WR 35.3%, PF 0.972, -$599 net).
The gate here is what enforces that:

    trader.buy_stock(...) MUST consult is_symbol_deployable(symbol)
    before submitting any order. Off-book → refused, logged as GATED_OUT.

Currently the shared strategy_library.json has ZERO deployable entries for
Jerry's asset classes (equity, options, crypto_spot). Result: Jerry stays
online, monitors, reports — and refuses every entry. That is the intended
'ready-but-idling' state.

When Lens or Victoria promotes a crypto or equity strategy to the library,
this module picks it up on the next call. No Jerry code needs to change.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, '/root/.openclaw/scripts')
try:
    from strategy_library import iter_deployable, load as load_library  # type: ignore
except ImportError as e:                                    # pragma: no cover
    logging.warning(f'[jerry_gate] strategy_library import failed: {e}; gate defaults CLOSED')
    def iter_deployable(*_a, **_kw):
        return iter(())
    def load_library(*_a, **_kw):
        return {'_load_status': 'import_failed', 'validated': []}


AGENT = 'jerry'


def deployable_symbols() -> set:
    """Set of symbols in the library that Jerry is authorised to trade."""
    return {e['instrument'] for e in iter_deployable(agent=AGENT)}


def deployable_asset_classes_status() -> dict:
    """Per-asset-class summary for logging: how many deployable, examples."""
    from collections import defaultdict
    counts: dict = defaultdict(int)
    examples: dict = defaultdict(list)
    for e in iter_deployable(agent=AGENT):
        ac = e.get('asset_class', 'unknown')
        counts[ac] += 1
        if len(examples[ac]) < 3:
            examples[ac].append(e['instrument'])
    return {ac: {'count': counts[ac], 'examples': examples[ac]}
            for ac in counts}


def is_symbol_deployable(symbol: str) -> bool:
    """True iff at least one deployable strategy exists for `symbol` under
    Jerry's asset-class scope."""
    return symbol in deployable_symbols()


def gate_or_refuse(symbol: str, action: str = 'buy',
                   log: Optional[logging.Logger] = None) -> tuple:
    """Return (allowed, reason) for a proposed trade on `symbol`.

    Callers use this at the top of every buy/order path. The reason string
    is safe to persist and to Telegram — no fabricated numbers.
    """
    lib = load_library()
    if lib.get('_load_status') != 'ok':
        msg = ('LIBRARY_UNAVAILABLE: strategy_library.json missing or unreadable; '
               'gate defaults CLOSED — no trade.')
        (log or logging.getLogger('jerry_gate')).warning(msg)
        return False, msg

    if is_symbol_deployable(symbol):
        return True, f'DEPLOYABLE: {symbol} in library (asset-class jerry)'

    status = deployable_asset_classes_status()
    reason = (f'GATED_OUT: no deployable strategy for {symbol}. '
              f'Jerry authorised asset-classes: equity, options, crypto_spot. '
              f'Deployable today: {status or "none"}. '
              f'Refusing {action} — Jerry idles until Lens/Victoria promote '
              f'a strategy for this symbol.')
    (log or logging.getLogger('jerry_gate')).info(reason)
    return False, reason


def startup_summary() -> str:
    """One-line Telegram-friendly summary of what Jerry is currently
    authorised to trade. Used in the boot message + status pings."""
    lib = load_library()
    if lib.get('_load_status') != 'ok':
        return 'Library UNAVAILABLE — Jerry gated to zero trades.'
    status = deployable_asset_classes_status()
    if not status:
        return ('No deployable strategies for Jerry\'s asset-classes '
                '(equity/options/crypto_spot). Idling — will trade when '
                'Lens/Victoria promotes a validated strategy.')
    bits = [f'{ac}: {v["count"]} ({", ".join(v["examples"])}'
            + (', …' if v["count"] > len(v["examples"]) else '') + ')'
            for ac, v in status.items()]
    return 'Trading on validated strategies: ' + ' | '.join(bits)


if __name__ == '__main__':
    print(startup_summary())
    print()
    print('Deployable symbols for jerry:', deployable_symbols())
    print()
    print('Detail:')
    for ac, v in deployable_asset_classes_status().items():
        print(f'  {ac}: {v}')
