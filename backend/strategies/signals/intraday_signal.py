#!/usr/bin/env python3
"""日内策略纯信号层。"""

DEFAULT_CODES = ['HK.03690']
DEFAULT_ORDER_QTY = 100
DEFAULT_BREAKOUT_PCT = 0.004
DEFAULT_PULLBACK_PCT = 0.003
DEFAULT_ENTRY_START_TIME = '09:45:00'
DEFAULT_FLAT_TIME = '15:45:00'


class IntradayBreakoutSignal:
    """适合模拟盘联调的日内突破策略。"""

    strategy_name = 'intraday_breakout_test'
    requires_daily_bars = False

    def __init__(
        self,
        codes=DEFAULT_CODES,
        order_qty=DEFAULT_ORDER_QTY,
        breakout_pct=DEFAULT_BREAKOUT_PCT,
        pullback_pct=DEFAULT_PULLBACK_PCT,
        entry_start_time=DEFAULT_ENTRY_START_TIME,
        flat_time=DEFAULT_FLAT_TIME,
    ):
        self.codes = list(codes)
        self.order_qty = order_qty
        self.breakout_pct = breakout_pct
        self.pullback_pct = pullback_pct
        self.entry_start_time = entry_start_time
        self.flat_time = flat_time

        self.short_ma_period = 0
        self.long_ma_period = 0
        self.prices = {code: [] for code in self.codes}
        self.bar_time_keys = {code: [] for code in self.codes}
        self.last_short_ma = {code: 0 for code in self.codes}
        self.last_long_ma = {code: 0 for code in self.codes}

        self.pending_buys = set()
        self.pending_sells = {}
        self.session_date = {code: None for code in self.codes}
        self.session_open = {code: None for code in self.codes}
        self.reference_price = {code: None for code in self.codes}
        self.session_high = {code: None for code in self.codes}
        self.traded_today = {code: False for code in self.codes}

    @staticmethod
    def _to_float(value):
        if value in (None, '', 'N/A'):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _split_time_key(time_key):
        if not time_key:
            return None, None
        parts = str(time_key).split(' ', 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        return parts[0], None

    def _extract_trade_date(self, quote_data):
        date_from_key, _ = self._split_time_key(quote_data.get('time_key'))
        return quote_data.get('data_date') or date_from_key or 'unknown-date'

    def _extract_trade_time(self, quote_data):
        _, time_from_key = self._split_time_key(quote_data.get('time_key'))
        return quote_data.get('data_time') or time_from_key or '00:00:00'

    def _reset_session(self, code, trade_date, open_price, reference_price, last_price):
        session_open = open_price if open_price is not None else last_price
        reference = reference_price if reference_price is not None else session_open
        self.session_date[code] = trade_date
        self.session_open[code] = session_open
        self.reference_price[code] = reference
        self.session_high[code] = last_price
        self.traded_today[code] = False

    def _sync_session_state(self, quote_data):
        code = quote_data['code']
        last_price = self._to_float(quote_data.get('last_price')) or 0.0
        trade_date = self._extract_trade_date(quote_data)
        open_price = self._to_float(quote_data.get('open_price') or quote_data.get('open'))

        prev_close = self._to_float(quote_data.get('prev_close_price'))
        if prev_close is None and len(self.prices.get(code, [])) >= 2:
            prev_close = self.prices[code][-2]
        if prev_close is None and self.prices.get(code):
            prev_close = self.prices[code][-1]

        reference_candidates = [value for value in [open_price, prev_close] if value is not None]
        reference_price = max(reference_candidates) if reference_candidates else last_price

        if self.session_date.get(code) != trade_date:
            self._reset_session(code, trade_date, open_price, reference_price, last_price)
        else:
            if self.session_open.get(code) is None and open_price is not None:
                self.session_open[code] = open_price
            if self.reference_price.get(code) is None:
                self.reference_price[code] = reference_price
            self.session_high[code] = max(self.session_high.get(code) or last_price, last_price)

        return {
            'trade_date': trade_date,
            'trade_time': self._extract_trade_time(quote_data),
            'last_price': last_price,
            'reference_price': self.reference_price[code],
            'session_high': self.session_high[code],
        }

    def update_bar(self, bar_data):
        code = bar_data['code']
        close_price = self._to_float(bar_data.get('close')) or 0.0
        time_key = bar_data.get('time_key')
        if code not in self.prices:
            self.prices[code] = []
            self.bar_time_keys[code] = []

        if not self.bar_time_keys[code] or self.bar_time_keys[code][-1] != time_key:
            self.bar_time_keys[code].append(time_key)
            self.prices[code].append(close_price)
        else:
            self.prices[code][-1] = close_price

        return {
            'code': code,
            'time_key': time_key,
            'close': close_price,
            'count': len(self.prices[code]),
            'appended': True,
        }

    def refresh_reference_ma(self, code):
        return None, None

    def startup_lines(self):
        return [
            f"启动策略: {self.strategy_name}",
            f"代码: {', '.join(self.codes)}",
            f"突破阈值: {self.breakout_pct * 100:.2f}%",
            f"回撤卖出阈值: {self.pullback_pct * 100:.2f}%",
            f"入场开始时间: {self.entry_start_time}",
            f"日内平仓时间: {self.flat_time}",
            f"单次下单数量: {self.order_qty}",
        ]

    def format_quote_log(self, result):
        return "[日内报价] %s 实时价: %.2f | 参考价: %.2f | 日内高点: %.2f | 时间: %s" % (
            result['code'],
            result['price'],
            result['reference_price'],
            result['session_high'],
            result['trade_time'],
        )

    def initial_state_lines(self):
        return []

    def get_pending_buy_qty(self, code):
        return self.order_qty if code in self.pending_buys else 0

    def add_pending_buy(self, code, qty):
        self.pending_buys.add(code)

    def clear_pending_buy(self, code, qty=None):
        self.pending_buys.discard(code)

    def can_send_buy(self, code, position_qty, qty):
        return position_qty == 0 and code not in self.pending_buys and not self.traded_today.get(code, False)

    def get_pending_sell_qty(self, code):
        return self.pending_sells.get(code, 0)

    def add_pending_sell(self, code, qty):
        self.pending_sells[code] = qty

    def clear_pending_sell(self, code, qty=None):
        self.pending_sells.pop(code, None)

    def can_send_sell(self, code, position_qty, qty):
        return position_qty > 0 and qty > 0 and code not in self.pending_sells

    def replace_pending_orders(self, pending_orders):
        self.pending_buys = {item['code'] for item in pending_orders if item['side'] == 'BUY'}
        self.pending_sells = {item['code']: item['qty'] for item in pending_orders if item['side'] == 'SELL'}

    def evaluate_quote(self, quote_data, position_qty=0):
        code = quote_data['code']
        session = self._sync_session_state(quote_data)
        price = session['last_price']
        trade_time = session['trade_time']
        reference_price = session['reference_price'] or price
        session_high = max(session['session_high'] or price, price)
        self.session_high[code] = session_high

        action = None
        signal_qty = 0
        reason = None

        if position_qty > 0:
            signal_qty = position_qty
            if trade_time >= self.flat_time:
                if self.can_send_sell(code, position_qty, signal_qty):
                    self.add_pending_sell(code, signal_qty)
                    action = 'SELL'
                    reason = '日内收盘前平仓'
            elif price <= session_high * (1 - self.pullback_pct):
                if self.can_send_sell(code, position_qty, signal_qty):
                    self.add_pending_sell(code, signal_qty)
                    action = 'SELL'
                    reason = '日内冲高回落卖出'
        else:
            breakout_price = reference_price * (1 + self.breakout_pct)
            if (
                trade_time >= self.entry_start_time
                and trade_time < self.flat_time
                and price >= breakout_price
                and self.can_send_buy(code, position_qty, self.order_qty)
            ):
                self.add_pending_buy(code, self.order_qty)
                self.traded_today[code] = True
                action = 'BUY'
                signal_qty = self.order_qty
                reason = '日内突破买入'

        return {
            'code': code,
            'price': price,
            'reference_price': reference_price,
            'session_high': session_high,
            'trade_time': trade_time,
            'action': action,
            'reason': reason,
            'qty': signal_qty if action is not None else 0,
        }
