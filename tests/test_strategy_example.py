import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


class FakeFrame:
    def __init__(self, records):
        self._records = list(records)

    def to_dict(self, orient):
        if orient != 'records':
            raise ValueError(f'Unsupported orient: {orient}')
        return list(self._records)

    def __len__(self):
        return len(self._records)


class FakeOpenQuoteContext:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.handlers = []
        self.subscriptions = []

    def set_handler(self, handler):
        self.handlers.append(handler)
        return 0

    def subscribe(self, codes, subtypes):
        self.subscriptions.append((list(codes), list(subtypes)))
        return 0, None

    def get_cur_kline(self, code, num, ktype):
        records = []
        base = 100.0
        for idx in range(num):
            records.append({
                'code': code,
                'close': base + idx,
                'time_key': f'2026-01-{idx + 1:02d} 00:00:00',
            })
        return 0, FakeFrame(records)

    def get_global_state(self):
        return 0, {'server_ver': 'test', 'qot_logined': '1'}

    def stop(self):
        return None

    def close(self):
        return None


class FakeStockQuoteHandlerBase:
    def on_recv_rsp(self, rsp_pb):
        return 0, rsp_pb


class FakeMonitor:
    def __init__(self):
        self.positions = {}
        self.add_calls = []
        self.tick_calls = []

    def add_position(self, **kwargs):
        self.positions[kwargs['code']] = kwargs
        self.add_calls.append(kwargs)

    def get_position_info(self, code):
        return self.positions.get(code)

    def on_tick(self, code, price):
        self.tick_calls.append((code, price))
        return None


class StrategyExampleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake_signal_sender = types.ModuleType('signal_sender')
        cls.fake_signal_sender.calls = []

        def send_signal(code, action, price, quantity, note=''):
            cls.fake_signal_sender.calls.append((code, action, price, quantity, note))

        cls.fake_signal_sender.send_signal = send_signal

        cls.fake_position_monitor = types.ModuleType('position_monitor')
        cls.fake_position_monitor.PositionMonitor = FakeMonitor

        futu = types.ModuleType('futu')
        futu.RET_OK = 0
        futu.RET_ERROR = -1
        futu.OpenQuoteContext = FakeOpenQuoteContext
        futu.StockQuoteHandlerBase = FakeStockQuoteHandlerBase
        futu.SubType = types.SimpleNamespace(K_DAY='K_DAY', QUOTE='QUOTE')
        futu.KLType = types.SimpleNamespace(K_DAY='K_DAY')

        sys.modules['futu'] = futu
        sys.modules['signal_sender'] = cls.fake_signal_sender
        sys.modules['position_monitor'] = cls.fake_position_monitor

        path = Path('/Users/mubinlai/code/quant-trading-system/scripts/strategy_example.py')
        spec = importlib.util.spec_from_file_location('strategy_example_under_test', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.module = module

    def setUp(self):
        self.fake_signal_sender.calls.clear()

    def make_strategy(self):
        strategy = self.module.MaCrossStrategy(codes=['HK.00700'], short_ma=5, long_ma=20)
        return strategy

    def seed_history(self, strategy):
        code = 'HK.00700'
        strategy.prices[code] = [10.0] * 19 + [9.0]
        strategy.last_short_ma[code] = strategy.calculate_ma(strategy.prices[code], strategy.short_ma_period)
        strategy.last_long_ma[code] = strategy.calculate_ma(strategy.prices[code], strategy.long_ma_period)
        return code

    def test_start_registers_quote_handler_and_quote_subscription(self):
        strategy = self.make_strategy()

        with mock.patch.object(self.module.time, 'sleep', side_effect=KeyboardInterrupt):
            strategy.start()

        self.assertEqual(1, len(strategy.quote_ctx.handlers))
        self.assertIsInstance(strategy.quote_ctx.handlers[0], self.module.QuoteHandler)
        self.assertEqual(
            [(['HK.00700'], ['QUOTE'])],
            strategy.quote_ctx.subscriptions,
        )

    def test_on_quote_uses_live_price_to_trigger_buy(self):
        strategy = self.make_strategy()
        code = self.seed_history(strategy)

        strategy.on_quote({'code': code, 'last_price': 20.0})

        self.assertEqual(1, len(self.fake_signal_sender.calls))
        self.assertEqual((code, 'BUY', 20.0, 100, '均线金叉买入'), self.fake_signal_sender.calls[0])
        self.assertEqual(1, len(strategy.monitor.add_calls))
        self.assertEqual((code, 20.0), strategy.monitor.tick_calls[-1])
        self.assertGreater(strategy.last_short_ma[code], strategy.last_long_ma[code])

    def test_on_quote_does_not_rebuy_when_position_exists(self):
        strategy = self.make_strategy()
        code = self.seed_history(strategy)
        strategy.monitor.positions[code] = {'qty': 100}

        strategy.on_quote({'code': code, 'last_price': 20.0})

        self.assertEqual([], self.fake_signal_sender.calls)
        self.assertEqual([], strategy.monitor.add_calls)
        self.assertEqual([(code, 20.0)], strategy.monitor.tick_calls)


if __name__ == '__main__':
    unittest.main()
