#!/usr/bin/env python3
"""把现有 signal 适配到 Zipline handle_data。"""

from datetime import time as time_cls

import pandas as pd

from backend.core.config import STOP_LOSS_PCT, TAKE_PROFIT_PCT


class ZiplineStrategyAdapter:
    def __init__(
        self,
        signal,
        prepared_bundle,
        data_frequency='daily',
        commission_rate=0.001,
        slippage=0.0,
        stop_loss_pct=STOP_LOSS_PCT,
        take_profit_pct=TAKE_PROFIT_PCT,
    ):
        self.signal = signal
        self.prepared_bundle = prepared_bundle
        self.data_frequency = data_frequency
        self.commission_rate = commission_rate
        self.slippage = slippage
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self._code_by_symbol = {symbol: code for code, symbol in prepared_bundle.symbol_map.items()}

    def initialize(self, context):
        from zipline.api import set_benchmark, set_commission, set_slippage, symbol
        from zipline.finance.commission import PerDollar
        from zipline.finance.slippage import FixedSlippage

        context.assets = {
            code: symbol(zipline_symbol)
            for code, zipline_symbol in self.prepared_bundle.symbol_map.items()
        }
        context.previous_close = {}
        context.session_open = {}
        set_commission(PerDollar(cost=self.commission_rate))
        set_slippage(FixedSlippage(spread=self.slippage * 2))
        first_asset = next(iter(context.assets.values()))
        set_benchmark(first_asset)

    def _local_time(self, dt):
        ts = pd.Timestamp(dt)
        if ts.tzinfo is None:
            ts = ts.tz_localize('UTC')
        return ts.tz_convert('Asia/Hong_Kong').tz_localize(None)

    @staticmethod
    def _time_key(local_dt):
        return local_dt.strftime('%Y-%m-%d %H:%M:%S')

    def _build_event(self, code, bar, local_dt):
        time_key = self._time_key(local_dt)
        return {
            'code': code,
            'time_key': time_key,
            'open': float(bar['open']),
            'high': float(bar['high']),
            'low': float(bar['low']),
            'close': float(bar['close']),
            'volume': float(bar.get('volume', 0.0)),
        }

    def _build_quote_payload(self, code, bar, local_dt, context):
        time_key = self._time_key(local_dt)
        session_date = local_dt.strftime('%Y-%m-%d')
        session_time = local_dt.strftime('%H:%M:%S')
        if self.data_frequency == 'daily':
            session_open = float(bar['open'])
        else:
            session_open = context.session_open.setdefault(code, float(bar['open']))

        return {
            'code': code,
            'last_price': float(bar['close']),
            'high_price': float(bar['high']),
            'time_key': time_key,
            'open_price': session_open,
            'prev_close_price': context.previous_close.get(code),
            'data_date': session_date,
            'data_time': session_time,
            'volume': float(bar.get('volume', 0.0)),
        }

    def _position_info(self, context, asset):
        position = context.portfolio.positions[asset]
        qty = abs(int(position.amount))
        if qty == 0:
            return 0, None
        return qty, {
            'qty': qty,
            'entry': float(position.cost_basis),
            'entry_time': None,
        }

    def _risk_exit(self, context, asset, code, current_price, time_key):
        from zipline.api import order_target

        qty, position_info = self._position_info(context, asset)
        if qty <= 0 or not position_info:
            return False
        entry = position_info['entry']
        if current_price <= entry * (1 - self.stop_loss_pct):
            order_target(asset, 0)
            self.signal.clear_pending_sell(code, qty)
            return True
        if current_price >= entry * (1 + self.take_profit_pct):
            order_target(asset, 0)
            self.signal.clear_pending_sell(code, qty)
            return True
        return False

    def handle_data(self, context, data):
        from zipline.api import get_datetime, order, order_target, record

        local_dt = self._local_time(get_datetime())
        latest_prices = {}

        for code, asset in context.assets.items():
            if not data.can_trade(asset):
                continue

            bar = {
                'open': data.current(asset, 'open'),
                'high': data.current(asset, 'high'),
                'low': data.current(asset, 'low'),
                'close': data.current(asset, 'close'),
                'volume': data.current(asset, 'volume'),
            }
            if any(value is None for value in bar.values()):
                continue

            event = self._build_event(code, bar, local_dt)
            self.signal.update_bar(event)
            latest_prices[code] = float(bar['close'])

            position_qty, position_info = self._position_info(context, asset)
            decision = self.signal.evaluate_quote(
                self._build_quote_payload(code, bar, local_dt, context),
                position_qty=position_qty,
                position_info=position_info,
            )

            if decision and decision['action'] == 'BUY':
                order(asset, int(decision['qty']))
                self.signal.clear_pending_buy(code, decision['qty'])
            elif decision and decision['action'] == 'SELL':
                order_target(asset, 0)
                self.signal.clear_pending_sell(code, decision['qty'])
            else:
                self._risk_exit(context, asset, code, float(bar['close']), event['time_key'])

            context.previous_close[code] = float(bar['close'])

        record(portfolio_value=context.portfolio.portfolio_value, cash=context.portfolio.cash)
