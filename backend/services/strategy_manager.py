#!/usr/bin/env python3
"""策略管理模块。"""

import argparse
import json

from backend.strategies.runtime.realtime_runner import RealtimeStrategyRunner
from backend.strategies.signals.intraday_signal import IntradayBreakoutSignal
from backend.strategies.signals.ma_signal import PyramidingMaSignal, SinglePositionMaSignal


STRATEGY_REGISTRY = {
    'single_position_ma': {
        'signal_class': SinglePositionMaSignal,
    },
    'pyramiding_ma': {
        'signal_class': PyramidingMaSignal,
    },
    'intraday_breakout_test': {
        'signal_class': IntradayBreakoutSignal,
    },
}

STRATEGY_METADATA = {
    # 前端和后台展示、默认参数装配都依赖这份 metadata。
    'single_position_ma': {
        'name': 'single_position_ma',
        'title': '单仓均线策略',
        'description': '单标的同一时间只允许一笔正式持仓，适合简单金叉买入模型。',
        'params': {
            'codes': ['SZ.000001'],
            'short_ma': 5,
            'long_ma': 20,
            'order_qty': 100,
        },
        'param_fields': [
            {
                'name': 'codes',
                'label': '标的列表',
                'type': 'codes',
                'required': True,
                'placeholder': 'SZ.000001,HK.03690',
            },
            {
                'name': 'short_ma',
                'label': '短期均线',
                'type': 'number',
                'required': True,
                'min': 1,
            },
            {
                'name': 'long_ma',
                'label': '长期均线',
                'type': 'number',
                'required': True,
                'min': 2,
            },
            {
                'name': 'order_qty',
                'label': '单次下单数量',
                'type': 'number',
                'required': True,
                'min': 1,
            },
        ],
    },
    'pyramiding_ma': {
        'name': 'pyramiding_ma',
        'title': '有上限加仓均线策略',
        'description': '允许在仓位上限内继续加仓，并把待确认买单数量纳入仓位计算。',
        'params': {
            'codes': ['SZ.000001'],
            'short_ma': 5,
            'long_ma': 20,
            'order_qty': 100,
            'max_position_per_stock': 300,
        },
        'param_fields': [
            {
                'name': 'codes',
                'label': '标的列表',
                'type': 'codes',
                'required': True,
                'placeholder': 'SZ.000001,HK.03690',
            },
            {
                'name': 'short_ma',
                'label': '短期均线',
                'type': 'number',
                'required': True,
                'min': 1,
            },
            {
                'name': 'long_ma',
                'label': '长期均线',
                'type': 'number',
                'required': True,
                'min': 2,
            },
            {
                'name': 'order_qty',
                'label': '单次下单数量',
                'type': 'number',
                'required': True,
                'min': 1,
            },
            {
                'name': 'max_position_per_stock',
                'label': '单标的最大仓位',
                'type': 'number',
                'required': True,
                'min': 1,
            },
        ],
    },
    'intraday_breakout_test': {
        'name': 'intraday_breakout_test',
        'title': '日内突破测试策略',
        'description': '以实时报价做日内突破买入与回撤/尾盘卖出，适合模拟盘全流程联调。',
        'supports_backtest': False,
        'params': {
            'codes': ['HK.03690'],
            'order_qty': 100,
            'breakout_pct': 0.004,
            'pullback_pct': 0.003,
            'entry_start_time': '09:45:00',
            'flat_time': '15:45:00',
        },
        'param_fields': [
            {
                'name': 'codes',
                'label': '标的列表',
                'type': 'codes',
                'required': True,
                'placeholder': 'HK.03690',
            },
            {
                'name': 'order_qty',
                'label': '单次下单数量',
                'type': 'number',
                'required': True,
                'min': 1,
            },
            {
                'name': 'breakout_pct',
                'label': '突破阈值',
                'type': 'number',
                'required': True,
                'min': 0.0001,
                'step': 0.0005,
            },
            {
                'name': 'pullback_pct',
                'label': '回撤卖出阈值',
                'type': 'number',
                'required': True,
                'min': 0.0001,
                'step': 0.0005,
            },
            {
                'name': 'entry_start_time',
                'label': '入场开始时间',
                'type': 'text',
                'required': True,
                'placeholder': '09:45:00',
            },
            {
                'name': 'flat_time',
                'label': '日内平仓时间',
                'type': 'text',
                'required': True,
                'placeholder': '15:45:00',
            },
        ],
    },
}


class StrategyManager:
    """
    策略管理器。

    负责维护策略注册表，并为实时运行与回测提供统一加载入口。
    """

    def __init__(self, registry=None):
        self.registry = registry or STRATEGY_REGISTRY
        self.instances = {}
        self.signal_instances = {}

    def list_strategies(self):
        return sorted(self.registry.keys())

    def list_strategy_definitions(self):
        return [STRATEGY_METADATA[name] for name in self.list_strategies()]

    def load_strategy(self, name, **kwargs):
        if name not in self.registry:
            raise ValueError(f'未知策略: {name}. 可用策略: {", ".join(self.list_strategies())}')
        strategy = RealtimeStrategyRunner(
            signal_class=self.registry[name]['signal_class'],
            strategy_name=name,
            **kwargs,
        )
        self.instances[name] = strategy
        return strategy

    def load_signal(self, name, **kwargs):
        if name not in self.registry:
            raise ValueError(f'未知策略: {name}. 可用策略: {", ".join(self.list_strategies())}')
        signal = self.registry[name]['signal_class'](**kwargs)
        self.signal_instances[name] = signal
        return signal

    def get_strategy(self, name):
        return self.instances.get(name)

    def start_strategy(self, name, **kwargs):
        strategy = self.load_strategy(name, **kwargs)
        strategy.start()
        return strategy


def parse_args():
    parser = argparse.ArgumentParser(description='策略管理器')
    parser.add_argument('--strategy', default='single_position_ma', choices=sorted(STRATEGY_REGISTRY.keys()), help='要启动的策略名称')
    parser.add_argument('--codes', nargs='+', default=None, help='股票列表，如 SZ.000001 HK.03690')
    parser.add_argument('--short-ma', type=int, default=None, help='短期均线周期')
    parser.add_argument('--long-ma', type=int, default=None, help='长期均线周期')
    parser.add_argument('--order-qty', type=int, default=None, help='单次下单数量')
    parser.add_argument('--max-position-per-stock', type=int, default=None, help='加仓策略的单标的最大仓位')
    parser.add_argument('--breakout-pct', type=float, default=None, help='日内突破阈值')
    parser.add_argument('--pullback-pct', type=float, default=None, help='日内回撤卖出阈值')
    parser.add_argument('--entry-start-time', default=None, help='日内策略开始入场时间')
    parser.add_argument('--flat-time', default=None, help='日内策略平仓时间')
    parser.add_argument('--strategy-params-json', default=None, help='通用策略参数 JSON')
    parser.add_argument('--run-id', default=None, help='运行实例 ID，用于外部控制回调')
    parser.add_argument('--db-path', default=None, help='SQLite 数据库路径')
    return parser.parse_args()


def build_strategy_kwargs(args):
    kwargs = json.loads(args.strategy_params_json) if args.strategy_params_json else {}
    if args.codes:
        kwargs['codes'] = args.codes
    if args.short_ma is not None:
        kwargs['short_ma'] = args.short_ma
    if args.long_ma is not None:
        kwargs['long_ma'] = args.long_ma
    if args.order_qty is not None:
        kwargs['order_qty'] = args.order_qty
    if args.max_position_per_stock is not None and args.strategy == 'pyramiding_ma':
        kwargs['max_position_per_stock'] = args.max_position_per_stock
    if args.breakout_pct is not None:
        kwargs['breakout_pct'] = args.breakout_pct
    if args.pullback_pct is not None:
        kwargs['pullback_pct'] = args.pullback_pct
    if args.entry_start_time is not None:
        kwargs['entry_start_time'] = args.entry_start_time
    if args.flat_time is not None:
        kwargs['flat_time'] = args.flat_time
    if args.run_id is not None:
        kwargs['run_id'] = args.run_id
    if args.db_path is not None:
        kwargs['db_path'] = args.db_path
    return kwargs


def main():
    args = parse_args()
    manager = StrategyManager()
    manager.start_strategy(args.strategy, **build_strategy_kwargs(args))


if __name__ == '__main__':
    main()
