"""
phantom_trader.py — Phemex execution layer for Phantom.

Handles all order placement, position management, SL/TP modification,
and trade logging. All trades are persisted to data/trade_history.json
and broadcast to Telegram.
"""

import math
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from phantom_config import (
    exchange, STARTING_BALANCE, SAFETY_FLOOR_PCT,
    TRADE_HISTORY_PATH, DASHBOARD_PATH, PERFORMANCE_PATH,
    get_logger, send_telegram, load_json, save_json,
)

log = get_logger('trader')


class PhantomTrader:
    """Unified interface for Binance USDM Futures testnet trading."""

    def __init__(self):
        self.exchange = exchange

    # ── Balance / Positions ────────────────────────────────────────────────────

    def get_balance(self) -> float:
        """Fetch current USDT balance from Binance futures testnet."""
        try:
            bal = self.exchange.fetch_balance()
            usdt = (bal.get('USDT', {}).get('total') or
                    bal.get('total', {}).get('USDT') or 0.0)
            return float(usdt)
        except Exception as e:
            log.error('get_balance failed: %s', e)
            return 0.0

    def get_positions(self) -> list[dict]:
        """
        Fetch all open positions.
        Returns list of position dicts with normalised fields.
        """
        try:
            raw = self.exchange.fetch_positions()
            result = []
            for p in raw:
                contracts = float(p.get('contracts') or p.get('size') or 0)
                if contracts == 0:
                    continue
                result.append({
                    'symbol':        p.get('symbol', ''),
                    'side':          p.get('side', '').lower(),
                    'contracts':     contracts,
                    'entry_price':   float(p.get('entryPrice') or p.get('entry_price') or 0),
                    'leverage':      float(p.get('leverage') or 1),
                    'unrealized_pnl': float(p.get('unrealizedPnl') or 0),
                    'notional':      float(p.get('notional') or 0),
                    'liquidation_price': p.get('liquidationPrice'),
                    'margin_mode':   p.get('marginMode', 'cross'),
                })
            return result
        except Exception as e:
            log.error('get_positions failed: %s', e)
            return []

    def get_market_data(self, symbol: str, timeframe: str,
                        limit: int = 100) -> list[dict]:
        """
        Fetch OHLCV candles.
        Returns list of {ts, open, high, low, close, volume}.
        """
        try:
            candles = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            return [
                {'ts': c[0], 'open': float(c[1]), 'high': float(c[2]),
                 'low': float(c[3]), 'close': float(c[4]), 'volume': float(c[5])}
                for c in candles
            ]
        except Exception as e:
            log.error('get_market_data %s %s: %s', symbol, timeframe, e)
            return []

    def get_ticker(self, symbol: str) -> dict:
        """Fetch current ticker for a symbol."""
        try:
            return self.exchange.fetch_ticker(symbol)
        except Exception as e:
            log.error('get_ticker %s: %s', symbol, e)
            return {}

    # ── Order execution ────────────────────────────────────────────────────────

    def open_position(
        self,
        symbol: str,
        side: str,             # 'long' or 'short'
        leverage: int,
        amount_usdt: float,
        strategy_name: str,
        context: str = '',
        sl_price: Optional[float] = None,
        tp_price: Optional[float] = None,
    ) -> Optional[dict]:
        """
        Open a leveraged futures position.

        Args:
            symbol:       e.g. 'BTC/USDT:USDT'
            side:         'long' or 'short'
            leverage:     1 to 100
            amount_usdt:  margin to use in USDT
            strategy_name: which strategy triggered this
            context:      human-readable reason
            sl_price:     stop-loss price (optional)
            tp_price:     take-profit price (optional)

        Returns:
            Trade record dict (also logged to trade_history.json), or None on failure.
        """
        side_lower = side.lower()
        if side_lower not in ('long', 'short'):
            log.error('Invalid side: %s', side)
            return None

        # ── Set leverage ───────────────────────────────────────────────────────
        try:
            # Binance USDM accepts leverage via set_leverage; marginMode param ignored
            self.exchange.set_leverage(leverage, symbol)
            log.info('Set leverage %dx for %s', leverage, symbol)
        except Exception as e:
            log.warning('set_leverage failed for %s: %s (proceeding)', symbol, e)

        # ── Calculate contract size ────────────────────────────────────────────
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            price  = float(ticker.get('last') or ticker.get('close'))
        except Exception as e:
            log.error('get_price failed for %s: %s', symbol, e)
            return None

        # Amount in base currency = (margin × leverage) / price
        notional  = amount_usdt * leverage
        contracts = notional / price

        # Align to market's amount precision step (Binance uses precision.amount)
        try:
            market = self.exchange.market(symbol)
            # Binance futures: precision.amount is the lot step (e.g. 0.001 for BTC)
            step = float(
                market.get('precision', {}).get('amount') or
                market.get('contractSize') or 0.001
            )
            if step > 0:
                contracts = math.floor(contracts / step) * step
            contracts = round(contracts, 8)
        except Exception:
            contracts = round(contracts, 3)

        if contracts <= 0:
            log.error('Calculated 0 contracts for %s — size $%.2f too small', symbol, amount_usdt)
            return None

        # ── Place market order ─────────────────────────────────────────────────
        # Binance USDM one-way mode: buy=long, sell=short — no positionSide needed
        ccxt_side = 'buy' if side_lower == 'long' else 'sell'
        trade_id  = str(uuid.uuid4())[:8]

        try:
            order = self.exchange.create_market_order(
                symbol, ccxt_side, contracts,
            )
            order_id     = order.get('id', 'unknown')
            filled_price = float(order.get('average') or order.get('price') or price)
            log.info('Order placed: %s %s %s  %g contracts @ $%.4f  id=%s',
                     side_lower.upper(), symbol, strategy_name,
                     contracts, filled_price, order_id)
        except Exception as e:
            log.error('create_market_order failed for %s: %s', symbol, e)
            return None

        # ── Set SL / TP ────────────────────────────────────────────────────────
        if sl_price:
            self._set_stop_loss(symbol, side_lower, contracts, sl_price)
        if tp_price:
            self._set_take_profit(symbol, side_lower, contracts, tp_price)

        # ── Build trade record ─────────────────────────────────────────────────
        record = {
            'id':            trade_id,
            'order_id':      order_id,
            'timestamp':     datetime.now(timezone.utc).isoformat(),
            'strategy_name': strategy_name,
            'symbol':        symbol,
            'side':          side_lower,
            'leverage':      leverage,
            'entry_price':   round(filled_price, 4),
            'exit_price':    None,
            'sl':            sl_price,
            'tp':            tp_price,
            'size_usdt':     round(amount_usdt, 2),
            'contracts':     round(contracts, 6),
            'notional':      round(notional, 2),
            'pnl':           None,
            'pnl_pct':       None,
            'status':        'open',
            'close_reason':  None,
            'context':       context,
            'opened_at':     datetime.now(timezone.utc).isoformat(),
            'closed_at':     None,
        }

        self._append_trade(record)
        self._update_dashboard()

        # ── Telegram alert ─────────────────────────────────────────────────────
        sl_str = f"  SL: ${sl_price:,.2f}" if sl_price else ''
        tp_str = f"  TP: ${tp_price:,.2f}" if tp_price else ''
        send_telegram(
            f"PHANTOM — NEW POSITION\n"
            f"{symbol} {side_lower.upper()} @ ${filled_price:,.4f}\n"
            f"Leverage: {leverage}x | Margin: ${amount_usdt:.0f}\n"
            f"Strategy: {strategy_name}\n"
            f"{sl_str}{tp_str}\n"
            f"Reason: {context[:120]}"
        )

        return record

    def close_position(
        self,
        symbol: str,
        reason: str = 'manual',
        trade_id: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Close an open position and update its trade record.

        Args:
            symbol:   Symbol to close.
            reason:   Why we're closing (tp/sl/trailing/manual/time_stop).
            trade_id: Optional specific trade ID to update.

        Returns:
            Updated trade record with P&L, or None on failure.
        """
        # Find existing position
        positions = self.get_positions()
        pos = next((p for p in positions if p['symbol'] == symbol), None)

        if pos is None:
            log.warning('close_position: no open position for %s', symbol)
            return None

        contracts = pos['contracts']
        side      = pos['side']

        # To close: buy back shorts, sell longs
        close_side = 'buy' if side == 'short' else 'sell'

        try:
            order = self.exchange.create_market_order(
                symbol, close_side, contracts,
                params={'reduceOnly': True},
            )
            exit_price = float(order.get('average') or order.get('price') or 0)
        except Exception as e:
            log.error('close_position failed for %s: %s', symbol, e)
            return None

        # Calculate P&L
        entry_price = pos['entry_price']
        leverage    = pos['leverage']
        notional    = pos['notional']

        if side == 'long':
            pnl_pct = (exit_price - entry_price) / entry_price * leverage
        else:
            pnl_pct = (entry_price - exit_price) / entry_price * leverage
        pnl_usd = notional * pnl_pct / leverage * leverage  # notional × % return

        log.info('Closed %s %s @ $%.4f  PnL: $%+.2f (%+.2f%%)  reason=%s',
                 side.upper(), symbol, exit_price, pnl_usd, pnl_pct * 100, reason)

        # Update trade record
        history = load_json(TRADE_HISTORY_PATH, [])
        record  = None
        for t in reversed(history):
            if t.get('symbol') == symbol and t.get('status') == 'open':
                if trade_id is None or t.get('id') == trade_id:
                    t['exit_price']   = round(exit_price, 4)
                    t['pnl']          = round(pnl_usd, 4)
                    t['pnl_pct']      = round(pnl_pct * 100, 2)
                    t['status']       = 'closed'
                    t['close_reason'] = reason
                    t['closed_at']    = datetime.now(timezone.utc).isoformat()
                    record = t
                    break

        if record:
            save_json(TRADE_HISTORY_PATH, history)

        self._update_dashboard()

        pnl_sign = '+' if pnl_usd >= 0 else ''
        send_telegram(
            f"PHANTOM — POSITION CLOSED\n"
            f"{symbol} {side.upper()} → "
            f"{pnl_sign}${pnl_usd:.2f} ({pnl_sign}{pnl_pct*100:.1f}%)\n"
            f"Entry: ${entry_price:,.4f}  Exit: ${exit_price:,.4f}\n"
            f"Strategy: {record.get('strategy_name', '?') if record else '?'}\n"
            f"Close reason: {reason}"
        )

        return record

    def modify_position(
        self,
        symbol: str,
        new_sl: Optional[float] = None,
        new_tp: Optional[float] = None,
    ) -> bool:
        """Modify SL/TP on an open position."""
        success = True
        if new_sl:
            success = success and self._set_stop_loss(symbol, None, None, new_sl)
        if new_tp:
            success = success and self._set_take_profit(symbol, None, None, new_tp)
        if success:
            history = load_json(TRADE_HISTORY_PATH, [])
            for t in reversed(history):
                if t.get('symbol') == symbol and t.get('status') == 'open':
                    if new_sl:
                        t['sl'] = new_sl
                    if new_tp:
                        t['tp'] = new_tp
                    break
            save_json(TRADE_HISTORY_PATH, history)
        return success

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _set_stop_loss(self, symbol: str, side, contracts, sl_price: float) -> bool:
        try:
            positions = self.get_positions()
            pos = next((p for p in positions if p['symbol'] == symbol), None)
            if not pos and side is None:
                return False
            side      = side or pos['side']
            contracts = contracts or pos['contracts']
            sl_side   = 'sell' if side == 'long' else 'buy'
            # Binance USDM: STOP_MARKET with stopPrice + closePosition
            self.exchange.create_order(
                symbol, 'STOP_MARKET', sl_side, contracts,
                params={
                    'stopPrice':     sl_price,
                    'closePosition': True,   # closes full position regardless of size
                },
            )
            log.info('SL set for %s @ $%.4f', symbol, sl_price)
            return True
        except Exception as e:
            log.warning('set_stop_loss failed for %s: %s', symbol, e)
            return False

    def _set_take_profit(self, symbol: str, side, contracts, tp_price: float) -> bool:
        try:
            positions = self.get_positions()
            pos = next((p for p in positions if p['symbol'] == symbol), None)
            if not pos and side is None:
                return False
            side      = side or pos['side']
            contracts = contracts or pos['contracts']
            tp_side   = 'sell' if side == 'long' else 'buy'
            # Binance USDM: TAKE_PROFIT_MARKET with stopPrice + closePosition
            self.exchange.create_order(
                symbol, 'TAKE_PROFIT_MARKET', tp_side, contracts,
                params={
                    'stopPrice':     tp_price,
                    'closePosition': True,
                },
            )
            log.info('TP set for %s @ $%.4f', symbol, tp_price)
            return True
        except Exception as e:
            log.warning('set_take_profit failed for %s: %s', symbol, e)
            return False

    def _append_trade(self, record: dict) -> None:
        history = load_json(TRADE_HISTORY_PATH, [])
        if not isinstance(history, list):
            history = []
        history.append(record)
        save_json(TRADE_HISTORY_PATH, history)

    def _update_dashboard(self) -> None:
        """Write current state to phantom_portfolio.json."""
        history    = load_json(TRADE_HISTORY_PATH, [])
        positions  = self.get_positions()
        closed     = [t for t in history if t.get('status') == 'closed']
        total_pnl  = sum(t.get('pnl', 0) or 0 for t in closed)
        wins       = sum(1 for t in closed if (t.get('pnl') or 0) > 0)
        win_rate   = (wins / len(closed) * 100) if closed else 0

        balance = self.get_balance()

        strategies = load_json(
            Path('/root/.openclaw/agents/phantom/data/strategies.json'), []
        )
        active_strats = [s for s in strategies if s.get('status') == 'active']

        # Determine status
        floor = STARTING_BALANCE * SAFETY_FLOOR_PCT
        if balance < floor and balance > 0:
            status = 'paused_safety_floor'
        elif active_strats:
            status = 'trading'
        else:
            status = 'discovering'

        dashboard = {
            'last_updated':     __import__('datetime').datetime.now(
                __import__('datetime').timezone.utc).isoformat(),
            'balance':          round(balance, 2),
            'starting_balance': STARTING_BALANCE,
            'total_pnl':        round(total_pnl, 2),
            'total_pnl_pct':    round(total_pnl / STARTING_BALANCE * 100, 2),
            'open_positions':   positions,
            'active_strategies': [
                {'name': s.get('name'), 'instruments': s.get('instruments')}
                for s in active_strats
            ],
            'total_trades':     len(closed),
            'win_rate':         round(win_rate, 1),
            'status':           status,
        }
        save_json(DASHBOARD_PATH, dashboard)
