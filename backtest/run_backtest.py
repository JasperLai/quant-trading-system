#!/usr/bin/env python3
"""
回测入口。
"""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / 'scripts'
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(ROOT))

from backtest.data_provider import FutuHistoryDataProvider
from backtest.engine import BacktestEngine
from strategy_manager import STRATEGY_METADATA, StrategyManager


def parse_args():
    parser = argparse.ArgumentParser(description='历史K线回测')
    parser.add_argument('--strategy', default='single_position_ma', choices=sorted(STRATEGY_METADATA.keys()))
    parser.add_argument('--codes', nargs='+', default=['SZ.000001'])
    parser.add_argument('--start', required=True, help='开始日期，例如 2025-01-01')
    parser.add_argument('--end', required=True, help='结束日期，例如 2025-12-31')
    parser.add_argument('--short-ma', type=int, default=5)
    parser.add_argument('--long-ma', type=int, default=20)
    parser.add_argument('--order-qty', type=int, default=100)
    parser.add_argument('--max-position-per-stock', type=int, default=None)
    parser.add_argument('--initial-cash', type=float, default=100000.0)
    parser.add_argument('--commission-rate', type=float, default=0.001)
    parser.add_argument('--slippage', type=float, default=0.0)
    parser.add_argument('--report-file', default=None, help='可选，输出 JSON 报告文件')
    parser.add_argument('--no-cache', action='store_true', help='禁用历史数据缓存')
    return parser.parse_args()


def build_strategy_kwargs(args):
    kwargs = {
        'codes': args.codes,
        'short_ma': args.short_ma,
        'long_ma': args.long_ma,
        'order_qty': args.order_qty,
    }
    if args.max_position_per_stock is not None and args.strategy == 'pyramiding_ma':
        kwargs['max_position_per_stock'] = args.max_position_per_stock
    return kwargs


def main():
    args = parse_args()
    manager = StrategyManager()
    signal = manager.load_signal(args.strategy, **build_strategy_kwargs(args))

    provider = FutuHistoryDataProvider()
    bars_by_code = provider.fetch_many(
        signal.codes,
        start=args.start,
        end=args.end,
        use_cache=not args.no_cache,
    )

    engine = BacktestEngine(
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
