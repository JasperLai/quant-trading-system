#!/usr/bin/env python3
"""
回测入口。
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest.data_provider import FutuHistoryDataProvider
from backtest.engine import BacktestEngine, MinuteBacktestEngine, TickBacktestEngine
from backend.services.strategy_manager import (
    STRATEGY_METADATA,
    StrategyManager,
    get_backtest_engine_name,
    get_backtest_modes,
    get_backtest_ktype,
    resolve_strategy_params,
    strategy_supports_backtest,
)


def parse_args():
    parser = argparse.ArgumentParser(description='历史K线回测')
    parser.add_argument('--strategy', default='single_position_ma', choices=sorted(STRATEGY_METADATA.keys()))
    parser.add_argument('--backtest-mode', choices=['daily', 'minute', 'tick'], default=None)
    parser.add_argument('--codes', nargs='+', default=None)
    parser.add_argument('--start', required=True, help='开始日期，例如 2025-01-01')
    parser.add_argument('--end', required=True, help='结束日期，例如 2025-12-31')
    parser.add_argument('--short-ma', type=int, default=None)
    parser.add_argument('--long-ma', type=int, default=None)
    parser.add_argument('--order-qty', type=int, default=None)
    parser.add_argument('--max-position-per-stock', type=int, default=None)
    parser.add_argument('--rsi-period', type=int, default=None)
    parser.add_argument('--oversold', type=float, default=None)
    parser.add_argument('--overbought', type=float, default=None)
    parser.add_argument('--bollinger-period', type=int, default=None)
    parser.add_argument('--stddev-multiplier', type=float, default=None)
    parser.add_argument('--macd-fast', type=int, default=None)
    parser.add_argument('--macd-slow', type=int, default=None)
    parser.add_argument('--macd-signal', type=int, default=None)
    parser.add_argument('--donchian-entry', type=int, default=None)
    parser.add_argument('--donchian-exit', type=int, default=None)
    parser.add_argument('--breakout-pct', type=float, default=None)
    parser.add_argument('--pullback-pct', type=float, default=None)
    parser.add_argument('--stop-loss-pct', type=float, default=None)
    parser.add_argument('--entry-start-time', default=None)
    parser.add_argument('--flat-time', default=None)
    parser.add_argument('--min-hold-minutes', type=int, default=None)
    parser.add_argument('--max-trades-per-day', type=int, default=None)
    parser.add_argument('--reentry-cooldown-minutes', type=int, default=None)
    parser.add_argument('--strategy-params-json', default=None, help='通用策略参数 JSON')
    parser.add_argument('--initial-cash', type=float, default=100000.0)
    parser.add_argument('--commission-rate', type=float, default=0.001)
    parser.add_argument('--slippage', type=float, default=0.0)
    parser.add_argument('--report-file', default=None, help='可选，输出 JSON 报告文件')
    parser.add_argument('--no-cache', action='store_true', help='禁用历史数据缓存')
    return parser.parse_args()


def build_strategy_kwargs(args):
    return resolve_strategy_params(
        args.strategy,
        {
            **(json.loads(args.strategy_params_json) if args.strategy_params_json else {}),
            'codes': args.codes,
            'short_ma': args.short_ma,
            'long_ma': args.long_ma,
            'order_qty': args.order_qty,
            'max_position_per_stock': args.max_position_per_stock,
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
            'breakout_pct': args.breakout_pct,
            'pullback_pct': args.pullback_pct,
            'stop_loss_pct': args.stop_loss_pct,
            'entry_start_time': args.entry_start_time,
            'flat_time': args.flat_time,
            'min_hold_minutes': args.min_hold_minutes,
            'max_trades_per_day': args.max_trades_per_day,
            'reentry_cooldown_minutes': args.reentry_cooldown_minutes,
        },
    )


def main():
    args = parse_args()
    if not strategy_supports_backtest(args.strategy):
        raise ValueError(f'策略 {args.strategy} 当前不支持回测')
    if args.backtest_mode and args.backtest_mode not in get_backtest_modes(args.strategy):
        raise ValueError(f'策略 {args.strategy} 不支持 {args.backtest_mode} 回测模式，可用模式: {", ".join(get_backtest_modes(args.strategy))}')
    manager = StrategyManager()
    signal = manager.load_signal(args.strategy, **build_strategy_kwargs(args))

    provider = FutuHistoryDataProvider()
    engine_name = args.backtest_mode or get_backtest_engine_name(args.strategy)
    if engine_name == 'tick':
        bars_by_code = provider.fetch_many_tickers(
            signal.codes,
            start=args.start,
            end=args.end,
            use_cache=not args.no_cache,
        )
        engine_class = TickBacktestEngine
    else:
        bars_by_code = provider.fetch_many(
            signal.codes,
            start=args.start,
            end=args.end,
            ktype='K_1M' if engine_name == 'minute' else get_backtest_ktype(args.strategy),
            use_cache=not args.no_cache,
        )
        engine_class = MinuteBacktestEngine if engine_name == 'minute' else BacktestEngine
    engine = engine_class(
        signal=signal,
        initial_cash=args.initial_cash,
        commission_rate=args.commission_rate,
        slippage=args.slippage,
    )
    result = engine.run(bars_by_code)
    print(json.dumps(result['summary'], ensure_ascii=False, indent=2))

    if args.report_file:
        report_path = Path(args.report_file)
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(f'详细报告已写入: {report_path}')


if __name__ == '__main__':
    main()
