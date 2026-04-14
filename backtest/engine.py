#!/usr/bin/env python3
"""
日线回测引擎。
"""

from backend.core.config import STOP_LOSS_PCT, TAKE_PROFIT_PCT
from backtest.portfolio import BacktestPortfolio
from backtest.report import build_backtest_report


class BacktestEngine:
    def __init__(
        self,
        signal,
        initial_cash=100000.0,
        commission_rate=0.001,
        slippage=0.0,
        stop_loss_pct=STOP_LOSS_PCT,
        take_profit_pct=TAKE_PROFIT_PCT,
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
        events = self._iter_events(bars_by_code)
        for index, event in enumerate(events):
            code = event['code']
            time_key = event.get('time_key')
            close_price = event['close']
            bought_on_bar = False

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
                if bought:
                    self.signal.clear_pending_buy(code, decision['qty'])
                    bought_on_bar = True
            elif decision and decision['action'] == 'SELL':
                sold = self.portfolio.sell(code, close_price, time_key, decision['reason'])
                if sold is not None:
                    self.signal.clear_pending_sell(code, decision['qty'])

            # 日线回测里，当前 bar 收盘才形成信号，因此同一 bar 内不应再用同一个收盘价
            # 立即触发刚刚买入仓位的止损/止盈。否则会出现“先买后止损”的不真实结果。
            if not bought_on_bar:
                self.portfolio.evaluate_risk(code, close_price, time_key)

            next_time_key = events[index + 1].get('time_key') if index + 1 < len(events) else None
            if next_time_key != time_key:
                # 同一 time_key 下的所有标的都处理完之后，才记录一次权益。
                # 否则会出现“同一天多条权益点，其中部分股票用新价、部分仍用旧价”的失真曲线。
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
