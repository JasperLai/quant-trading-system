#!/usr/bin/env python3
"""
回测账户与仓位模型。
"""

from backend.core.config import STOP_LOSS_PCT, TAKE_PROFIT_PCT


class BacktestPortfolio:
    def __init__(self, initial_cash=100000.0, commission_rate=0.001, slippage=0.0):
        self.initial_cash = float(initial_cash)
        self.cash = float(initial_cash)
        self.commission_rate = commission_rate
        self.slippage = slippage
        self.positions = {}
        self.trades = []
        self.equity_curve = []

    def get_position_info(self, code):
        return self.positions.get(code)

    def get_position_qty(self, code):
        info = self.get_position_info(code)
        return info['qty'] if info else 0

    def _commission(self, gross_amount):
        return abs(gross_amount) * self.commission_rate

    def buy(
        self,
        code,
        qty,
        price,
        time_key,
        stop_loss_pct=STOP_LOSS_PCT,
        take_profit_pct=TAKE_PROFIT_PCT,
        reason='均线金叉买入',
    ):
        fill_price = price + self.slippage
        gross_amount = fill_price * qty
        commission = self._commission(gross_amount)
        total_cost = gross_amount + commission
        if total_cost > self.cash:
            return False

        existing = self.positions.get(code)
        if existing is None:
            total_qty = qty
            avg_entry = fill_price
            entry_time = time_key
            total_cost_basis = total_cost
        else:
            total_qty = existing['qty'] + qty
            avg_entry = (
                existing['entry'] * existing['qty'] + fill_price * qty
            ) / total_qty
            entry_time = existing.get('entry_time', time_key)
            total_cost_basis = existing['cost_basis_total'] + total_cost

        self.cash -= total_cost
        self.positions[code] = {
            'qty': total_qty,
            'entry': avg_entry,
            'cost_basis_total': round(total_cost_basis, 4),
            'cost_basis_per_share': round(total_cost_basis / total_qty, 4),
            'entry_time': entry_time,
            'stop': round(avg_entry * (1 + stop_loss_pct), 4),
            'profit': round(avg_entry * (1 + take_profit_pct), 4),
            'stop_pct': stop_loss_pct,
            'profit_pct': take_profit_pct,
            'reason': reason,
        }
        self.trades.append(
            {
                'time': time_key,
                'code': code,
                'side': 'BUY',
                'qty': qty,
                'price': round(fill_price, 4),
                'commission': round(commission, 4),
                'cash_after': round(self.cash, 4),
                'reason': reason,
            }
        )
        return True

    def sell(self, code, price, time_key, reason):
        existing = self.positions.get(code)
        if existing is None:
            return None

        qty = existing['qty']
        fill_price = price - self.slippage
        gross_amount = fill_price * qty
        commission = self._commission(gross_amount)
        realized_pnl = gross_amount - commission - existing['cost_basis_total']
        self.cash += gross_amount - commission
        self.positions.pop(code, None)
        trade = {
            'time': time_key,
            'code': code,
            'side': 'SELL',
            'qty': qty,
            'price': round(fill_price, 4),
            'commission': round(commission, 4),
            'cash_after': round(self.cash, 4),
            'reason': reason,
            'realized_pnl': round(realized_pnl, 4),
        }
        self.trades.append(trade)
        return trade

    def evaluate_risk(self, code, price, time_key):
        pos = self.positions.get(code)
        if pos is None:
            return None
        if price <= pos['stop']:
            return self.sell(code, price, time_key, 'STOP_LOSS')
        if price >= pos['profit']:
            return self.sell(code, price, time_key, 'TAKE_PROFIT')
        return None

    def mark_equity(self, time_key, latest_prices):
        market_value = 0.0
        for code, pos in self.positions.items():
            last_price = latest_prices.get(code, pos['entry'])
            market_value += pos['qty'] * last_price
        equity = self.cash + market_value
        self.equity_curve.append({'time': time_key, 'equity': round(equity, 4), 'cash': round(self.cash, 4)})
        return equity
