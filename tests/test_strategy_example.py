import importlib.util
import importlib
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path('/Users/mubinlai/code/quant-trading-system')


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

    def subscribe(self, codes, subtypes, **kwargs):
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

    def request_history_kline(self, **kwargs):
        return 0, FakeFrame([]), None

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
        self.remove_calls = []
        self.tick_calls = []

    def add_position(self, **kwargs):
        normalized = {
            'qty': kwargs['qty'],
            'entry': kwargs['entry_price'],
            'stop': kwargs['stop_loss'],
            'profit': kwargs['take_profit'],
            'stop_pct': kwargs.get('stop_loss_pct', -0.20),
            'profit_pct': kwargs.get('take_profit_pct', 0.30),
            'reason': kwargs.get('reason'),
            'entry_time': kwargs.get('entry_time'),
        }
        self.positions[kwargs['code']] = normalized
        self.add_calls.append(kwargs)

    def get_position_info(self, code):
        return self.positions.get(code)

    def get_all_positions(self):
        return dict(self.positions)

    def remove_position(self, code):
        self.positions.pop(code, None)
        self.remove_calls.append(code)

    def on_tick(self, code, price):
        self.tick_calls.append((code, price))
        return None


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class StrategyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake_signal_sender = types.ModuleType('signal_sender')
        cls.fake_signal_sender.calls = []

        def send_signal(code, action, price, quantity, note=''):
            cls.fake_signal_sender.calls.append((code, action, price, quantity, note))

        def send_agent_message(message, log_prefix='消息'):
            cls.fake_signal_sender.calls.append(('AGENT', log_prefix, message))

        cls.fake_signal_sender.send_signal = send_signal
        cls.fake_signal_sender.send_agent_message = send_agent_message

        cls.fake_position_monitor = types.ModuleType('position_monitor')
        cls.fake_position_monitor.PositionMonitor = FakeMonitor

        futu = types.ModuleType('futu')
        futu.RET_OK = 0
        futu.RET_ERROR = -1
        futu.OpenQuoteContext = FakeOpenQuoteContext
        futu.StockQuoteHandlerBase = FakeStockQuoteHandlerBase
        futu.SubType = types.SimpleNamespace(K_DAY='K_DAY', QUOTE='QUOTE')
        futu.KLType = types.SimpleNamespace(K_DAY='K_DAY')
        futu.AuType = types.SimpleNamespace(QFQ='QFQ')

        sys.modules['futu'] = futu
        sys.modules['backend.integrations.agent.signal_sender'] = cls.fake_signal_sender
        sys.modules['backend.monitoring.position_monitor'] = cls.fake_position_monitor

        sys.path.insert(0, str(ROOT))
        os.environ['QTS_RUNTIME_DB_PATH'] = str(ROOT / 'backend' / 'data' / 'test-runtime.sqlite3')
        cls.signal_module = importlib.import_module('backend.strategies.signals.ma_signal')
        cls.runner_module = importlib.import_module('backend.strategies.runtime.realtime_runner')
        cls.single_module = importlib.import_module('backend.strategies.runtime.single_position')
        cls.pyramiding_module = importlib.import_module('backend.strategies.runtime.pyramiding')
        cls.manager_module = importlib.import_module('backend.services.strategy_manager')
        cls.backtest_engine_module = importlib.import_module('backtest.engine')

    def setUp(self):
        self.fake_signal_sender.calls.clear()

    def seed_history(self, strategy, code='HK.00700'):
        strategy.prices[code] = [10.0] * 19 + [9.0]
        strategy.bar_time_keys[code] = [f'2026-01-{idx + 1:02d} 00:00:00' for idx in range(20)]
        strategy.last_short_ma[code] = strategy.calculate_ma(strategy.prices[code], strategy.short_ma_period)
        strategy.last_long_ma[code] = strategy.calculate_ma(strategy.prices[code], strategy.long_ma_period)
        return code

    def test_on_bar_appends_same_price_when_time_key_changes(self):
        strategy = self.single_module.MaCrossStrategy(codes=['SZ.000001'], short_ma=5, long_ma=10)
        strategy.on_bar({'code': 'SZ.000001', 'time_key': '2026-04-01 00:00:00', 'close': 10.94})
        strategy.on_bar({'code': 'SZ.000001', 'time_key': '2026-04-02 00:00:00', 'close': 10.94})

        self.assertEqual([10.94, 10.94], strategy.prices['SZ.000001'])
        self.assertEqual(
            ['2026-04-01 00:00:00', '2026-04-02 00:00:00'],
            strategy.bar_time_keys['SZ.000001'],
        )

    def test_on_bar_updates_last_value_when_time_key_repeats(self):
        strategy = self.single_module.MaCrossStrategy(codes=['SZ.000001'], short_ma=5, long_ma=10)
        strategy.on_bar({'code': 'SZ.000001', 'time_key': '2026-04-01 00:00:00', 'close': 10.94})
        strategy.on_bar({'code': 'SZ.000001', 'time_key': '2026-04-01 00:00:00', 'close': 10.99})

        self.assertEqual([10.99], strategy.prices['SZ.000001'])
        self.assertEqual(['2026-04-01 00:00:00'], strategy.bar_time_keys['SZ.000001'])

    def test_single_strategy_start_registers_quote_handler_and_subscriptions(self):
        strategy = self.single_module.MaCrossStrategy(codes=['HK.00700'], short_ma=5, long_ma=20)

        with mock.patch.object(self.runner_module.time, 'sleep', side_effect=KeyboardInterrupt):
            strategy.start()

        self.assertEqual(1, len(strategy.quote_ctx.handlers))
        self.assertIsInstance(strategy.quote_ctx.handlers[0], self.runner_module.QuoteHandler)
        self.assertEqual(
            [(['HK.00700'], ['K_DAY']), (['HK.00700'], ['QUOTE'])],
            strategy.quote_ctx.subscriptions,
        )

    def test_single_strategy_buy_creates_pending_only(self):
        strategy = self.single_module.MaCrossStrategy(codes=['HK.00700'], short_ma=5, long_ma=20)
        code = self.seed_history(strategy)

        strategy.on_quote({'code': code, 'last_price': 20.0})

        self.assertEqual(1, len(self.fake_signal_sender.calls))
        self.assertEqual([], strategy.monitor.add_calls)
        self.assertIn(code, strategy.pending_buys)

    def test_single_strategy_confirm_position_registers_monitor(self):
        strategy = self.single_module.MaCrossStrategy(codes=['HK.00700'], short_ma=5, long_ma=20)
        code = self.seed_history(strategy)
        strategy.pending_buys.add(code)

        strategy.confirm_position(code=code, qty=100, entry_price=20.0)

        self.assertNotIn(code, strategy.pending_buys)
        self.assertEqual(1, len(strategy.monitor.add_calls))

    def test_single_strategy_dead_cross_creates_pending_sell_only(self):
        strategy = self.single_module.MaCrossStrategy(codes=['HK.00700'], short_ma=5, long_ma=20)
        code = 'HK.00700'
        strategy.prices[code] = [10.0] * 19 + [11.0]
        strategy.bar_time_keys[code] = [f'2026-01-{idx + 1:02d} 00:00:00' for idx in range(20)]
        strategy.last_short_ma[code] = strategy.calculate_ma(strategy.prices[code], strategy.short_ma_period)
        strategy.last_long_ma[code] = strategy.calculate_ma(strategy.prices[code], strategy.long_ma_period)
        strategy.monitor.positions[code] = {'qty': 100}

        strategy.on_quote({'code': code, 'last_price': 1.0})

        self.assertEqual(('HK.00700', 'SELL', 1.0, 100, '均线死叉卖出'), self.fake_signal_sender.calls[0])
        self.assertIn(code, strategy.pending_sells)

    def test_confirm_exit_clears_pending_sell_and_removes_position(self):
        strategy = self.single_module.MaCrossStrategy(codes=['HK.00700'], short_ma=5, long_ma=20)
        code = 'HK.00700'
        strategy.pending_sells.add(code)
        strategy.monitor.positions[code] = {'qty': 100}

        strategy.confirm_exit(code=code, qty=100, exit_price=19.0)

        self.assertNotIn(code, strategy.pending_sells)
        self.assertEqual([code], strategy.monitor.remove_calls)

    def test_process_control_commands_handles_confirm_buy_and_sell(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'runtime.sqlite3'
            repository = importlib.import_module('backend.repositories.runtime_repository').RuntimeRepository(db_path=db_path)
            repository.upsert_run(
                run_id='run-test',
                strategy_name='single_position_ma',
                config={},
                pid=1234,
                status='running',
            )
            repository.enqueue_command('run-test', 'confirm_buy', {'action': 'confirm_buy', 'code': 'HK.00700', 'qty': 100, 'entry_price': 20.0})
            repository.enqueue_command('run-test', 'confirm_sell', {'action': 'confirm_sell', 'code': 'HK.00700', 'qty': 100, 'exit_price': 21.5})
            strategy = self.single_module.MaCrossStrategy(
                codes=['HK.00700'],
                short_ma=5,
                long_ma=20,
                run_id='run-test',
                db_path=str(db_path),
            )

            strategy.process_control_commands()

            self.assertEqual(1, len(strategy.monitor.add_calls))
            self.assertEqual(['HK.00700'], strategy.monitor.remove_calls)
            executions = repository.list_executions('run-test')
            self.assertEqual(2, len(executions))
            self.assertEqual('BUY', executions[0]['side'])
            self.assertEqual(20.0, executions[0]['price'])
            self.assertEqual('SELL', executions[1]['side'])
            self.assertEqual(21.5, executions[1]['price'])

    def test_process_control_commands_keeps_failed_command_pending(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'runtime.sqlite3'
            repository = importlib.import_module('backend.repositories.runtime_repository').RuntimeRepository(db_path=db_path)
            repository.upsert_run(
                run_id='run-fail',
                strategy_name='single_position_ma',
                config={},
                pid=1234,
                status='running',
            )
            repository.enqueue_command('run-fail', 'confirm_buy', {'action': 'confirm_buy', 'code': 'HK.00700', 'qty': 100})
            strategy = self.single_module.MaCrossStrategy(
                codes=['HK.00700'],
                short_ma=5,
                long_ma=20,
                run_id='run-fail',
                db_path=str(db_path),
            )

            strategy.process_control_commands()

            pending = repository.fetch_pending_commands('run-fail')
            self.assertEqual(1, len(pending))
            self.assertEqual('HK.00700', pending[0]['code'])

    def test_pyramiding_strategy_respects_max_position(self):
        strategy = self.pyramiding_module.PyramidingMaCrossStrategy(
            codes=['HK.00700'],
            short_ma=5,
            long_ma=20,
            order_qty=100,
            max_position_per_stock=300,
        )
        code = self.seed_history(strategy)
        strategy.monitor.positions[code] = {'qty': 200}
        strategy.pending_buys[code] = 100

        strategy.on_quote({'code': code, 'last_price': 20.0})

        self.assertEqual([], self.fake_signal_sender.calls)

    def test_pyramiding_strategy_allows_incremental_buy_under_cap(self):
        strategy = self.pyramiding_module.PyramidingMaCrossStrategy(
            codes=['HK.00700'],
            short_ma=5,
            long_ma=20,
            order_qty=100,
            max_position_per_stock=300,
        )
        code = self.seed_history(strategy)
        strategy.monitor.positions[code] = {'qty': 100}

        strategy.on_quote({'code': code, 'last_price': 20.0})

        self.assertEqual(1, len(self.fake_signal_sender.calls))
        self.assertEqual(100, strategy.pending_buys[code])

    def test_pyramiding_confirm_position_reduces_pending_qty(self):
        strategy = self.pyramiding_module.PyramidingMaCrossStrategy(
            codes=['HK.00700'],
            short_ma=5,
            long_ma=20,
            order_qty=100,
            max_position_per_stock=300,
        )
        code = self.seed_history(strategy)
        strategy.pending_buys[code] = 200

        strategy.confirm_position(code=code, qty=100, entry_price=20.0)

        self.assertEqual(100, strategy.pending_buys[code])
        self.assertEqual(1, len(strategy.monitor.add_calls))

    def test_strategy_manager_loads_registered_strategy(self):
        manager = self.manager_module.StrategyManager()
        strategy = manager.load_strategy('pyramiding_ma', codes=['HK.00700'], max_position_per_stock=400)

        self.assertIsInstance(strategy, self.pyramiding_module.PyramidingMaCrossStrategy)
        self.assertEqual(400, strategy.max_position_per_stock)
        self.assertIn('pyramiding_ma', manager.instances)

    def test_strategy_manager_loads_signal_for_backtest(self):
        manager = self.manager_module.StrategyManager()
        signal = manager.load_signal('single_position_ma', codes=['SZ.000001'], short_ma=3, long_ma=6)

        self.assertIsInstance(signal, self.signal_module.SinglePositionMaSignal)
        self.assertEqual(3, signal.short_ma_period)
        self.assertEqual(6, signal.long_ma_period)

    def test_backtest_engine_can_open_and_close_position(self):
        signal = self.signal_module.SinglePositionMaSignal(codes=['SZ.000001'], short_ma=2, long_ma=3, order_qty=100)
        engine = self.backtest_engine_module.BacktestEngine(
            signal=signal,
            initial_cash=100000.0,
            commission_rate=0.0,
            slippage=0.0,
            take_profit_pct=0.05,
        )
        bars_by_code = {
            'SZ.000001': [
                {'code': 'SZ.000001', 'time_key': '2026-01-01 00:00:00', 'close': 10.0},
                {'code': 'SZ.000001', 'time_key': '2026-01-02 00:00:00', 'close': 10.0},
                {'code': 'SZ.000001', 'time_key': '2026-01-03 00:00:00', 'close': 9.0},
                {'code': 'SZ.000001', 'time_key': '2026-01-04 00:00:00', 'close': 12.0},
                {'code': 'SZ.000001', 'time_key': '2026-01-05 00:00:00', 'close': 13.0},
            ]
        }

        result = engine.run(bars_by_code)

        self.assertEqual(2, len(result['trades']))
        self.assertEqual('BUY', result['trades'][0]['side'])
        self.assertEqual('SELL', result['trades'][1]['side'])
        self.assertEqual('TAKE_PROFIT', result['trades'][1]['reason'])
        self.assertEqual({}, result['open_positions'])
        self.assertGreater(result['summary']['final_equity'], result['summary']['initial_cash'])

    def test_backtest_engine_does_not_clear_pending_sell_when_no_position_closed(self):
        class StubSignal:
            strategy_name = 'stub'

            def __init__(self):
                self.pending_sell_cleared = False

            def update_bar(self, event):
                return event

            def evaluate_quote(self, quote_data, position_qty=0):
                return {'action': 'SELL', 'qty': 100, 'reason': 'stub sell'}

            def clear_pending_sell(self, code, qty=None):
                self.pending_sell_cleared = True

            def clear_pending_buy(self, code, qty=None):
                return None

        signal = StubSignal()
        engine = self.backtest_engine_module.BacktestEngine(
            signal=signal,
            initial_cash=100000.0,
            commission_rate=0.0,
            slippage=0.0,
        )
        result = engine.run({'SZ.000001': [{'code': 'SZ.000001', 'time_key': '2026-01-01 00:00:00', 'close': 10.0}]})

        self.assertFalse(signal.pending_sell_cleared)
        self.assertEqual([], result['trades'])

    def test_sync_runtime_state_skips_duplicate_writes(self):
        strategy = self.single_module.MaCrossStrategy(
            codes=['HK.00700'],
            short_ma=5,
            long_ma=20,
            run_id='run-sync',
            db_path=str(ROOT / 'backend' / 'data' / 'test-runtime.sqlite3'),
        )
        strategy.repository.replace_positions = mock.Mock()
        strategy.repository.replace_pending_orders = mock.Mock()

        strategy.sync_runtime_state()
        strategy.sync_runtime_state()

        self.assertEqual(1, strategy.repository.replace_positions.call_count)
        self.assertEqual(1, strategy.repository.replace_pending_orders.call_count)

    def test_backtest_engine_can_exit_on_dead_cross(self):
        signal = self.signal_module.SinglePositionMaSignal(codes=['SZ.000001'], short_ma=2, long_ma=3, order_qty=100)
        engine = self.backtest_engine_module.BacktestEngine(
            signal=signal,
            initial_cash=100000.0,
            commission_rate=0.0,
            slippage=0.0,
            stop_loss_pct=-0.50,
            take_profit_pct=0.30,
        )
        bars_by_code = {
            'SZ.000001': [
                {'code': 'SZ.000001', 'time_key': '2026-01-01 00:00:00', 'close': 10.0},
                {'code': 'SZ.000001', 'time_key': '2026-01-02 00:00:00', 'close': 10.0},
                {'code': 'SZ.000001', 'time_key': '2026-01-03 00:00:00', 'close': 9.0},
                {'code': 'SZ.000001', 'time_key': '2026-01-04 00:00:00', 'close': 12.0},
                {'code': 'SZ.000001', 'time_key': '2026-01-05 00:00:00', 'close': 5.0},
            ]
        }

        result = engine.run(bars_by_code)

        self.assertEqual(2, len(result['trades']))
        self.assertEqual('BUY', result['trades'][0]['side'])
        self.assertEqual('SELL', result['trades'][1]['side'])
        self.assertEqual('均线死叉卖出', result['trades'][1]['reason'])


if __name__ == '__main__':
    unittest.main()
