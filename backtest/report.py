#!/usr/bin/env python3
"""
回测结果汇总。
"""


def build_backtest_report(result):
    equity_curve = result['equity_curve']
    trades = result['trades']
    initial_cash = result['initial_cash']
    final_equity = result['final_equity']

    max_equity = initial_cash
    max_drawdown = 0.0
    for point in equity_curve:
        equity = point['equity']
        if equity > max_equity:
            max_equity = equity
        drawdown = 0.0 if max_equity == 0 else (max_equity - equity) / max_equity
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    sell_trades = [trade for trade in trades if trade['side'] == 'SELL']
    wins = [trade for trade in sell_trades if trade.get('realized_pnl', 0) > 0]

    return {
        'strategy': result['strategy'],
        'initial_cash': round(initial_cash, 4),
        'final_equity': round(final_equity, 4),
        'return_pct': round((final_equity - initial_cash) / initial_cash * 100, 4),
        'trade_count': len(trades),
        'closed_trade_count': len(sell_trades),
        'win_rate': round((len(wins) / len(sell_trades) * 100) if sell_trades else 0.0, 4),
        'max_drawdown_pct': round(max_drawdown * 100, 4),
        'open_positions': result['open_positions'],
    }
