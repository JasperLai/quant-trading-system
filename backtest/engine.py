#!/usr/bin/env python3
"""
回测引擎。
"""

from backend.core.config import STOP_LOSS_PCT, TAKE_PROFIT_PCT
from backtest.portfolio import BacktestPortfolio
from backtest.report import build_backtest_report


class BacktestEngine:
    """日线回测引擎。"""

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


class MinuteBacktestEngine:
    """
    分钟级回测引擎。

    这套引擎与日线引擎的差异有两点：
    1. `time_key` 细化到分钟，事件按分钟 bar 驱动。
    2. 信号层收到的 quote payload 会补全 session 级字段，例如 `open_price`、
       `prev_close_price`、`data_date`、`data_time`，便于日内策略复用实时逻辑。
    """

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

    @staticmethod
    def _split_time_key(time_key):
        if not time_key:
            return '', ''
        parts = str(time_key).split(' ', 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        return parts[0], ''

    def _build_quote_payload(self, event, session_state, previous_close_by_code):
        code = event['code']
        time_key = event.get('time_key')
        trade_date, trade_time = self._split_time_key(time_key)
        close_price = event['close']
        bar_open = event.get('open', close_price)

        current_session = session_state.get(code)
        if current_session is None or current_session['date'] != trade_date:
            session_state[code] = {
                'date': trade_date,
                'open': bar_open,
            }

        return {
            'code': code,
            'last_price': close_price,
            'time_key': time_key,
            'open_price': session_state[code]['open'],
            'prev_close_price': previous_close_by_code.get(code),
            'data_date': trade_date,
            'data_time': trade_time,
        }

    def run(self, bars_by_code):
        latest_prices = {}
        events = self._iter_events(bars_by_code)
        previous_close_by_code = {}
        session_state = {}

        for index, event in enumerate(events):
            code = event['code']
            time_key = event.get('time_key')
            close_price = event['close']
            bar_high = event.get('high', close_price)
            bar_low = event.get('low', close_price)
            bought_on_bar = False

            self.signal.update_bar(event)
            latest_prices[code] = close_price

            decision = self.signal.evaluate_quote(
                self._build_quote_payload(event, session_state, previous_close_by_code),
                position_qty=self.portfolio.get_position_qty(code),
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

            if not bought_on_bar:
                self.portfolio.evaluate_risk_from_bar(code, high=bar_high, low=bar_low, close=close_price, time_key=time_key)

            previous_close_by_code[code] = close_price

            next_time_key = events[index + 1].get('time_key') if index + 1 < len(events) else None
            if next_time_key != time_key:
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


class TickBacktestEngine:
    """
    Tick 级逐笔回测引擎。

    假设输入事件与 FUTU 的 get_rt_ticker() 结果结构兼容，至少包含：
    - code
    - time / time_key
    - price
    - volume

    这套引擎是“逐笔 quote 驱动”模型：
    - 不依赖 K 线聚合
    - 每笔 tick 都会驱动一次 signal.evaluate_quote()
    - 风控检查也按每笔 tick 执行
    """

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

    @staticmethod
    def _normalize_tick(event):
        time_key = event.get('time_key') or event.get('time')
        price = event.get('price')
        if price is None:
            price = event.get('last_price')
        return {
            **event,
            'time_key': time_key,
            'last_price': float(price),
        }

    def _iter_events(self, ticks_by_code):
        events = []
        for code, ticks in ticks_by_code.items():
            for tick in ticks:
                event = dict(self._normalize_tick(tick))
                event['code'] = code
                events.append(event)
        events.sort(key=lambda item: (item.get('time_key', ''), item['code']))
        return events

    @staticmethod
    def _split_time_key(time_key):
        if not time_key:
            return '', ''
        parts = str(time_key).split(' ', 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        return parts[0], ''

    def _build_quote_payload(self, tick, session_state, previous_close_by_code):
        code = tick['code']
        time_key = tick.get('time_key')
        trade_date, trade_time = self._split_time_key(time_key)
        last_price = tick['last_price']

        current_session = session_state.get(code)
        if current_session is None or current_session['date'] != trade_date:
            open_price = float(tick.get('open_price') or tick.get('open') or last_price)
            session_state[code] = {
                'date': trade_date,
                'open': open_price,
            }

        return {
            'code': code,
            'last_price': last_price,
            'time_key': time_key,
            'open_price': float(tick.get('open_price') or tick.get('open') or session_state[code]['open']),
            'prev_close_price': tick.get('prev_close_price', previous_close_by_code.get(code)),
            'data_date': tick.get('data_date', trade_date),
            'data_time': tick.get('data_time', trade_time),
            'volume': tick.get('volume'),
        }

    def run(self, ticks_by_code):
        latest_prices = {}
        previous_close_by_code = {}
        session_state = {}
        events = self._iter_events(ticks_by_code)

        for event in events:
            code = event['code']
            time_key = event['time_key']
            price = event['last_price']
            latest_prices[code] = price

            decision = self.signal.evaluate_quote(
                self._build_quote_payload(event, session_state, previous_close_by_code),
                position_qty=self.portfolio.get_position_qty(code),
            )

            if decision and decision['action'] == 'BUY':
                bought = self.portfolio.buy(
                    code=code,
                    qty=decision['qty'],
                    price=price,
                    time_key=time_key,
                    stop_loss_pct=self.stop_loss_pct,
                    take_profit_pct=self.take_profit_pct,
                    reason=decision['reason'],
                )
                if bought:
                    self.signal.clear_pending_buy(code, decision['qty'])
            elif decision and decision['action'] == 'SELL':
                sold = self.portfolio.sell(code, price, time_key, decision['reason'])
                if sold is not None:
                    self.signal.clear_pending_sell(code, decision['qty'])

            self.portfolio.evaluate_risk(code, price, time_key)
            previous_close_by_code[code] = price
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
