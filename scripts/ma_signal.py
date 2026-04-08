#!/usr/bin/env python3
"""
均线策略纯信号层。

负责：
1. 维护历史 K 线样本
2. 计算短期/长期 MA
3. 根据持仓和 pending 状态决定是否发出 BUY 信号

不负责：
1. OpenD 连接
2. 信号发送
3. 持仓落地与风控执行
"""

SHORT_MA = 5
LONG_MA = 20
CODES = ['HK.03690', 'HK.09896', 'SZ.000001']
DEFAULT_ORDER_QTY = 100
HISTORY_BUFFER_BARS = 10


class BaseMaSignal:
    strategy_name = 'base_ma_cross'

    def __init__(
        self,
        codes=CODES,
        short_ma=SHORT_MA,
        long_ma=LONG_MA,
        order_qty=DEFAULT_ORDER_QTY,
    ):
        self.codes = list(codes)
        self.short_ma_period = short_ma
        self.long_ma_period = long_ma
        self.order_qty = order_qty

        self.prices = {code: [] for code in self.codes}
        self.bar_time_keys = {code: [] for code in self.codes}
        self.last_short_ma = {code: 0 for code in self.codes}
        self.last_long_ma = {code: 0 for code in self.codes}

    def calculate_ma(self, prices, period):
        if len(prices) < period:
            return None
        return sum(prices[-period:]) / period

    def calculate_live_ma(self, code, latest_price):
        history = self.prices[code]
        if len(history) < self.long_ma_period:
            return None, None

        live_prices = history[:-1] + [latest_price]
        short_ma = self.calculate_ma(live_prices, self.short_ma_period)
        long_ma = self.calculate_ma(live_prices, self.long_ma_period)
        return short_ma, long_ma

    def update_bar(self, bar_data):
        code = bar_data['code']
        close_price = bar_data['close']
        time_key = bar_data.get('time_key')

        if code not in self.prices:
            self.prices[code] = []
            self.bar_time_keys[code] = []
            self.last_short_ma[code] = 0
            self.last_long_ma[code] = 0

        appended = False
        if not self.bar_time_keys[code] or self.bar_time_keys[code][-1] != time_key:
            self.bar_time_keys[code].append(time_key)
            self.prices[code].append(close_price)
            appended = True
        else:
            self.prices[code][-1] = close_price

        max_bars = self.long_ma_period + HISTORY_BUFFER_BARS
        if len(self.prices[code]) > max_bars:
            self.prices[code] = self.prices[code][-max_bars:]
            self.bar_time_keys[code] = self.bar_time_keys[code][-max_bars:]

        return {
            'code': code,
            'time_key': time_key,
            'close': close_price,
            'count': len(self.prices[code]),
            'appended': appended,
        }

    def refresh_reference_ma(self, code):
        short_ma = self.calculate_ma(self.prices[code], self.short_ma_period)
        long_ma = self.calculate_ma(self.prices[code], self.long_ma_period)
        self.last_short_ma[code] = short_ma if short_ma else 0
        self.last_long_ma[code] = long_ma if long_ma else 0
        return short_ma, long_ma

    def get_pending_qty(self, code):
        raise NotImplementedError

    def add_pending_buy(self, code, qty):
        raise NotImplementedError

    def clear_pending_buy(self, code, qty=None):
        raise NotImplementedError

    def can_send_buy(self, code, position_qty, qty):
        raise NotImplementedError

    def evaluate_quote(self, quote_data, position_qty=0):
        code = quote_data['code']
        price = quote_data['last_price']

        if len(self.prices.get(code, [])) < self.long_ma_period:
            return None

        short_ma, long_ma = self.calculate_live_ma(code, price)
        if short_ma is None or long_ma is None:
            return None

        if (
            abs(short_ma - self.last_short_ma[code]) < 0.01
            and abs(long_ma - self.last_long_ma[code]) < 0.01
        ):
            return None

        prev_short_ma = self.last_short_ma[code]
        prev_long_ma = self.last_long_ma[code]
        self.last_short_ma[code] = short_ma
        self.last_long_ma[code] = long_ma

        qty = self.order_qty
        should_buy = False
        if prev_short_ma <= prev_long_ma and short_ma > long_ma:
            should_buy = self.can_send_buy(code, position_qty, qty)
            if should_buy:
                self.add_pending_buy(code, qty)

        return {
            'code': code,
            'price': price,
            'short_ma': short_ma,
            'long_ma': long_ma,
            'prev_short_ma': prev_short_ma,
            'prev_long_ma': prev_long_ma,
            'buy_signal': should_buy,
            'qty': qty if should_buy else 0,
        }


class SinglePositionMaSignal(BaseMaSignal):
    strategy_name = 'single_position_ma_cross'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pending_buys = set()

    def get_pending_qty(self, code):
        return self.order_qty if code in self.pending_buys else 0

    def add_pending_buy(self, code, qty):
        self.pending_buys.add(code)

    def clear_pending_buy(self, code, qty=None):
        self.pending_buys.discard(code)

    def can_send_buy(self, code, position_qty, qty):
        return position_qty == 0 and code not in self.pending_buys


class PyramidingMaSignal(BaseMaSignal):
    strategy_name = 'pyramiding_ma_cross'

    def __init__(self, *args, max_position_per_stock=300, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_position_per_stock = max_position_per_stock
        self.pending_buys = {}

    def get_pending_qty(self, code):
        return self.pending_buys.get(code, 0)

    def add_pending_buy(self, code, qty):
        self.pending_buys[code] = self.pending_buys.get(code, 0) + qty

    def clear_pending_buy(self, code, qty=None):
        if code not in self.pending_buys:
            return
        if qty is None or qty >= self.pending_buys[code]:
            self.pending_buys.pop(code, None)
            return
        self.pending_buys[code] -= qty

    def can_send_buy(self, code, position_qty, qty):
        pending_qty = self.get_pending_qty(code)
        return position_qty + pending_qty + qty <= self.max_position_per_stock
