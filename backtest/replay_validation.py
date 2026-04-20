#!/usr/bin/env python3
"""基于回测结果做业务流程回放验证。"""

import argparse
import json
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest.data_provider import FutuHistoryDataProvider
from backtest.engine import BacktestEngine, MinuteBacktestEngine, TickBacktestEngine
from backend.core.config import TAKE_PROFIT_PCT
from backend.repositories.runtime_repository import RuntimeRepository
from backend.services.position_service import PositionService
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
    parser = argparse.ArgumentParser(description='回测信号 -> 业务流程回放验证')
    parser.add_argument('--strategy', default='pyramiding_ma', choices=sorted(STRATEGY_METADATA.keys()))
    parser.add_argument('--backtest-mode', choices=['daily', 'minute', 'tick'], default=None)
    parser.add_argument('--codes', nargs='+', default=None)
    parser.add_argument('--start', required=True, help='开始日期，例如 2025-10-01')
    parser.add_argument('--end', required=True, help='结束日期，例如 2026-04-08')
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
    parser.add_argument('--report-file', default=None, help='可选，输出完整验证报告 JSON')
    parser.add_argument('--no-cache', action='store_true')
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


def run_backtest(args):
    if not strategy_supports_backtest(args.strategy):
        raise ValueError(f'策略 {args.strategy} 当前不支持回测')
    if args.backtest_mode and args.backtest_mode not in get_backtest_modes(args.strategy):
        raise ValueError(f'策略 {args.strategy} 不支持 {args.backtest_mode} 回测模式，可用模式: {", ".join(get_backtest_modes(args.strategy))}')
    manager = StrategyManager()
    strategy_kwargs = build_strategy_kwargs(args)
    signal = manager.load_signal(args.strategy, **strategy_kwargs)
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
    return engine.run(bars_by_code), bars_by_code, strategy_kwargs


def make_run(repository, strategy_name, config):
    run_id = uuid.uuid4().hex[:8]
    repository.upsert_run(run_id, strategy_name, config, pid=0, status='replay')
    return run_id


def snapshot(repository, service, run_id):
    return {
        'strategyPositions': repository.list_strategy_positions(run_id),
        'accountPositions': repository.list_account_positions(service.account_id),
        'pendingOrders': repository.list_pending_orders(run_id),
        'executions': repository.list_executions(run_id),
    }


def replay_strategy_trades(backtest_result, args, strategy_kwargs):
    with tempfile.TemporaryDirectory() as temp_dir:
        repository = RuntimeRepository(db_path=Path(temp_dir) / 'workflow.sqlite3')
        service = PositionService(repository)
        run_id = make_run(
            repository,
            args.strategy,
            {
                'strategy': args.strategy,
                **strategy_kwargs,
                'source': 'backtest_replay',
            },
        )

        events = []
        for trade in backtest_result['trades']:
            if trade['side'] == 'BUY':
                position = service.confirm_position(
                    run_id=run_id,
                    code=trade['code'],
                    qty=trade['qty'],
                    entry_price=trade['price'],
                    reason=trade['reason'],
                )
                events.append(
                    {
                        'event': 'confirm_buy',
                        'trade': trade,
                        'position': position,
                        'snapshot': snapshot(repository, service, run_id),
                    }
                )
            elif trade['side'] == 'SELL':
                remaining_qty = service.confirm_exit(
                    run_id=run_id,
                    code=trade['code'],
                    qty=trade['qty'],
                    exit_price=trade['price'],
                    reason=trade['reason'],
                )
                events.append(
                    {
                        'event': 'confirm_sell',
                        'trade': trade,
                        'remainingQty': remaining_qty,
                        'snapshot': snapshot(repository, service, run_id),
                    }
                )

        final_state = snapshot(repository, service, run_id)
        checks = {
            'execution_count_matches_trades': len(final_state['executions']) == len(backtest_result['trades']),
            'no_pending_orders': final_state['pendingOrders'] == [],
            'account_qty_matches_strategy_qty': (
                sum(item['qty'] for item in final_state['accountPositions'])
                == sum(item['qty'] for item in final_state['strategyPositions'])
            ),
        }
        return {
            'runId': run_id,
            'events': events,
            'finalState': final_state,
            'checks': checks,
        }


def replay_guardian_exit(backtest_result, args):
    buy_trades = [trade for trade in backtest_result['trades'] if trade['side'] == 'BUY']
    if not buy_trades:
        return {
            'skipped': True,
            'reason': '回测结果中没有 BUY 事件，无法验证 guardian 账户级卖出。',
        }

    with tempfile.TemporaryDirectory() as temp_dir:
        repository = RuntimeRepository(db_path=Path(temp_dir) / 'guardian.sqlite3')
        service = PositionService(repository)

        run_a = make_run(repository, args.strategy, {'source': 'guardian_replay', 'slot': 'A'})
        run_b = make_run(repository, args.strategy, {'source': 'guardian_replay', 'slot': 'B'})

        first_buy = buy_trades[0]
        second_buy = buy_trades[1] if len(buy_trades) > 1 else None

        if second_buy is not None:
            service.confirm_position(run_a, first_buy['code'], first_buy['qty'], first_buy['price'], reason='guardian seed A')
            service.confirm_position(run_b, second_buy['code'], second_buy['qty'], second_buy['price'], reason='guardian seed B')
            target_code = first_buy['code']
            synthetic_exit_price = next(
                (trade['price'] for trade in backtest_result['trades'] if trade['side'] == 'SELL' and trade['code'] == target_code),
                round(second_buy['price'] * (1 + TAKE_PROFIT_PCT), 4),
            )
        else:
            split_a = max(first_buy['qty'] // 2, 1)
            split_b = first_buy['qty'] - split_a
            if split_b == 0:
                split_b = split_a
            service.confirm_position(run_a, first_buy['code'], split_a, first_buy['price'], reason='guardian seed A')
            service.confirm_position(run_b, first_buy['code'], split_b, first_buy['price'], reason='guardian seed B')
            target_code = first_buy['code']
            synthetic_exit_price = round(first_buy['price'] * (1 + TAKE_PROFIT_PCT), 4)

        account_positions_before = repository.list_account_positions(service.account_id)
        total_qty = sum(item['qty'] for item in account_positions_before if item['code'] == target_code)
        guardian_result = service.confirm_account_exit(
            account_id=service.account_id,
            code=target_code,
            qty=total_qty,
            exit_price=synthetic_exit_price,
            reason='guardian replay exit',
        )

        return {
            'skipped': False,
            'accountId': service.account_id,
            'code': target_code,
            'exitPrice': synthetic_exit_price,
            'before': {
                'runA': repository.list_executions(run_a),
                'runB': repository.list_executions(run_b),
                'accountPositions': account_positions_before,
            },
            'result': guardian_result,
            'after': {
                'runA': {
                    'positions': repository.list_strategy_positions(run_a),
                    'executions': repository.list_executions(run_a),
                },
                'runB': {
                    'positions': repository.list_strategy_positions(run_b),
                    'executions': repository.list_executions(run_b),
                },
                'accountPositions': repository.list_account_positions(service.account_id),
            },
            'checks': {
                'account_positions_cleared': repository.list_account_positions(service.account_id) == [],
                'allocations_recorded': len(guardian_result['allocations']) > 0,
            },
        }


def build_chart_payload(code, bars, trades):
    chart_trades = [
        {
            'time': trade['time'],
            'code': trade['code'],
            'side': trade['side'],
            'price': trade['price'],
            'qty': trade['qty'],
            'reason': trade['reason'],
        }
        for trade in trades
        if trade['code'] == code
    ]
    chart_bars = [
        {
            'time': bar.get('time_key'),
            'open': bar.get('open', bar.get('close')),
            'high': bar.get('high', bar.get('close')),
            'low': bar.get('low', bar.get('close')),
            'close': bar.get('close'),
            'volume': bar.get('volume'),
        }
        for bar in bars
    ]
    return {
        'code': code,
        'bars': chart_bars,
        'trades': chart_trades,
    }


def run_replay_validation(args):
    backtest_result, bars_by_code, strategy_kwargs = run_backtest(args)
    workflow_result = replay_strategy_trades(backtest_result, args, strategy_kwargs)
    guardian_result = replay_guardian_exit(backtest_result, args)
    code = strategy_kwargs['codes'][0]

    return {
        'input': {
            'strategy': args.strategy,
            'strategyParams': strategy_kwargs,
            'start': args.start,
            'end': args.end,
        },
        'backtest': {
            'summary': backtest_result['summary'],
            'tradeCount': len(backtest_result['trades']),
            'trades': backtest_result['trades'],
        },
        'workflowReplay': workflow_result,
        'guardianReplay': guardian_result,
        'chart': build_chart_payload(code, bars_by_code.get(code, []), backtest_result['trades']),
    }


def main():
    args = parse_args()
    result = run_replay_validation(args)

    print(json.dumps(result['backtest']['summary'], ensure_ascii=False, indent=2))
    print(json.dumps(result['workflowReplay']['checks'], ensure_ascii=False, indent=2))
    print(json.dumps(result['guardianReplay']['checks'], ensure_ascii=False, indent=2))

    if args.report_file:
        report_path = Path(args.report_file)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(f'完整验证报告已写入: {report_path}')


if __name__ == '__main__':
    main()
