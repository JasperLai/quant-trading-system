#!/usr/bin/env python3
"""Zipline 输出结果适配层。"""

from backtest.report import build_backtest_report


def _normalize_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        return list(value)
    except TypeError:
        return []


def _code_from_identifier(identifier, sid_map, symbol_map):
    if identifier is None:
        return 'UNKNOWN'
    if isinstance(identifier, dict):
        if identifier.get('symbol') in symbol_map:
            return symbol_map[identifier['symbol']]
        if identifier.get('sid') in sid_map:
            return sid_map[identifier['sid']]
    symbol = getattr(identifier, 'symbol', None)
    if symbol in symbol_map:
        return symbol_map[symbol]
    sid = getattr(identifier, 'sid', None)
    if sid in sid_map:
        return sid_map[sid]
    if isinstance(identifier, int) and identifier in sid_map:
        return sid_map[identifier]
    return str(identifier)


def adapt_zipline_result(perf, prepared_bundle, strategy_name, initial_cash):
    frame = perf.reset_index().rename(columns={'index': 'time'})
    symbol_map = {zipline_symbol: code for code, zipline_symbol in prepared_bundle.symbol_map.items()}
    sid_map = {int(sid): code for sid, code in prepared_bundle.sid_map.items()}

    equity_curve = []
    trades = []
    seen_transactions = set()

    for _, row in frame.iterrows():
        time_value = row.get('time')
        portfolio_value = row.get('portfolio_value')
        if portfolio_value is None:
            portfolio_value = row.get('ending_cash', initial_cash)
        cash_value = row.get('ending_cash', row.get('cash', 0.0))
        equity_curve.append(
            {
                'time': str(time_value),
                'equity': round(float(portfolio_value), 4),
                'cash': round(float(cash_value), 4),
            }
        )

        for transaction in _normalize_list(row.get('transactions')):
            order_id = transaction.get('order_id') or transaction.get('id') or (transaction.get('dt'), transaction.get('amount'))
            if order_id in seen_transactions:
                continue
            seen_transactions.add(order_id)
            amount = int(transaction.get('amount', 0))
            if amount == 0:
                continue
            side = 'BUY' if amount > 0 else 'SELL'
            qty = abs(amount)
            price = float(transaction.get('price', 0.0))
            code = _code_from_identifier(transaction.get('sid'), sid_map, symbol_map)
            trades.append(
                {
                    'time': str(transaction.get('dt') or time_value),
                    'code': code,
                    'side': side,
                    'qty': qty,
                    'price': round(price, 4),
                    'commission': round(float(transaction.get('commission', 0.0)), 4),
                    'cash_after': round(float(cash_value), 4),
                    'reason': 'ZIPLINE_ORDER',
                    **(
                        {
                            'realized_pnl': round(float(transaction.get('realized_pnl')), 4),
                        }
                        if side == 'SELL' and transaction.get('realized_pnl') is not None
                        else {}
                    ),
                }
            )

    open_positions = {}
    if not frame.empty:
        last_positions = _normalize_list(frame.iloc[-1].get('positions'))
        for position in last_positions:
            amount = int(position.get('amount', 0))
            if amount == 0:
                continue
            code = _code_from_identifier(position.get('sid'), sid_map, symbol_map)
            cost_basis = float(position.get('cost_basis', 0.0))
            open_positions[code] = {
                'qty': amount,
                'entry': round(cost_basis, 4),
            }

    final_equity = equity_curve[-1]['equity'] if equity_curve else initial_cash
    result = {
        'strategy': strategy_name,
        'initial_cash': float(initial_cash),
        'final_equity': float(final_equity),
        'trades': trades,
        'equity_curve': equity_curve,
        'open_positions': open_positions,
    }
    result['summary'] = build_backtest_report(result)
    return result
