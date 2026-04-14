#!/usr/bin/env python3
"""策略管理模块。"""

import argparse
import json

from backend.strategies.runtime.realtime_runner import RealtimeStrategyRunner
from backend.strategies.signals.indicator_signals import (
    BollingerReversionSignal,
    DonchianBreakoutSignal,
    MacdTrendSignal,
    RsiReversionSignal,
)
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
    'rsi_reversion': {
        'signal_class': RsiReversionSignal,
    },
    'bollinger_reversion': {
        'signal_class': BollingerReversionSignal,
    },
    'macd_trend': {
        'signal_class': MacdTrendSignal,
    },
    'donchian_breakout': {
        'signal_class': DonchianBreakoutSignal,
    },
}

STRATEGY_METADATA = {
    # 前端和后台展示、默认参数装配都依赖这份 metadata。
    'single_position_ma': {
        'name': 'single_position_ma',
        'title': '单仓均线策略',
        'description': '单标的同一时间只允许一笔正式持仓，适合简单金叉买入模型。',
        'supports_backtest': True,
        'learning_notes': {
            'style': '趋势跟随',
            'entry': '短期均线上穿长期均线时买入。',
            'exit': '短期均线下穿长期均线时卖出。',
            'usage': '适合理解最基础的金叉/死叉模型，也是其他趋势策略的起点。',
        },
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
        'supports_backtest': True,
        'learning_notes': {
            'style': '趋势跟随 + 分批建仓',
            'entry': '均线金叉时买入，只要总仓位未达到上限就允许继续加仓。',
            'exit': '均线死叉时卖出当前仓位。',
            'usage': '适合理解“信号正确但建仓节奏不同”时，持仓曲线会如何变化。',
        },
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
    'rsi_reversion': {
        'name': 'rsi_reversion',
        'title': 'RSI 反转策略',
        'description': '在超卖区等待 RSI 回升买入，在超买区卖出，适合均值回归型日线回测。',
        'supports_backtest': True,
        'learning_notes': {
            'style': '均值回归',
            'entry': 'RSI 从超卖区下方向上回穿阈值时买入。',
            'exit': '持仓后 RSI 进入超买区时卖出。',
            'usage': '适合理解“跌深反弹”型策略，通常更依赖震荡市，不适合单边趋势很强的阶段。',
        },
        'params': {
            'codes': ['HK.03690'],
            'rsi_period': 14,
            'oversold': 30,
            'overbought': 70,
            'order_qty': 100,
        },
        'param_fields': [
            {'name': 'codes', 'label': '标的列表', 'type': 'codes', 'required': True, 'placeholder': 'HK.03690'},
            {'name': 'rsi_period', 'label': 'RSI周期', 'type': 'number', 'required': True, 'min': 2},
            {'name': 'oversold', 'label': '超卖阈值', 'type': 'number', 'required': True, 'min': 1, 'max': 50},
            {'name': 'overbought', 'label': '超买阈值', 'type': 'number', 'required': True, 'min': 50, 'max': 99},
            {'name': 'order_qty', 'label': '单次下单数量', 'type': 'number', 'required': True, 'min': 1},
        ],
    },
    'bollinger_reversion': {
        'name': 'bollinger_reversion',
        'title': '布林带反转策略',
        'description': '价格跌出下轨后重新回到通道内买入，回归中轨时卖出。',
        'supports_backtest': True,
        'learning_notes': {
            'style': '波动带回归',
            'entry': '价格跌破布林下轨后重新站回通道内时买入。',
            'exit': '价格回归到布林中轨附近时卖出。',
            'usage': '适合理解波动扩张后的回归逻辑，对横盘震荡标的更友好。',
        },
        'params': {
            'codes': ['HK.03690'],
            'bollinger_period': 20,
            'stddev_multiplier': 2.0,
            'order_qty': 100,
        },
        'param_fields': [
            {'name': 'codes', 'label': '标的列表', 'type': 'codes', 'required': True, 'placeholder': 'HK.03690'},
            {'name': 'bollinger_period', 'label': '布林周期', 'type': 'number', 'required': True, 'min': 5},
            {'name': 'stddev_multiplier', 'label': '标准差倍数', 'type': 'number', 'required': True, 'min': 0.5, 'step': 0.1},
            {'name': 'order_qty', 'label': '单次下单数量', 'type': 'number', 'required': True, 'min': 1},
        ],
    },
    'macd_trend': {
        'name': 'macd_trend',
        'title': 'MACD 趋势策略',
        'description': '使用 MACD 金叉/死叉跟随趋势，适合中短期波段回测。',
        'supports_backtest': True,
        'learning_notes': {
            'style': '动量趋势',
            'entry': 'MACD 线上穿 Signal 线时买入。',
            'exit': 'MACD 线下穿 Signal 线时卖出。',
            'usage': '适合理解趋势确认比均线更灵敏时，信号频率和回撤会如何变化。',
        },
        'params': {
            'codes': ['HK.03690'],
            'macd_fast': 12,
            'macd_slow': 26,
            'macd_signal': 9,
            'order_qty': 100,
        },
        'param_fields': [
            {'name': 'codes', 'label': '标的列表', 'type': 'codes', 'required': True, 'placeholder': 'HK.03690'},
            {'name': 'macd_fast', 'label': '快线周期', 'type': 'number', 'required': True, 'min': 2},
            {'name': 'macd_slow', 'label': '慢线周期', 'type': 'number', 'required': True, 'min': 3},
            {'name': 'macd_signal', 'label': '信号线周期', 'type': 'number', 'required': True, 'min': 2},
            {'name': 'order_qty', 'label': '单次下单数量', 'type': 'number', 'required': True, 'min': 1},
        ],
    },
    'donchian_breakout': {
        'name': 'donchian_breakout',
        'title': '唐奇安突破策略',
        'description': '突破前 N 日区间高点买入，跌破退出通道卖出，适合趋势突破回测。',
        'supports_backtest': True,
        'learning_notes': {
            'style': '区间突破',
            'entry': '价格突破过去 N 日最高价时买入。',
            'exit': '价格跌破较短退出通道低点时卖出。',
            'usage': '适合理解海龟式突破思路，对强趋势行情更敏感，但震荡期容易被来回打止损。',
        },
        'params': {
            'codes': ['HK.03690'],
            'donchian_entry': 20,
            'donchian_exit': 10,
            'order_qty': 100,
        },
        'param_fields': [
            {'name': 'codes', 'label': '标的列表', 'type': 'codes', 'required': True, 'placeholder': 'HK.03690'},
            {'name': 'donchian_entry', 'label': '突破周期', 'type': 'number', 'required': True, 'min': 5},
            {'name': 'donchian_exit', 'label': '退出周期', 'type': 'number', 'required': True, 'min': 2},
            {'name': 'order_qty', 'label': '单次下单数量', 'type': 'number', 'required': True, 'min': 1},
        ],
    },
    'intraday_breakout_test': {
        'name': 'intraday_breakout_test',
        'title': '日内突破测试策略',
        'description': '以实时报价做日内突破买入与回撤/尾盘卖出，适合模拟盘全流程联调。',
        'supports_backtest': False,
        'learning_notes': {
            'style': '日内测试',
            'entry': '09:45 之后向上突破参考价一定比例时买入。',
            'exit': '冲高回撤或尾盘强制平仓时卖出。',
            'usage': '主要用来联调模拟盘流程，不适合作为现在这套日线回测模型的正式回测对象。',
        },
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
        return [
            {
                **STRATEGY_METADATA[name],
                'supports_backtest': STRATEGY_METADATA[name].get('supports_backtest', True),
            }
            for name in self.list_strategies()
        ]

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
    parser.add_argument('--rsi-period', type=int, default=None, help='RSI 周期')
    parser.add_argument('--oversold', type=float, default=None, help='RSI 超卖阈值')
    parser.add_argument('--overbought', type=float, default=None, help='RSI 超买阈值')
    parser.add_argument('--bollinger-period', type=int, default=None, help='布林周期')
    parser.add_argument('--stddev-multiplier', type=float, default=None, help='布林标准差倍数')
    parser.add_argument('--macd-fast', type=int, default=None, help='MACD 快线周期')
    parser.add_argument('--macd-slow', type=int, default=None, help='MACD 慢线周期')
    parser.add_argument('--macd-signal', type=int, default=None, help='MACD 信号线周期')
    parser.add_argument('--donchian-entry', type=int, default=None, help='唐奇安突破周期')
    parser.add_argument('--donchian-exit', type=int, default=None, help='唐奇安退出周期')
    parser.add_argument('--strategy-params-json', default=None, help='通用策略参数 JSON')
    parser.add_argument('--run-id', default=None, help='运行实例 ID，用于外部控制回调')
    parser.add_argument('--db-path', default=None, help='SQLite 数据库路径')
    return parser.parse_args()


def resolve_strategy_params(strategy_name, overrides=None):
    if strategy_name not in STRATEGY_METADATA:
        raise ValueError(f'未知策略: {strategy_name}')
    params = dict(STRATEGY_METADATA[strategy_name].get('params', {}))
    field_defs = {field['name']: field for field in STRATEGY_METADATA[strategy_name].get('param_fields', [])}
    for key, value in (overrides or {}).items():
        if value is None:
            continue
        field = field_defs.get(key)
        if key == 'codes':
            if isinstance(value, str):
                normalized = [item.strip() for item in value.split(',') if item.strip()]
            elif isinstance(value, (list, tuple)):
                normalized = [str(item).strip() for item in value if str(item).strip()]
            else:
                raise ValueError(f'策略参数 {key} 类型错误，期望代码列表')
            if field and field.get('required') and not normalized:
                raise ValueError(f'策略参数 {key} 不能为空')
            params[key] = normalized
            continue

        if field and field.get('type') == 'number':
            try:
                if isinstance(value, bool):
                    raise ValueError
                normalized = float(value) if any(token in str(value) for token in ['.', 'e', 'E']) else int(value)
            except (TypeError, ValueError):
                raise ValueError(f'策略参数 {key} 类型错误，期望数值') from None
            if 'min' in field and normalized < field['min']:
                raise ValueError(f'策略参数 {key} 不能小于 {field["min"]}')
            if 'max' in field and normalized > field['max']:
                raise ValueError(f'策略参数 {key} 不能大于 {field["max"]}')
            params[key] = normalized
            continue

        if field and field.get('type') == 'text':
            normalized = str(value).strip()
            if field.get('required') and not normalized:
                raise ValueError(f'策略参数 {key} 不能为空')
            params[key] = normalized
            continue

        params[key] = value
    return params


def strategy_supports_backtest(strategy_name):
    if strategy_name not in STRATEGY_METADATA:
        raise ValueError(f'未知策略: {strategy_name}')
    return STRATEGY_METADATA[strategy_name].get('supports_backtest', True)


def build_strategy_kwargs(args):
    kwargs = resolve_strategy_params(
        args.strategy,
        {
            **(json.loads(args.strategy_params_json) if args.strategy_params_json else {}),
            'codes': args.codes,
            'short_ma': args.short_ma,
            'long_ma': args.long_ma,
            'order_qty': args.order_qty,
            'max_position_per_stock': args.max_position_per_stock,
            'breakout_pct': args.breakout_pct,
            'pullback_pct': args.pullback_pct,
            'entry_start_time': args.entry_start_time,
            'flat_time': args.flat_time,
            'rsi_period': args.rsi_period,
            'oversold': args.oversold,
            'overbought': args.overbought,
            'bollinger_period': args.bollinger_period,
            'stddev_multiplier': args.stddev_multiplier,
            'macd_fast': args.macd_fast,
            'macd_slow': args.macd_slow,
            'macd_signal': args.macd_signal,
            'donchian_entry': args.donchian_entry,
            'donchian_exit': args.donchian_exit,
        },
    )
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
