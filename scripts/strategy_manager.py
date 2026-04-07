#!/usr/bin/env python3
"""
策略管理模块。

负责：
1. 注册可用策略
2. 根据名称加载策略
3. 启动指定策略
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pyramiding_strategy import PyramidingMaCrossStrategy
from strategy_example import MaCrossStrategy


STRATEGY_REGISTRY = {
    'single_position_ma': MaCrossStrategy,
    'pyramiding_ma': PyramidingMaCrossStrategy,
}

STRATEGY_METADATA = {
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
    },
}


class StrategyManager:
    def __init__(self, registry=None):
        self.registry = registry or STRATEGY_REGISTRY
        self.instances = {}

    def list_strategies(self):
        return sorted(self.registry.keys())

    def list_strategy_definitions(self):
        return [STRATEGY_METADATA[name] for name in self.list_strategies()]

    def load_strategy(self, name, **kwargs):
        if name not in self.registry:
            raise ValueError(f'未知策略: {name}. 可用策略: {", ".join(self.list_strategies())}')
        strategy = self.registry[name](**kwargs)
        self.instances[name] = strategy
        return strategy

    def get_strategy(self, name):
        return self.instances.get(name)

    def start_strategy(self, name, **kwargs):
        strategy = self.load_strategy(name, **kwargs)
        strategy.start()
        return strategy


def parse_args():
    parser = argparse.ArgumentParser(description='策略管理器')
    parser.add_argument(
        '--strategy',
        default='single_position_ma',
        choices=sorted(STRATEGY_REGISTRY.keys()),
        help='要启动的策略名称',
    )
    parser.add_argument('--codes', nargs='+', default=None, help='股票列表，如 SZ.000001 HK.03690')
    parser.add_argument('--short-ma', type=int, default=None, help='短期均线周期')
    parser.add_argument('--long-ma', type=int, default=None, help='长期均线周期')
    parser.add_argument('--order-qty', type=int, default=None, help='单次下单数量')
    parser.add_argument('--max-position-per-stock', type=int, default=None, help='加仓策略的单标的最大仓位')
    return parser.parse_args()


def build_strategy_kwargs(args):
    kwargs = {}
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
    return kwargs


def main():
    args = parse_args()
    manager = StrategyManager()
    manager.start_strategy(args.strategy, **build_strategy_kwargs(args))


if __name__ == '__main__':
    main()
