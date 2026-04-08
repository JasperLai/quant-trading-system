#!/usr/bin/env python3
"""
日线回测引擎。
"""

from backtest.portfolio import BacktestPortfolio
from backtest.report import build_backtest_report


class BacktestEngine:
    def __init__(
        self,
        signal,
        initial_cash=100000.0,
        commission_rate=0.001,
        slippage=0.0,
        stop_loss_pct=-0.20,
        take_profit_pct=0.30,
    ):
        self.signal = signal
        self.portfolio = BacktestPortfolio(
            initial_cash=initial_cash,
            commission_rate=commission_rate,
            slippage=slippage,
        )
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct

    def _iter_events(self, bars_by_code):
        events = []
        for code, bars in bars_by_code.items():
            for bar in bars:
                event = dict(bar)
                event['code'] = code
                events.append(event)
        events.sort(key=lambda item: (item.get('time_key', ''), item['code']))
        return events

    def run(self, bars_by_code):
        latest_prices = {}
        for event in self._iter_events(bars_by_code):
            code = event['code']
            time_key = event.get('time_key')
            close_price = event['close']

            self.signal.update_bar(event)
            latest_prices[code] = close_price

            position_qty = self.portfolio.get_position_qty(code)
            decision = self.signal.evaluate_quote(
                {'code': code, 'last_price': close_price, 'time_key': time_key},
                position_qty=position_qty,
            )

            if decision and decision['action'] == 'BUY':
                bought = self.portfolio.buy(
                    code=code,
                    qty=decision['qty'],
                    price=close_price,
                    time_key=time_key,
                    stop_loss_pct=self.stop_loss_pct,
                    take_profit_pct=self.take_profit_pct,
                    reason=decision['reason'],
                )
                self.signal.clear_pending_buy(code, decision['qty'])
            elif decision and decision['action'] == 'SELL':
                sold = self.portfolio.sell(code, close_price, time_key, decision['reason'])
                if sold is not None:
                    self.signal.clear_pending_sell(code, decision['qty'])
                else:
                    self.signal.clear_pending_sell(code, decision['qty'])

            self.portfolio.evaluate_risk(code, close_price, time_key)
            self.portfolio.mark_equity(time_key, latest_prices)

        final_equity = self.portfolio.equity_curve[-1]['equity'] if self.portfolio.equity_curve else self.portfolio.cash
        result = {
            'strategy': self.signal.strategy_name,
            'initial_cash': self.portfolio.initial_cash,
            'final_equity': final_equity,
            'trades': self.portfolio.trades,
            'equity_curve': self.portfolio.equity_curve,
            'open_positions': self.portfolio.positions.copy(),
        }
        result['summary'] = build_backtest_report(result)
        return result
