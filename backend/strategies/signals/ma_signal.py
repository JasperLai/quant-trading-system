#!/usr/bin/env python3
"""
均线策略纯信号层。
"""

SHORT_MA = 5
LONG_MA = 20
CODES = ['HK.03690', 'HK.09896', 'SZ.000001']
DEFAULT_ORDER_QTY = 100
HISTORY_BUFFER_BARS = 10


class BaseMaSignal:
    """
    均线策略的纯信号基类。

    这个类只做两件事：
    1. 维护可用于计算均线的价格序列。
    2. 在收到最新价格时判断是否产生 BUY / SELL 意图。

    它刻意不接触 OpenD、日志、OpenClaw、持仓监控等运行时依赖，
    这样同一套逻辑既可以被实时策略复用，也可以被回测引擎复用。
    """

    strategy_name = 'base_ma_cross'
    requires_daily_bars = True

    def __init__(self, codes=CODES, short_ma=SHORT_MA, long_ma=LONG_MA, order_qty=DEFAULT_ORDER_QTY):
        self.codes = list(codes)
        self.short_ma_period = short_ma
        self.long_ma_period = long_ma
        self.order_qty = order_qty

        # prices 和 bar_time_keys 一起维护一条按 time_key 去重的日线序列。
        self.prices = {code: [] for code in self.codes}
        self.bar_time_keys = {code: [] for code in self.codes}

        # last_short_ma / last_long_ma 保存上一次已经对外生效的均线状态。
        self.last_short_ma = {code: 0 for code in self.codes}
        self.last_long_ma = {code: 0 for code in self.codes}

    def calculate_ma(self, prices, period):
        """计算简单移动平均线；样本不足时返回 None。"""
        if len(prices) < period:
            return None
        return sum(prices[-period:]) / period

    def calculate_live_ma(self, code, latest_price):
        """
        用最新报价覆盖最后一根日线收盘价，计算盘中实时均线。
        """
        history = self.prices[code]
        if len(history) < self.long_ma_period:
            return None, None

        live_prices = history[:-1] + [latest_price]
        short_ma = self.calculate_ma(live_prices, self.short_ma_period)
        long_ma = self.calculate_ma(live_prices, self.long_ma_period)
        return short_ma, long_ma

    def update_bar(self, bar_data):
        """
        更新历史 bar 样本，并按 time_key 去重。
        """
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
        """
        用当前历史样本刷新参考均线。
        """
        short_ma = self.calculate_ma(self.prices[code], self.short_ma_period)
        long_ma = self.calculate_ma(self.prices[code], self.long_ma_period)
        self.last_short_ma[code] = short_ma if short_ma else 0
        self.last_long_ma[code] = long_ma if long_ma else 0
        return short_ma, long_ma

    def history_bar_count(self):
        return self.long_ma_period + 5

    def startup_lines(self):
        return [
            f"启动策略: {self.strategy_name}",
            f"代码: {', '.join(self.codes)}",
            f"短期均线周期: {self.short_ma_period}",
            f"长期均线周期: {self.long_ma_period}",
            f"单次下单数量: {self.order_qty}",
        ]

    def format_quote_log(self, result):
        return "[报价] %s 实时价: %.2f | 短期MA(%s): %.2f | 长期MA(%s): %.2f" % (
            result['code'],
            result['price'],
            self.short_ma_period,
            result['short_ma'],
            self.long_ma_period,
            result['long_ma'],
        )

    def initial_state_lines(self):
        lines = [f"当前均线状态: 短期MA({self.short_ma_period}) vs 长期MA({self.long_ma_period})"]
        for code in self.codes:
            lines.append(
                "  %s: 短期MA(%s)=%.2f, 长期MA(%s)=%.2f"
                % (code, self.short_ma_period, self.last_short_ma[code], self.long_ma_period, self.last_long_ma[code])
            )
        return lines

    def get_pending_buy_qty(self, code):
        raise NotImplementedError

    def add_pending_buy(self, code, qty):
        raise NotImplementedError

    def clear_pending_buy(self, code, qty=None):
        raise NotImplementedError

    def can_send_buy(self, code, position_qty, qty):
        raise NotImplementedError

    def get_pending_sell_qty(self, code):
        raise NotImplementedError

    def add_pending_sell(self, code, qty):
        raise NotImplementedError

    def clear_pending_sell(self, code, qty=None):
        raise NotImplementedError

    def can_send_sell(self, code, position_qty, qty):
        raise NotImplementedError

    def replace_pending_orders(self, pending_orders):
        raise NotImplementedError

    def evaluate_quote(self, quote_data, position_qty=0):
        """
        在最新报价到达时评估是否产生 BUY / SELL 意图。
        """
        code = quote_data['code']
        price = quote_data['last_price']

        if len(self.prices.get(code, [])) < self.long_ma_period:
            return None

        short_ma, long_ma = self.calculate_live_ma(code, price)
        if short_ma is None or long_ma is None:
            return None

        # 轻量去抖：报价变化过小不重复向上层报告。
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
        action = None
        signal_qty = 0
        reason = None

        # 当前采用“新金叉 / 新死叉事件触发”模型。
        if prev_short_ma <= prev_long_ma and short_ma > long_ma:
            if self.can_send_buy(code, position_qty, qty):
                self.add_pending_buy(code, qty)
                action = 'BUY'
                signal_qty = qty
                reason = '均线金叉买入'
        elif prev_short_ma >= prev_long_ma and short_ma < long_ma:
            signal_qty = position_qty
            if self.can_send_sell(code, position_qty, signal_qty):
                self.add_pending_sell(code, signal_qty)
                action = 'SELL'
                reason = '均线死叉卖出'

        return {
            'code': code,
            'price': price,
            'short_ma': short_ma,
            'long_ma': long_ma,
            'prev_short_ma': prev_short_ma,
            'prev_long_ma': prev_long_ma,
            'action': action,
            'reason': reason,
            'qty': signal_qty if action is not None else 0,
        }


class SinglePositionMaSignal(BaseMaSignal):
    """单仓模型：有持仓或已有 pending BUY 时不再继续买。"""

    strategy_name = 'single_position_ma_cross'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pending_buys = set()
        self.pending_sells = {}

    def get_pending_buy_qty(self, code):
        return self.order_qty if code in self.pending_buys else 0

    def add_pending_buy(self, code, qty):
        self.pending_buys.add(code)

    def clear_pending_buy(self, code, qty=None):
        self.pending_buys.discard(code)

    def can_send_buy(self, code, position_qty, qty):
        return position_qty == 0 and code not in self.pending_buys

    def get_pending_sell_qty(self, code):
        return self.pending_sells.get(code, 0)

    def add_pending_sell(self, code, qty):
        self.pending_sells[code] = qty

    def clear_pending_sell(self, code, qty=None):
        self.pending_sells.pop(code, None)

    def can_send_sell(self, code, position_qty, qty):
        return position_qty > 0 and code not in self.pending_sells and qty > 0

    def replace_pending_orders(self, pending_orders):
        buy_codes = {item['code'] for item in pending_orders if item['side'] == 'BUY'}
        sell_codes = {item['code']: item['qty'] for item in pending_orders if item['side'] == 'SELL'}
        self.pending_buys = buy_codes
        self.pending_sells = sell_codes


class PyramidingMaSignal(BaseMaSignal):
    """加仓模型：允许继续买，但总仓位不能超过单标的上限。"""

    strategy_name = 'pyramiding_ma_cross'

    def __init__(self, *args, max_position_per_stock=300, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_position_per_stock = max_position_per_stock
        self.pending_buys = {}
        self.pending_sells = {}

    def get_pending_buy_qty(self, code):
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
        # 已成交仓位和待确认仓位都要计入上限。
        pending_qty = self.get_pending_buy_qty(code)
        return position_qty + pending_qty + qty <= self.max_position_per_stock

    def get_pending_sell_qty(self, code):
        return self.pending_sells.get(code, 0)

    def add_pending_sell(self, code, qty):
        self.pending_sells[code] = self.pending_sells.get(code, 0) + qty

    def clear_pending_sell(self, code, qty=None):
        if code not in self.pending_sells:
            return
        if qty is None or qty >= self.pending_sells[code]:
            self.pending_sells.pop(code, None)
            return
        self.pending_sells[code] -= qty

    def can_send_sell(self, code, position_qty, qty):
        pending_qty = self.get_pending_sell_qty(code)
        return position_qty > 0 and qty > 0 and pending_qty == 0

    def replace_pending_orders(self, pending_orders):
        pending_buys = {}
        pending_sells = {}
        for item in pending_orders:
            if item['side'] == 'BUY':
                pending_buys[item['code']] = item['qty']
            elif item['side'] == 'SELL':
                pending_sells[item['code']] = item['qty']
        self.pending_buys = pending_buys
        self.pending_sells = pending_sells
