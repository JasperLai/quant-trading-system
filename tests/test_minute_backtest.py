#!/usr/bin/env python3
"""分钟级回测引擎测试。"""

import unittest

from backtest.engine import MinuteBacktestEngine
from backend.services.strategy_manager import (
    StrategyManager,
    get_backtest_engine_name,
    get_backtest_ktype,
    strategy_supports_backtest,
)


def make_minute_bar(code, time_key, open_price, high, low, close, volume=1000):
    return {
        'code': code,
        'time_key': time_key,
        'open': open_price,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume,
    }


class MinuteBacktestTest(unittest.TestCase):
    def test_intraday_strategy_supports_minute_backtest(self):
        self.assertTrue(strategy_supports_backtest('intraday_breakout_test'))
        self.assertEqual('minute', get_backtest_engine_name('intraday_breakout_test'))
        self.assertEqual('K_1M', get_backtest_ktype('intraday_breakout_test'))

    def test_minute_engine_runs_intraday_breakout_signal(self):
        manager = StrategyManager()
        signal = manager.load_signal(
            'intraday_breakout_test',
            codes=['HK.03690'],
            order_qty=100,
            breakout_pct=0.004,
            pullback_pct=0.002,
            stop_loss_pct=0.01,
            entry_start_time='09:45:00',
            flat_time='15:45:00',
            min_hold_minutes=0,
            max_trades_per_day=3,
            reentry_cooldown_minutes=0,
        )
        bars_by_code = {
            'HK.03690': [
                make_minute_bar('HK.03690', '2026-04-14 09:31:00', 100.0, 100.0, 100.0, 100.0),
                make_minute_bar('HK.03690', '2026-04-14 09:45:00', 100.0, 100.2, 100.0, 100.1),
                make_minute_bar('HK.03690', '2026-04-14 09:46:00', 100.1, 100.8, 100.1, 100.6),
                make_minute_bar('HK.03690', '2026-04-14 09:47:00', 100.6, 101.3, 100.5, 101.1),
                make_minute_bar('HK.03690', '2026-04-14 09:48:00', 101.1, 101.1, 100.6, 100.8),
            ]
        }
        result = MinuteBacktestEngine(signal=signal, initial_cash=100000, commission_rate=0, slippage=0).run(bars_by_code)
        sides = [trade['side'] for trade in result['trades']]
        self.assertEqual(['BUY', 'SELL'], sides)
        self.assertEqual(5, len(result['equity_curve']))
        self.assertEqual('intraday_breakout_test', result['summary']['strategy'])
