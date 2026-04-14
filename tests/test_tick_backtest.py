#!/usr/bin/env python3
"""Tick 级回测引擎测试。"""

import unittest

from backtest.engine import TickBacktestEngine
from backend.services.strategy_manager import StrategyManager, get_backtest_modes


def make_tick(code, time_key, price, open_price=100.0, prev_close_price=99.8, volume=100):
    return {
        'code': code,
        'time_key': time_key,
        'price': price,
        'open_price': open_price,
        'prev_close_price': prev_close_price,
        'volume': volume,
    }


class TickBacktestEngineTest(unittest.TestCase):
    def test_intraday_strategy_declares_tick_mode_support(self):
        self.assertIn('tick', get_backtest_modes('intraday_breakout_test'))

    def test_tick_engine_can_drive_intraday_signal(self):
        manager = StrategyManager()
        signal = manager.load_signal(
            'intraday_breakout_test',
            codes=['HK.03690'],
            order_qty=100,
            breakout_pct=0.003,
            pullback_pct=0.002,
            entry_start_time='09:45:00',
            flat_time='15:45:00',
        )
        ticks_by_code = {
            'HK.03690': [
                make_tick('HK.03690', '2026-04-14 09:44:59', 100.00),
                make_tick('HK.03690', '2026-04-14 09:45:01', 100.35),
                make_tick('HK.03690', '2026-04-14 09:45:10', 100.60),
                make_tick('HK.03690', '2026-04-14 09:45:20', 100.38),
            ]
        }
        result = TickBacktestEngine(
            signal=signal,
            initial_cash=100000,
            commission_rate=0,
            slippage=0,
        ).run(ticks_by_code)
        self.assertEqual(['BUY', 'SELL'], [trade['side'] for trade in result['trades']])
        self.assertEqual(4, len(result['equity_curve']))
        self.assertEqual('intraday_breakout_test', result['summary']['strategy'])

