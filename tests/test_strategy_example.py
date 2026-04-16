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


class FakeOpenSecTradeContext:
    def __init__(self, filter_trdmarket, host, port):
        self.filter_trdmarket = filter_trdmarket
        self.host = host
        self.port = port

    def get_acc_list(self):
        return 0, FakeFrame([])

    def set_handler(self, handler):
        return 0

    def accinfo_query(self, **kwargs):
        return 0, FakeFrame([])

    def position_list_query(self, **kwargs):
        return 0, FakeFrame([])

    def order_list_query(self, **kwargs):
        return 0, FakeFrame([])

    def deal_list_query(self, **kwargs):
        return 0, FakeFrame([])

    def place_order(self, **kwargs):
        return 0, FakeFrame([{'order_id': 'test'}])

    def close(self):
        return None


class FakeStockQuoteHandlerBase:
    def on_recv_rsp(self, rsp_pb):
        return 0, rsp_pb


class FakeTradeOrderHandlerBase:
    def on_recv_rsp(self, rsp_pb):
        return 0, rsp_pb


class FakeTradeDealHandlerBase:
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

        def send_signal(code, action, price, quantity, note='', **kwargs):
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
        futu.OpenSecTradeContext = FakeOpenSecTradeContext
        futu.StockQuoteHandlerBase = FakeStockQuoteHandlerBase
        futu.TradeOrderHandlerBase = FakeTradeOrderHandlerBase
        futu.TradeDealHandlerBase = FakeTradeDealHandlerBase
        futu.SubType = types.SimpleNamespace(K_DAY='K_DAY', QUOTE='QUOTE')
        futu.KLType = types.SimpleNamespace(K_DAY='K_DAY')
        futu.AuType = types.SimpleNamespace(QFQ='QFQ')
        futu.TrdMarket = types.SimpleNamespace(HK='HK', US='US', CN='CN')
        futu.TrdEnv = types.SimpleNamespace(SIMULATE='SIMULATE', REAL='REAL')
        futu.TrdSide = types.SimpleNamespace(BUY='BUY', SELL='SELL')
        futu.OrderType = types.SimpleNamespace(NORMAL='NORMAL', MARKET='MARKET', ABSOLUTE_LIMIT='ABSOLUTE_LIMIT', NONE='NONE')
        futu.TimeInForce = types.SimpleNamespace(DAY='DAY')
        futu.Session = types.SimpleNamespace(NONE='NONE')
        futu.TrailType = types.SimpleNamespace(NONE='NONE')

        sys.modules['futu'] = futu
        sys.modules['backend.integrations.agent.signal_sender'] = cls.fake_signal_sender
        sys.modules['backend.monitoring.position_monitor'] = cls.fake_position_monitor

        sys.path.insert(0, str(ROOT))
        os.environ['QTS_RUNTIME_DB_PATH'] = str(ROOT / 'backend' / 'data' / 'test-runtime.sqlite3')
        cls.signal_module = importlib.import_module('backend.strategies.signals.ma_signal')
        cls.intraday_signal_module = importlib.import_module('backend.strategies.signals.intraday_signal')
        cls.runner_module = importlib.import_module('backend.strategies.runtime.realtime_runner')
        cls.manager_module = importlib.import_module('backend.services.strategy_manager')
        cls.position_service_module = importlib.import_module('backend.services.position_service')
        cls.api_module = importlib.import_module('backend.api.app')
        cls.backtest_engine_module = importlib.import_module('backtest.engine')

    def setUp(self):
        self.fake_signal_sender.calls.clear()

    def make_runtime(self, signal_class, **kwargs):
        return self.runner_module.RealtimeStrategyRunner(signal_class=signal_class, **kwargs)

    def seed_history(self, strategy, code='HK.00700'):
        strategy.prices[code] = [10.0] * 19 + [9.0]
        strategy.bar_time_keys[code] = [f'2026-01-{idx + 1:02d} 00:00:00' for idx in range(20)]
        strategy.last_short_ma[code] = strategy.calculate_ma(strategy.prices[code], strategy.short_ma_period)
        strategy.last_long_ma[code] = strategy.calculate_ma(strategy.prices[code], strategy.long_ma_period)
        return code

    def test_on_bar_appends_same_price_when_time_key_changes(self):
        strategy = self.make_runtime(self.signal_module.SinglePositionMaSignal, codes=['SZ.000001'], short_ma=5, long_ma=10)
        strategy.on_bar({'code': 'SZ.000001', 'time_key': '2026-04-01 00:00:00', 'close': 10.94})
        strategy.on_bar({'code': 'SZ.000001', 'time_key': '2026-04-02 00:00:00', 'close': 10.94})

        self.assertEqual([10.94, 10.94], strategy.prices['SZ.000001'])
        self.assertEqual(
            ['2026-04-01 00:00:00', '2026-04-02 00:00:00'],
            strategy.bar_time_keys['SZ.000001'],
        )

    def test_on_bar_updates_last_value_when_time_key_repeats(self):
        strategy = self.make_runtime(self.signal_module.SinglePositionMaSignal, codes=['SZ.000001'], short_ma=5, long_ma=10)
        strategy.on_bar({'code': 'SZ.000001', 'time_key': '2026-04-01 00:00:00', 'close': 10.94})
        strategy.on_bar({'code': 'SZ.000001', 'time_key': '2026-04-01 00:00:00', 'close': 10.99})

        self.assertEqual([10.99], strategy.prices['SZ.000001'])
        self.assertEqual(['2026-04-01 00:00:00'], strategy.bar_time_keys['SZ.000001'])

    def test_single_strategy_start_registers_quote_handler_and_subscriptions(self):
        strategy = self.make_runtime(self.signal_module.SinglePositionMaSignal, codes=['HK.00700'], short_ma=5, long_ma=20)

        with mock.patch.object(self.runner_module.time, 'sleep', side_effect=KeyboardInterrupt):
            strategy.start()

        self.assertEqual(1, len(strategy.quote_ctx.handlers))
        self.assertIsInstance(strategy.quote_ctx.handlers[0], self.runner_module.QuoteHandler)
        self.assertEqual(
            [(['HK.00700'], ['K_DAY']), (['HK.00700'], ['QUOTE'])],
            strategy.quote_ctx.subscriptions,
        )

    def test_single_strategy_buy_creates_pending_only(self):
        strategy = self.make_runtime(self.signal_module.SinglePositionMaSignal, codes=['HK.00700'], short_ma=5, long_ma=20)
        code = self.seed_history(strategy)

        strategy.on_quote({'code': code, 'last_price': 20.0})

        self.assertEqual(1, len(self.fake_signal_sender.calls))
        self.assertEqual([], strategy.monitor.add_calls)
        self.assertIn(code, strategy.pending_buys)

    def test_direct_execution_mode_places_order_without_agent_signal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository_module = importlib.import_module('backend.repositories.runtime_repository')
            repository = repository_module.RuntimeRepository(db_path=Path(temp_dir) / 'runtime.sqlite3')
            repository.upsert_run('run-direct', 'single_position_ma', {}, 1234, 'running')
            strategy = self.make_runtime(
                self.signal_module.SinglePositionMaSignal,
                codes=['HK.00700'],
                short_ma=5,
                long_ma=20,
                execution_mode='direct',
                run_id='run-direct',
                db_path=Path(temp_dir) / 'runtime.sqlite3',
            )
            code = self.seed_history(strategy)

            with mock.patch.object(strategy.trading_service, 'place_order', return_value={'order_id': 'ord-1', 'order_status': 'SUBMITTED'}) as mocked_place_order:
                strategy.on_quote({'code': code, 'last_price': 20.0})

            mocked_place_order.assert_called_once()
            self.assertEqual([], self.fake_signal_sender.calls)
            self.assertIn(code, strategy.pending_buys)

    def test_agent_execution_mode_keeps_sending_signal(self):
        strategy = self.make_runtime(
            self.signal_module.SinglePositionMaSignal,
            codes=['HK.00700'],
            short_ma=5,
            long_ma=20,
            execution_mode='agent',
        )
        code = self.seed_history(strategy)

        with mock.patch.object(strategy.trading_service, 'place_order') as mocked_place_order:
            strategy.on_quote({'code': code, 'last_price': 20.0})

        mocked_place_order.assert_not_called()
        self.assertEqual(1, len(self.fake_signal_sender.calls))

    def test_single_strategy_confirm_position_registers_monitor(self):
        strategy = self.make_runtime(self.signal_module.SinglePositionMaSignal, codes=['HK.00700'], short_ma=5, long_ma=20)
        code = self.seed_history(strategy)
        strategy.pending_buys.add(code)

        strategy.confirm_position(code=code, qty=100, entry_price=20.0)

        self.assertNotIn(code, strategy.pending_buys)
        self.assertEqual(1, len(strategy.monitor.add_calls))

    def test_single_strategy_dead_cross_creates_pending_sell_only(self):
        strategy = self.make_runtime(self.signal_module.SinglePositionMaSignal, codes=['HK.00700'], short_ma=5, long_ma=20)
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
        strategy = self.make_runtime(self.signal_module.SinglePositionMaSignal, codes=['HK.00700'], short_ma=5, long_ma=20)
        code = 'HK.00700'
        strategy.pending_sells[code] = 100
        strategy.monitor.positions[code] = {'qty': 100}

        strategy.confirm_exit(code=code, qty=100, exit_price=19.0)

        self.assertNotIn(code, strategy.pending_sells)
        self.assertEqual([code], strategy.monitor.remove_calls)

    def test_runner_reads_position_and_pending_state_from_repository(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'runtime.sqlite3'
            repository = importlib.import_module('backend.repositories.runtime_repository').RuntimeRepository(db_path=db_path)
            repository.upsert_run('run-test', 'single_position_ma', {}, 1234, 'running')
            repository.upsert_strategy_position(
                'run-test',
                'HK.00700',
                {
                    'qty': 100,
                    'entry': 20.0,
                    'stop': 16.0,
                    'profit': 26.0,
                    'stop_pct': -0.20,
                    'profit_pct': 0.30,
                    'reason': 'test',
                    'entry_time': '2026-04-08T10:00:00',
                },
            )
            repository.upsert_pending_order('run-test', 'HK.00700', 'SELL', 100)
            strategy = self.make_runtime(
                self.signal_module.SinglePositionMaSignal,
                codes=['HK.00700'],
                short_ma=5,
                long_ma=20,
                run_id='run-test',
                db_path=str(db_path),
            )
            strategy.prices['HK.00700'] = [10.0] * 19 + [11.0]
            strategy.bar_time_keys['HK.00700'] = [f'2026-01-{idx + 1:02d} 00:00:00' for idx in range(20)]
            strategy.last_short_ma['HK.00700'] = strategy.calculate_ma(strategy.prices['HK.00700'], strategy.short_ma_period)
            strategy.last_long_ma['HK.00700'] = strategy.calculate_ma(strategy.prices['HK.00700'], strategy.long_ma_period)

            strategy.on_quote({'code': 'HK.00700', 'last_price': 1.0})

            self.assertEqual([], self.fake_signal_sender.calls)
            self.assertIn('HK.00700', strategy.pending_sells)

    def test_api_confirm_buy_applies_for_running_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'runtime.sqlite3'
            runtime = self.api_module.StrategyRuntime()
            runtime.repository = importlib.import_module('backend.repositories.runtime_repository').RuntimeRepository(db_path=db_path)
            runtime.position_service = self.position_service_module.PositionService(runtime.repository)
            runtime.repository.upsert_run('run-live', 'single_position_ma', {}, 1234, 'running')

            response = runtime.confirm_buy(
                'run-live',
                self.api_module.ConfirmBuyRequest(code='HK.00700', qty=100, entryPrice=20.0, reason='manual confirm'),
            )

            self.assertEqual('applied', response['status'])
            self.assertEqual(1, len(runtime.repository.list_strategy_positions('run-live')))

    def test_pyramiding_strategy_respects_max_position(self):
        strategy = self.make_runtime(
            self.signal_module.PyramidingMaSignal,
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
        strategy = self.make_runtime(
            self.signal_module.PyramidingMaSignal,
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
        strategy = self.make_runtime(
            self.signal_module.PyramidingMaSignal,
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

        self.assertIsInstance(strategy, self.runner_module.RealtimeStrategyRunner)
        self.assertIsInstance(strategy.signal, self.signal_module.PyramidingMaSignal)
        self.assertEqual(400, strategy.max_position_per_stock)
        self.assertIn('pyramiding_ma', manager.instances)

    def test_strategy_manager_loads_intraday_strategy(self):
        manager = self.manager_module.StrategyManager()
        strategy = manager.load_strategy('intraday_breakout_test', codes=['HK.03690'], breakout_pct=0.01)

        self.assertIsInstance(strategy, self.runner_module.RealtimeStrategyRunner)
        self.assertIsInstance(strategy.signal, self.intraday_signal_module.IntradayBreakoutSignal)
        self.assertAlmostEqual(0.01, strategy.signal.breakout_pct)

    def test_strategy_manager_rejects_direct_mode_without_runtime_identity(self):
        manager = self.manager_module.StrategyManager()
        with self.assertRaisesRegex(ValueError, 'run_id 和 db_path'):
            manager.load_strategy(
                'single_position_ma',
                codes=['HK.00700'],
                short_ma=5,
                long_ma=20,
                execution_mode='direct',
            )

    def test_strategy_manager_loads_signal_for_backtest(self):
        manager = self.manager_module.StrategyManager()
        signal = manager.load_signal('single_position_ma', codes=['SZ.000001'], short_ma=3, long_ma=6)

        self.assertIsInstance(signal, self.signal_module.SinglePositionMaSignal)
        self.assertEqual(3, signal.short_ma_period)
        self.assertEqual(6, signal.long_ma_period)

    def test_resolve_strategy_params_validates_number_type(self):
        with self.assertRaises(ValueError):
            self.manager_module.resolve_strategy_params('single_position_ma', {'short_ma': 'abc'})

    def test_backtest_engine_skips_risk_check_on_same_bar_buy(self):
        class BuyOnceSignal:
            strategy_name = 'buy_once'

            def __init__(self):
                self.called = False

            def update_bar(self, event):
                return event

            def evaluate_quote(self, quote_data, position_qty=0):
                if not self.called:
                    self.called = True
                    return {'action': 'BUY', 'qty': 100, 'reason': 'test buy'}
                return None

            def clear_pending_buy(self, code, qty=None):
                return None

            def clear_pending_sell(self, code, qty=None):
                return None

        engine = self.backtest_engine_module.BacktestEngine(
            signal=BuyOnceSignal(),
            initial_cash=100000.0,
            commission_rate=0.0,
            slippage=0.0,
        )
        result = engine.run(
            {
                'HK.03690': [
                    {
                        'time_key': '2026-01-01 00:00:00',
                        'open': 100.0,
                        'high': 100.0,
                        'low': 100.0,
                        'close': 100.0,
                    }
                ]
            }
        )
        self.assertEqual(1, result['summary']['trade_count'])
        self.assertEqual('BUY', result['trades'][0]['side'])
        self.assertIn('HK.03690', result['open_positions'])

    def test_backtest_equity_curve_records_once_per_time_key(self):
        signal = self.signal_module.SinglePositionMaSignal(codes=['HK.00700', 'HK.09988'], short_ma=2, long_ma=3, order_qty=100)
        bars = {
            'HK.00700': [
                {'time_key': '2026-01-01 00:00:00', 'open': 10, 'high': 10, 'low': 10, 'close': 10},
                {'time_key': '2026-01-02 00:00:00', 'open': 11, 'high': 11, 'low': 11, 'close': 11},
            ],
            'HK.09988': [
                {'time_key': '2026-01-01 00:00:00', 'open': 20, 'high': 20, 'low': 20, 'close': 20},
                {'time_key': '2026-01-02 00:00:00', 'open': 21, 'high': 21, 'low': 21, 'close': 21},
            ],
        }
        result = self.backtest_engine_module.BacktestEngine(
            signal=signal,
            initial_cash=100000.0,
            commission_rate=0.0,
            slippage=0.0,
        ).run(bars)
        self.assertEqual(2, len(result['equity_curve']))
        self.assertEqual(['2026-01-01 00:00:00', '2026-01-02 00:00:00'], [item['time'] for item in result['equity_curve']])

    def test_backtest_realized_pnl_includes_buy_commission(self):
        portfolio = self.backtest_engine_module.BacktestPortfolio(initial_cash=100000.0, commission_rate=0.001, slippage=0.0)
        self.assertTrue(portfolio.buy('HK.03690', qty=100, price=10.0, time_key='2026-01-01 00:00:00', reason='BUY'))
        trade = portfolio.sell('HK.03690', price=10.02, time_key='2026-01-02 00:00:00', reason='SELL')
        self.assertIsNotNone(trade)
        self.assertLess(trade['realized_pnl'], 0)

    def test_intraday_signal_generates_buy_then_sell(self):
        signal = self.intraday_signal_module.IntradayBreakoutSignal(
            codes=['HK.03690'],
            order_qty=100,
            breakout_pct=0.01,
            pullback_pct=0.005,
            entry_start_time='09:30:00',
            flat_time='15:45:00',
        )

        buy = signal.evaluate_quote(
            {
                'code': 'HK.03690',
                'last_price': 101.2,
                'open_price': 100.0,
                'prev_close_price': 99.8,
                'data_date': '2026-04-13',
                'data_time': '09:35:00',
            },
            position_qty=0,
        )
        self.assertEqual('BUY', buy['action'])
        self.assertEqual(100, buy['qty'])

        hold = signal.evaluate_quote(
            {
                'code': 'HK.03690',
                'last_price': 102.0,
                'open_price': 100.0,
                'prev_close_price': 99.8,
                'data_date': '2026-04-13',
                'data_time': '10:00:00',
            },
            position_qty=100,
        )
        self.assertIsNone(hold['action'])

        sell = signal.evaluate_quote(
            {
                'code': 'HK.03690',
                'last_price': 101.3,
                'open_price': 100.0,
                'prev_close_price': 99.8,
                'data_date': '2026-04-13',
                'data_time': '10:05:00',
            },
            position_qty=100,
        )
        self.assertEqual('SELL', sell['action'])
        self.assertEqual(100, sell['qty'])

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
        strategy = self.make_runtime(
            self.signal_module.SinglePositionMaSignal,
            codes=['HK.00700'],
            short_ma=5,
            long_ma=20,
            run_id='run-sync',
            db_path=str(ROOT / 'backend' / 'data' / 'test-runtime.sqlite3'),
        )
        strategy.repository.replace_pending_orders = mock.Mock()

        strategy.sync_runtime_state()
        strategy.sync_runtime_state()

        self.assertEqual(1, strategy.repository.replace_pending_orders.call_count)

    def test_position_service_can_confirm_buy_and_sell_without_runtime_process(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'runtime.sqlite3'
            repository = importlib.import_module('backend.repositories.runtime_repository').RuntimeRepository(db_path=db_path)
            service = self.position_service_module.PositionService(repository)
            repository.upsert_run('run-position', 'single_position_ma', {}, 1234, 'stopped')
            repository.upsert_pending_order('run-position', 'HK.00700', 'BUY', 100)

            position = service.confirm_position('run-position', 'HK.00700', 100, 20.0)
            self.assertEqual(100, position['qty'])
            self.assertEqual([], repository.list_pending_orders('run-position'))
            account_positions = repository.list_account_positions('default')
            self.assertEqual(1, len(account_positions))
            self.assertEqual(100, account_positions[0]['qty'])

            repository.upsert_pending_order('run-position', 'HK.00700', 'SELL', 100)
            remaining = service.confirm_exit('run-position', 'HK.00700', qty=100, exit_price=21.0)

            self.assertEqual(0, remaining)
            self.assertEqual([], repository.list_strategy_positions('run-position'))
            self.assertEqual([], repository.list_account_positions('default'))
            self.assertEqual([], repository.list_pending_orders('run-position'))
            executions = repository.list_executions('run-position')
            self.assertEqual(['BUY', 'SELL'], [item['side'] for item in executions])

    def test_strategy_runtime_confirm_sell_applies_directly_for_stopped_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'runtime.sqlite3'
            runtime = self.api_module.StrategyRuntime()
            runtime.repository = importlib.import_module('backend.repositories.runtime_repository').RuntimeRepository(db_path=db_path)
            runtime.position_service = self.position_service_module.PositionService(runtime.repository)
            runtime.repository.upsert_run('run-stopped', 'single_position_ma', {}, 1234, 'stopped')
            runtime.repository.upsert_strategy_position(
                'run-stopped',
                'HK.00700',
                {
                    'qty': 100,
                    'entry': 20.0,
                    'stop': 16.0,
                    'profit': 26.0,
                    'stop_pct': -0.20,
                    'profit_pct': 0.30,
                    'reason': 'test',
                    'entry_time': '2026-04-08T10:00:00',
                },
            )
            runtime.repository.upsert_pending_order('run-stopped', 'HK.00700', 'SELL', 100)

            response = runtime.confirm_sell(
                'run-stopped',
                self.api_module.ConfirmSellRequest(code='HK.00700', qty=100, exitPrice=21.5, reason='manual confirm'),
            )

            self.assertEqual('applied', response['status'])
            self.assertEqual([], runtime.repository.list_strategy_positions('run-stopped'))

    def test_position_service_aggregates_account_positions_across_runs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'runtime.sqlite3'
            repository = importlib.import_module('backend.repositories.runtime_repository').RuntimeRepository(db_path=db_path)
            service = self.position_service_module.PositionService(repository)
            repository.upsert_run('run-a', 'single_position_ma', {}, 1234, 'stopped')
            repository.upsert_run('run-b', 'single_position_ma', {}, 1235, 'stopped')

            service.confirm_position('run-a', 'HK.00700', 100, 20.0)
            service.confirm_position('run-b', 'HK.00700', 200, 22.0)

            strategy_a = repository.list_strategy_positions('run-a')
            strategy_b = repository.list_strategy_positions('run-b')
            account_positions = repository.list_account_positions('default')

            self.assertEqual(100, strategy_a[0]['qty'])
            self.assertEqual(200, strategy_b[0]['qty'])
            self.assertEqual(1, len(account_positions))
            self.assertEqual(300, account_positions[0]['qty'])
            self.assertAlmostEqual(round((20.0 * 100 + 22.0 * 200) / 300, 4), account_positions[0]['entry'], places=4)

    def test_position_service_can_confirm_account_level_sell_and_allocate_across_runs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'runtime.sqlite3'
            repository = importlib.import_module('backend.repositories.runtime_repository').RuntimeRepository(db_path=db_path)
            service = self.position_service_module.PositionService(repository)
            repository.upsert_run('run-a', 'single_position_ma', {}, 1234, 'running')
            repository.upsert_run('run-b', 'single_position_ma', {}, 1235, 'running')

            service.confirm_position('run-a', 'HK.00700', 100, 20.0)
            service.confirm_position('run-b', 'HK.00700', 200, 22.0)

            result = service.confirm_account_exit(
                account_id='default',
                code='HK.00700',
                qty=150,
                exit_price=25.0,
                reason='guardian stop sell',
            )

            self.assertEqual(150, result['remainingQty'])
            self.assertEqual(
                [
                    {'run_id': 'run-a', 'qty': 100, 'remainingQty': 0},
                    {'run_id': 'run-b', 'qty': 50, 'remainingQty': 150},
                ],
                result['allocations'],
            )

            strategy_a = repository.list_strategy_positions('run-a')
            strategy_b = repository.list_strategy_positions('run-b')
            account_positions = repository.list_account_positions('default')

            self.assertEqual([], strategy_a)
            self.assertEqual(150, strategy_b[0]['qty'])
            self.assertEqual(150, account_positions[0]['qty'])
            self.assertEqual(['BUY', 'SELL'], [item['side'] for item in repository.list_executions('run-a')])
            self.assertEqual(['BUY', 'SELL'], [item['side'] for item in repository.list_executions('run-b')])

    def test_api_confirm_account_sell_returns_allocations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'runtime.sqlite3'
            runtime = self.api_module.StrategyRuntime()
            runtime.repository = importlib.import_module('backend.repositories.runtime_repository').RuntimeRepository(db_path=db_path)
            runtime.position_service = self.position_service_module.PositionService(runtime.repository)
            runtime.repository.upsert_run('run-a', 'single_position_ma', {}, 1234, 'running')
            runtime.position_service.confirm_position('run-a', 'HK.00700', 100, 20.0)

            response = runtime.confirm_account_sell(
                'default',
                self.api_module.ConfirmSellRequest(code='HK.00700', qty=100, exitPrice=21.0, reason='guardian sell'),
            )

            self.assertEqual('applied', response['status'])
            self.assertEqual('default', response['accountId'])
            self.assertEqual(0, response['remainingQty'])
            self.assertEqual([{'run_id': 'run-a', 'qty': 100, 'remainingQty': 0}], response['allocations'])

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
