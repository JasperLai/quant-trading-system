#!/usr/bin/env python3
"""主流策略信号与回测支持测试。"""

import unittest

from backtest.engine import BacktestEngine
from backend.services.strategy_manager import StrategyManager, strategy_supports_backtest
from backend.strategies.signals.indicator_signals import (
    BollingerReversionSignal,
    DonchianBreakoutSignal,
    MacdTrendSignal,
    RsiReversionSignal,
)


def make_bar(code, close, index):
    day = index + 1
    return {
        'code': code,
        'time_key': f'2026-01-{day:02d} 00:00:00',
        'open': close,
        'high': close,
        'low': close,
        'close': close,
        'volume': 1000 + index,
    }


class PopularStrategiesTest(unittest.TestCase):
    def test_strategy_registry_contains_new_backtest_strategies(self):
        manager = StrategyManager()
        names = set(manager.list_strategies())
        self.assertTrue({'rsi_reversion', 'bollinger_reversion', 'macd_trend', 'donchian_breakout'}.issubset(names))
        self.assertTrue(strategy_supports_backtest('rsi_reversion'))
        self.assertTrue(strategy_supports_backtest('bollinger_reversion'))
        self.assertTrue(strategy_supports_backtest('macd_trend'))
        self.assertTrue(strategy_supports_backtest('donchian_breakout'))

    def test_rsi_signal_generates_buy_and_sell(self):
        code = 'HK.03690'
        signal = RsiReversionSignal(codes=[code], order_qty=100, rsi_period=3, oversold=40, overbought=60)
        closes = [100, 96, 92, 90, 94, 100, 106]
        actions = []
        position_qty = 0
        for index, close in enumerate(closes):
            bar = make_bar(code, close, index)
            signal.update_bar(bar)
            decision = signal.evaluate_quote({'code': code, 'last_price': close, 'time_key': bar['time_key']}, position_qty=position_qty)
            if decision and decision['action'] == 'BUY':
                position_qty = decision['qty']
                signal.clear_pending_buy(code, decision['qty'])
                actions.append('BUY')
            elif decision and decision['action'] == 'SELL':
                position_qty = 0
                signal.clear_pending_sell(code, decision['qty'])
                actions.append('SELL')
        self.assertIn('BUY', actions)
        self.assertIn('SELL', actions)

    def test_macd_backtest_runs_with_trades(self):
        code = 'HK.03690'
        signal = MacdTrendSignal(codes=[code], order_qty=100, macd_fast=2, macd_slow=4, macd_signal=2)
        bars_by_code = {
            code: [
                make_bar(code, close, index)
                for index, close in enumerate([20, 19, 18, 17, 16, 15, 16, 17, 18, 19, 20, 21, 20, 19, 18, 17])
            ]
        }
        result = BacktestEngine(signal=signal, initial_cash=100000, commission_rate=0, slippage=0).run(bars_by_code)
        self.assertEqual('macd_trend', result['summary']['strategy'])
        self.assertGreaterEqual(result['summary']['trade_count'], 2)

    def test_donchian_and_bollinger_load_via_manager(self):
        manager = StrategyManager()
        donchian = manager.load_signal('donchian_breakout', codes=['HK.03690'], donchian_entry=10, donchian_exit=5)
        bollinger = manager.load_signal('bollinger_reversion', codes=['HK.03690'], bollinger_period=10, stddev_multiplier=1.8)
        self.assertIsInstance(donchian, DonchianBreakoutSignal)
        self.assertIsInstance(bollinger, BollingerReversionSignal)
        self.assertEqual(10, donchian.donchian_entry)
        self.assertEqual(1.8, bollinger.stddev_multiplier)


if __name__ == '__main__':
    unittest.main()
