"""
jerry_trader.py — Alpaca execution layer for Jerry.

Handles stock and options order submission, position management,
market data fetching, and trade history logging.
Paper trading only — uses paper-api.alpaca.markets.
"""

import json
import sys
import requests
import os
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from jerry_config import (
    api, TRADE_HISTORY_PATH, DASHBOARD_PATH,
    get_logger, load_json, save_json, send_telegram,
)
from jerry_context import load_context, snapshot_for_trade

# Phase 1: observation only — Jerry stamps team context onto every trade
# and writes closed trades to a learning log, but does NOT gate any trade.
LEARNING_LOG_PATH = '/root/.openclaw/dashboard/jerry_learning_log.json'

log = get_logger('trader')

# Alpaca data API base (same key, different endpoint)
_DATA_API = 'https://data.alpaca.markets'
_HEADERS  = {
    'APCA-API-KEY-ID':     os.getenv('ALPACA_API_KEY', ''),
    'APCA-API-SECRET-KEY': os.getenv('ALPACA_API_SECRET', ''),
}


class JerryTrader:

    def __init__(self):
        self._api = api

    # ── Account ────────────────────────────────────────────────────────────────

    def get_account(self) -> dict:
        try:
            acct = self._api.get_account()
            return {
                'status':         acct.status,
                'portfolio_value': float(acct.portfolio_value),
                'buying_power':   float(acct.buying_power),
                'cash':           float(acct.cash),
                'equity':         float(acct.equity),
            }
        except Exception as e:
            log.error('get_account error: %s', e)
            return {}

    def get_balance(self) -> float:
        acct = self.get_account()
        return acct.get('portfolio_value', 0.0)

    # ── Positions ──────────────────────────────────────────────────────────────

    def get_positions(self) -> list:
        try:
            positions = self._api.list_positions()
            result = []
            for p in positions:
                result.append({
                    'symbol':           p.symbol,
                    'qty':              float(p.qty),
                    'avg_entry_price':  float(p.avg_entry_price),
                    'current_price':    float(p.current_price) if p.current_price else 0,
                    'market_value':     float(p.market_value) if p.market_value else 0,
                    'unrealized_pl':    float(p.unrealized_pl) if p.unrealized_pl else 0,
                    'unrealized_plpc':  float(p.unrealized_plpc) if p.unrealized_plpc else 0,
                    'side':             p.side,
                    'asset_class':      getattr(p, 'asset_class', 'us_equity'),
                })
            return result
        except Exception as e:
            log.error('get_positions error: %s', e)
            return []

    def get_open_symbols(self) -> set:
        return {p['symbol'] for p in self.get_positions()}

    # ── Stock orders ──────────────────────────────────────────────────────────

    def buy_stock(self, symbol: str, notional: float,
                  stop_loss: float = None, take_profit: float = None,
                  strategy_name: str = '', thesis: str = '') -> dict | None:
        """
        Buy stock with optional bracket SL/TP.
        notional = dollar amount to spend.
        """
        try:
            # Get current price to calculate qty for bracket support
            snapshot = self.get_snapshot(symbol)
            price = snapshot.get('price', 0)
            if price <= 0:
                log.warning('Cannot get price for %s — skipping buy', symbol)
                return None

            qty = int(notional / price)
            if qty < 1:
                log.warning('%s: notional $%.2f < 1 share at $%.2f', symbol, notional, price)
                return None

            order_kwargs = dict(
                symbol=symbol,
                qty=qty,
                side='buy',
                type='market',
                time_in_force='day',
            )

            if stop_loss and take_profit:
                order_kwargs['order_class'] = 'bracket'
                order_kwargs['take_profit'] = {'limit_price': str(round(take_profit, 2))}
                order_kwargs['stop_loss']   = {'stop_price':  str(round(stop_loss, 2))}
            elif stop_loss:
                order_kwargs['order_class'] = 'oto'
                order_kwargs['stop_loss']   = {'stop_price': str(round(stop_loss, 2))}

            order = self._api.submit_order(**order_kwargs)

            log.info('BUY %s x%d @ ~$%.2f | SL=%.2f TP=%.2f | %s',
                     symbol, qty, price, stop_loss or 0, take_profit or 0, strategy_name)

            actual_price = price
            trade = self._log_trade(
                symbol=symbol, action='buy', qty=qty, price=actual_price,
                notional=notional, stop_loss=stop_loss, take_profit=take_profit,
                strategy_name=strategy_name, thesis=thesis, order_id=order.id,
                asset_type='stock',
            )

            self._notify_entry(trade)
            return trade

        except Exception as e:
            log.error('buy_stock %s error: %s', symbol, e)
            return None

    def sell_stock(self, symbol: str, qty: float = None,
                   reason: str = 'manual') -> dict | None:
        """Sell stock position (partial or full)."""
        try:
            if qty is None:
                # Close entire position
                order = self._api.close_position(symbol)
            else:
                order = self._api.submit_order(
                    symbol=symbol,
                    qty=int(qty),
                    side='sell',
                    type='market',
                    time_in_force='day',
                )
            log.info('SELL %s qty=%s reason=%s', symbol, qty or 'all', reason)
            self._mark_closed(symbol, reason)
            return {'symbol': symbol, 'action': 'sell', 'reason': reason}
        except Exception as e:
            log.error('sell_stock %s error: %s', symbol, e)
            return None

    def short_stock(self, symbol: str, notional: float,
                    stop_loss: float = None, take_profit: float = None,
                    strategy_name: str = '', thesis: str = '') -> dict | None:
        """Short sell stock."""
        try:
            snapshot = self.get_snapshot(symbol)
            price = snapshot.get('price', 0)
            if price <= 0:
                return None

            qty = int(notional / price)
            if qty < 1:
                return None

            order_kwargs = dict(
                symbol=symbol,
                qty=qty,
                side='sell',
                type='market',
                time_in_force='day',
            )

            if stop_loss and take_profit:
                order_kwargs['order_class'] = 'bracket'
                order_kwargs['take_profit'] = {'limit_price': str(round(take_profit, 2))}
                order_kwargs['stop_loss']   = {'stop_price':  str(round(stop_loss, 2))}

            order = self._api.submit_order(**order_kwargs)

            log.info('SHORT %s x%d @ ~$%.2f | %s', symbol, qty, price, strategy_name)

            trade = self._log_trade(
                symbol=symbol, action='short', qty=qty, price=price,
                notional=notional, stop_loss=stop_loss, take_profit=take_profit,
                strategy_name=strategy_name, thesis=thesis, order_id=order.id,
                asset_type='stock',
            )
            self._notify_entry(trade)
            return trade

        except Exception as e:
            log.error('short_stock %s error: %s', symbol, e)
            return None

    def close_position(self, symbol: str, reason: str = 'manual') -> None:
        try:
            self._api.close_position(symbol)
            log.info('Closed position: %s | reason: %s', symbol, reason)
            self._mark_closed(symbol, reason)
        except Exception as e:
            log.error('close_position %s error: %s', symbol, e)

    # ── Options orders ────────────────────────────────────────────────────────

    def buy_option(self, occ_symbol: str, qty: int = 1,
                   order_type: str = 'market',
                   strategy_name: str = '', thesis: str = '') -> dict | None:
        """
        Buy an options contract.
        occ_symbol format: SPY260515C00560000
        qty = number of contracts (each = 100 shares)
        """
        try:
            order = self._api.submit_order(
                symbol=occ_symbol,
                qty=qty,
                side='buy',
                type=order_type,
                time_in_force='day',
            )
            log.info('BUY OPTION %s x%d | %s', occ_symbol, qty, strategy_name)

            trade = self._log_trade(
                symbol=occ_symbol, action='buy_option', qty=qty, price=0,
                strategy_name=strategy_name, thesis=thesis, order_id=order.id,
                asset_type='option',
            )
            self._notify_entry(trade)
            return trade

        except Exception as e:
            log.error('buy_option %s error: %s', occ_symbol, e)
            return None

    def sell_option(self, occ_symbol: str, qty: int = 1,
                    order_type: str = 'market',
                    strategy_name: str = '', thesis: str = '') -> dict | None:
        """
        Sell an options contract (to open short position or close long).
        """
        try:
            order = self._api.submit_order(
                symbol=occ_symbol,
                qty=qty,
                side='sell',
                type=order_type,
                time_in_force='day',
            )
            log.info('SELL OPTION %s x%d | %s', occ_symbol, qty, strategy_name)

            trade = self._log_trade(
                symbol=occ_symbol, action='sell_option', qty=qty, price=0,
                strategy_name=strategy_name, thesis=thesis, order_id=order.id,
                asset_type='option',
            )
            self._notify_entry(trade)
            return trade

        except Exception as e:
            log.error('sell_option %s error: %s', occ_symbol, e)
            return None

    # ── Market data ───────────────────────────────────────────────────────────

    def get_snapshot(self, symbol: str) -> dict:
        """Get latest price and quote data for a stock."""
        try:
            snap = self._api.get_snapshot(symbol)
            price = 0.0
            if snap.latest_trade:
                price = float(snap.latest_trade.p)
            elif snap.minute_bar:
                price = float(snap.minute_bar.c)
            elif snap.daily_bar:
                price = float(snap.daily_bar.c)
            return {
                'symbol': symbol,
                'price':  price,
                'minute_bar': {
                    'open':   float(snap.minute_bar.o) if snap.minute_bar else 0,
                    'high':   float(snap.minute_bar.h) if snap.minute_bar else 0,
                    'low':    float(snap.minute_bar.l) if snap.minute_bar else 0,
                    'close':  float(snap.minute_bar.c) if snap.minute_bar else 0,
                    'volume': float(snap.minute_bar.v) if snap.minute_bar else 0,
                } if snap.minute_bar else {},
                'daily_bar': {
                    'open':   float(snap.daily_bar.o) if snap.daily_bar else 0,
                    'high':   float(snap.daily_bar.h) if snap.daily_bar else 0,
                    'low':    float(snap.daily_bar.l) if snap.daily_bar else 0,
                    'close':  float(snap.daily_bar.c) if snap.daily_bar else 0,
                    'volume': float(snap.daily_bar.v) if snap.daily_bar else 0,
                } if snap.daily_bar else {},
            }
        except Exception as e:
            log.debug('get_snapshot %s error: %s', symbol, e)
            return {'symbol': symbol, 'price': 0.0}

    def get_bars(self, symbol: str, timeframe: str = '1Day',
                 limit: int = 100) -> list:
        """Get historical OHLCV bars."""
        try:
            from alpaca_trade_api.rest import TimeFrame
            # Map common strings to Alpaca TimeFrame
            tf_map = {
                '1m': TimeFrame.Minute, '5m': '5Min', '15m': '15Min',
                '1h': TimeFrame.Hour, '4h': '4Hour',
                '1d': TimeFrame.Day, '1D': TimeFrame.Day, '1Day': TimeFrame.Day,
            }
            tf = tf_map.get(timeframe, TimeFrame.Day)
            bars = self._api.get_bars(symbol, tf, limit=limit).df
            result = []
            for ts, row in bars.iterrows():
                result.append({
                    'timestamp': str(ts),
                    'open':   float(row['open']),
                    'high':   float(row['high']),
                    'low':    float(row['low']),
                    'close':  float(row['close']),
                    'volume': float(row['volume']),
                })
            return result
        except Exception as e:
            log.debug('get_bars %s error: %s', symbol, e)
            return []

    def get_options_chain(self, symbol: str, expiry: str = None) -> list:
        """
        Get options chain for an underlying symbol.
        Uses Alpaca Data API v1beta1 options endpoint.
        expiry: 'YYYY-MM-DD' filter (optional)
        """
        try:
            url = f'{_DATA_API}/v1beta1/options/snapshots/{symbol}'
            params = {'feed': 'indicative', 'limit': 100}
            if expiry:
                params['expiration_date'] = expiry
            resp = requests.get(url, headers=_HEADERS, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            snapshots = data.get('snapshots', {})
            chain = []
            for occ_sym, snap_data in snapshots.items():
                greeks = snap_data.get('greeks', {})
                quote  = snap_data.get('latestQuote', {})
                chain.append({
                    'symbol':     occ_sym,
                    'underlying': symbol,
                    'delta':      greeks.get('delta', 0),
                    'gamma':      greeks.get('gamma', 0),
                    'theta':      greeks.get('theta', 0),
                    'vega':       greeks.get('vega', 0),
                    'iv':         snap_data.get('impliedVolatility', 0),
                    'bid':        float(quote.get('bp', 0)),
                    'ask':        float(quote.get('ap', 0)),
                    'mid':        (float(quote.get('bp', 0)) + float(quote.get('ap', 0))) / 2,
                })
            return chain
        except Exception as e:
            log.debug('get_options_chain %s error: %s', symbol, e)
            return []

    def build_occ_symbol(self, underlying: str, expiry: str,
                          option_type: str, strike: float) -> str:
        """
        Build OCC options symbol.
        underlying: 'SPY'
        expiry: 'YYYY-MM-DD'
        option_type: 'call' or 'put'
        strike: 560.0
        Returns: 'SPY260515C00560000'
        """
        from datetime import datetime as _dt
        dt = _dt.strptime(expiry, '%Y-%m-%d')
        date_str = dt.strftime('%y%m%d')
        cp = 'C' if option_type.lower() in ('call', 'c') else 'P'
        # Strike in thousandths, zero-padded to 8 digits
        strike_int = int(round(strike * 1000))
        return f"{underlying.upper()}{date_str}{cp}{strike_int:08d}"

    # ── Orders ────────────────────────────────────────────────────────────────

    def get_open_orders(self) -> list:
        try:
            orders = self._api.list_orders(status='open')
            return [{'id': o.id, 'symbol': o.symbol, 'side': o.side,
                     'qty': o.qty, 'type': o.type} for o in orders]
        except Exception as e:
            log.error('get_open_orders error: %s', e)
            return []

    def cancel_order(self, order_id: str) -> None:
        try:
            self._api.cancel_order(order_id)
        except Exception as e:
            log.error('cancel_order %s error: %s', order_id, e)

    # ── Trade history ─────────────────────────────────────────────────────────

    def _log_trade(self, symbol: str, action: str, qty: float,
                   price: float, strategy_name: str = '',
                   thesis: str = '', notional: float = 0,
                   stop_loss: float = None, take_profit: float = None,
                   order_id: str = '', asset_type: str = 'stock') -> dict:
        # Phase 1: stamp team-context onto the trade. Observation only — no gating.
        try:
            ctx = load_context()
            ctx_fields = snapshot_for_trade(ctx, symbol, action)
        except Exception as e:
            log.warning('team-context snapshot failed: %s', e)
            ctx_fields = {}

        trade = {
            'id':             order_id,
            'symbol':         symbol,
            'action':         action,
            'asset_type':     asset_type,
            'qty':            qty,
            'price':          price,
            'notional':       notional or round(qty * price, 2),
            'stop_loss':      stop_loss,
            'take_profit':    take_profit,
            'strategy_name':  strategy_name,
            'thesis':         thesis,
            'status':         'open',
            'pnl':            0.0,
            'opened_at':      datetime.now(timezone.utc).isoformat(),
            'closed_at':      None,
            'close_reason':   None,
            **ctx_fields,
        }
        history = load_json(TRADE_HISTORY_PATH, [])
        if not isinstance(history, list):
            history = []
        history.append(trade)
        save_json(TRADE_HISTORY_PATH, history)
        return trade

    def _mark_closed(self, symbol: str, reason: str) -> None:
        """Mark the most recent open trade for a symbol as closed."""
        history = load_json(TRADE_HISTORY_PATH, [])
        if not isinstance(history, list):
            return
        now = datetime.now(timezone.utc).isoformat()
        closed_trade = None
        exit_price   = 0.0
        for trade in reversed(history):
            if trade.get('symbol') == symbol and trade.get('status') == 'open':
                entry = float(trade.get('price', 0))
                exit_price = entry
                try:
                    positions = {p['symbol']: p for p in self.get_positions()}
                    if symbol not in positions:
                        snap = self.get_snapshot(symbol)
                        current = snap.get('price', entry)
                        exit_price = current or entry
                        qty = float(trade.get('qty', 0))
                        if trade.get('action') in ('buy',):
                            trade['pnl'] = round((current - entry) * qty, 2)
                        elif trade.get('action') == 'short':
                            trade['pnl'] = round((entry - current) * qty, 2)
                except Exception:
                    pass
                trade['status']       = 'closed'
                trade['closed_at']    = now
                trade['close_reason'] = reason
                closed_trade = trade
                break
        save_json(TRADE_HISTORY_PATH, history)
        if closed_trade:
            try:
                self._notify_exit(closed_trade, exit_price)
            except Exception as e:
                log.error('exit notify error: %s', e)
            try:
                self._append_learning_log(closed_trade, exit_price, reason)
            except Exception as e:
                log.warning('learning-log append failed: %s', e)

    @staticmethod
    def _append_learning_log(trade: dict, exit_price: float, reason: str) -> None:
        """Phase 1: append a context-tagged closed trade to the learning dataset.
        Not read by any trading logic — pure observation for later analysis."""
        record = {
            'trade_id':                  trade.get('id'),
            'symbol':                    trade.get('symbol'),
            'action':                    trade.get('action'),
            'asset_type':                trade.get('asset_type'),
            'qty':                       trade.get('qty'),
            'entry_price':               trade.get('price'),
            'exit_price':                exit_price,
            'opened_at':                 trade.get('opened_at'),
            'closed_at':                 trade.get('closed_at'),
            'close_reason':              reason,
            'pnl':                       trade.get('pnl'),
            'strategy_name':             trade.get('strategy_name'),
            'regime_at_entry':           trade.get('regime_at_entry', 'unknown'),
            'strategist_bias_at_entry':  trade.get('strategist_bias_at_entry', 'neutral'),
            'lens_bias_at_entry':        trade.get('lens_bias_at_entry', 'neutral'),
            'lens_confidence_at_entry':  trade.get('lens_confidence_at_entry'),
            'lens_overall_at_entry':     trade.get('lens_overall_at_entry'),
            'strategist_aligned':        trade.get('strategist_aligned', False),
            'norman_verdict_at_entry':   trade.get('norman_verdict_at_entry', 'UNKNOWN'),
            'norman_ruin_prob_at_entry': trade.get('norman_ruin_prob_at_entry'),
            'norman_dated':              trade.get('norman_dated'),
        }
        try:
            try:
                with open(LEARNING_LOG_PATH) as f:
                    store = json.load(f)
            except Exception:
                store = {'records': [], 'phase': 1,
                         'note': 'observation-only; no trading logic reads this file'}
            store.setdefault('records', []).append(record)
            with open(LEARNING_LOG_PATH, 'w') as f:
                json.dump(store, f, indent=2)
        except Exception as e:
            log.warning('learning-log write failed: %s', e)

    # ── Notifications ─────────────────────────────────────────────────────────

    @staticmethod
    def _fill_side_and_direction(action: str) -> tuple[str, str]:
        """Map an internal action verb to (order_side, position_direction)."""
        a = (action or '').lower()
        if a in ('buy', 'buy_option'):
            return 'BUY', 'LONG'
        if a in ('short',):
            return 'SELL', 'SHORT'
        if a in ('sell', 'close_long'):
            return 'SELL', 'LONG'
        if a in ('cover', 'close_short'):
            return 'BUY', 'SHORT'
        if a in ('sell_option',):
            return 'SELL', 'SHORT'
        return action.upper(), '?'

    def _notify_entry(self, trade: dict) -> None:
        if not trade:
            return
        balance  = self.get_balance()
        sym      = trade.get('symbol', '?')
        qty      = trade.get('qty', 0)
        price    = trade.get('price', 0)
        strat    = trade.get('strategy_name') or 'HOLD_MANAGE'
        is_opt   = trade.get('asset_type') == 'option'

        side, direction = self._fill_side_and_direction(trade.get('action', ''))
        size_str = (f"{int(qty)} contracts" if is_opt
                    else f"{int(qty)} shares")

        lines = [
            f"🤖 JERRY — {side} {sym}",
            f"Type: {'Option' if is_opt else 'Stock'}",
            f"Direction: {direction}",
            f"Size: {size_str}",
            f"Entry: ${price:.2f}",
            f"Strategy signal: {strat}",
            f"Account balance: ${balance:,.2f}",
        ]
        send_telegram('\n'.join(lines))

    def _notify_exit(self, trade: dict, exit_price: float) -> None:
        if not trade:
            return
        balance = self.get_balance()
        sym     = trade.get('symbol', '?')
        qty     = trade.get('qty', 0)
        is_opt  = trade.get('asset_type') == 'option'

        # Closing a long = SELL, closing a short = BUY. Direction = original position side.
        _, direction = self._fill_side_and_direction(trade.get('action', ''))
        side = 'SELL' if direction == 'LONG' else 'BUY'
        size_str = (f"{int(qty)} contracts" if is_opt
                    else f"{int(qty)} shares")

        lines = [
            f"🤖 JERRY — {side} {sym}",
            f"Type: {'Option' if is_opt else 'Stock'}",
            f"Direction: {direction}",
            f"Size: {size_str}",
            f"Entry: ${exit_price:.2f}",
            f"Strategy signal: {trade.get('close_reason') or 'HOLD_MANAGE'}",
            f"Account balance: ${balance:,.2f}",
        ]
        send_telegram('\n'.join(lines))
