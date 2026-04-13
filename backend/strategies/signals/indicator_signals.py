#!/usr/bin/env python3
"""主流日线技术策略信号层。"""

import math


DEFAULT_CODES = ['HK.03690']
DEFAULT_ORDER_QTY = 100
HISTORY_BUFFER_BARS = 10


class BaseDailyIndicatorSignal:
    """基于日线收盘价的通用指标策略基类。"""

    strategy_name = 'base_daily_indicator'
    requires_daily_bars = True

    def __init__(self, codes=DEFAULT_CODES, order_qty=DEFAULT_ORDER_QTY):
        self.codes = list(codes)
        self.order_qty = order_qty
        # runtime 仍会读取这两个字段；非均线策略保留为 0。
        self.short_ma_period = 0
        self.long_ma_period = 0
        self.prices = {code: [] for code in self.codes}
        self.bar_time_keys = {code: [] for code in self.codes}
        self.last_short_ma = {code: 0 for code in self.codes}
        self.last_long_ma = {code: 0 for code in self.codes}
        self.pending_buys = set()
        self.pending_sells = {}

    def history_bar_count(self):
        return self.min_history_bars() + 5

    def min_history_bars(self):
        raise NotImplementedError

    def startup_lines(self):
        return [
            f"启动策略: {self.strategy_name}",
            f"代码: {', '.join(self.codes)}",
            f"单次下单数量: {self.order_qty}",
        ]

    def initial_state_lines(self):
        return []

    def format_history_init_log(self, code, bar_count):
        return f"  {code}: 获取到 {bar_count} 条K线"

    def calculate_ma(self, prices, period):
        if len(prices) < period:
            return None
        return sum(prices[-period:]) / period

    def calculate_live_prices(self, code, latest_price):
        history = self.prices.get(code, [])
        if not history:
            return []
        return history[:-1] + [latest_price]

    def update_bar(self, bar_data):
        code = bar_data['code']
        close_price = float(bar_data['close'])
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

        max_bars = self.history_bar_count() + HISTORY_BUFFER_BARS
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
        return None, None

    @staticmethod
    def _mean(values):
        if not values:
            return None
        return sum(values) / len(values)

    @staticmethod
    def _stddev(values):
        if not values:
            return None
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        return math.sqrt(variance)

    @staticmethod
    def _ema_series(values, period):
        if not values:
            return []
        alpha = 2 / (period + 1)
        ema_values = [values[0]]
        for value in values[1:]:
            ema_values.append(alpha * value + (1 - alpha) * ema_values[-1])
        return ema_values

    @staticmethod
    def _rsi(values, period):
        if len(values) <= period:
            return None
        deltas = [values[index] - values[index - 1] for index in range(1, len(values))]
        gains = [max(delta, 0) for delta in deltas]
        losses = [max(-delta, 0) for delta in deltas]
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        for index in range(period, len(gains)):
            avg_gain = ((avg_gain * (period - 1)) + gains[index]) / period
            avg_loss = ((avg_loss * (period - 1)) + losses[index]) / period
        if avg_loss == 0:
            return 100.0
        relative_strength = avg_gain / avg_loss
        return 100 - (100 / (1 + relative_strength))

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
        self.pending_buys = {item['code'] for item in pending_orders if item['side'] == 'BUY'}
        self.pending_sells = {item['code']: item['qty'] for item in pending_orders if item['side'] == 'SELL'}


class RsiReversionSignal(BaseDailyIndicatorSignal):
    strategy_name = 'rsi_reversion'

    def __init__(
        self,
        codes=DEFAULT_CODES,
        order_qty=DEFAULT_ORDER_QTY,
        rsi_period=14,
        oversold=30,
        overbought=70,
    ):
        super().__init__(codes=codes, order_qty=order_qty)
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.overbought = overbought
        self.last_rsi = {code: None for code in self.codes}

    def min_history_bars(self):
        return self.rsi_period + 2

    def startup_lines(self):
        return super().startup_lines() + [
            f"RSI周期: {self.rsi_period}",
            f"超卖阈值: {self.oversold}",
            f"超买阈值: {self.overbought}",
        ]

    def refresh_reference_ma(self, code):
        rsi = self._rsi(self.prices[code], self.rsi_period)
        self.last_rsi[code] = rsi
        return rsi, None

    def format_history_init_log(self, code, bar_count):
        rsi = self.last_rsi.get(code)
        if rsi is None:
            return f"  {code}: 获取到 {bar_count} 条K线"
        return f"  {code}: 获取到 {bar_count} 条K线 | RSI({self.rsi_period}): {rsi:.2f}"

    def format_quote_log(self, result):
        return "[RSI] %s 实时价: %.2f | RSI(%s): %.2f | 阈值: %.1f/%.1f" % (
            result['code'],
            result['price'],
            self.rsi_period,
            result['rsi'],
            self.oversold,
            self.overbought,
        )

    def initial_state_lines(self):
        lines = [f"当前 RSI 状态: RSI({self.rsi_period})"]
        for code in self.codes:
            rsi = self.last_rsi.get(code)
            lines.append(f"  {code}: RSI={rsi:.2f}" if rsi is not None else f"  {code}: RSI=样本不足")
        return lines

    def evaluate_quote(self, quote_data, position_qty=0):
        code = quote_data['code']
        price = quote_data['last_price']
        live_prices = self.calculate_live_prices(code, price)
        if len(live_prices) <= self.rsi_period:
            return None

        rsi = self._rsi(live_prices, self.rsi_period)
        prev_rsi = self.last_rsi.get(code)
        if rsi is None:
            return None
        if prev_rsi is not None and abs(rsi - prev_rsi) < 0.2:
            return None

        self.last_rsi[code] = rsi
        action = None
        qty = 0
        reason = None

        if prev_rsi is not None and prev_rsi <= self.oversold and rsi > self.oversold:
            if self.can_send_buy(code, position_qty, self.order_qty):
                self.add_pending_buy(code, self.order_qty)
                action = 'BUY'
                qty = self.order_qty
                reason = 'RSI 超卖反弹买入'
        elif position_qty > 0 and rsi >= self.overbought:
            if self.can_send_sell(code, position_qty, position_qty):
                self.add_pending_sell(code, position_qty)
                action = 'SELL'
                qty = position_qty
                reason = 'RSI 超买止盈卖出'

        return {
            'code': code,
            'price': price,
            'rsi': rsi,
            'action': action,
            'reason': reason,
            'qty': qty,
        }


class BollingerReversionSignal(BaseDailyIndicatorSignal):
    strategy_name = 'bollinger_reversion'

    def __init__(
        self,
        codes=DEFAULT_CODES,
        order_qty=DEFAULT_ORDER_QTY,
        bollinger_period=20,
        stddev_multiplier=2.0,
    ):
        super().__init__(codes=codes, order_qty=order_qty)
        self.bollinger_period = bollinger_period
        self.stddev_multiplier = stddev_multiplier
        self.last_middle = {code: None for code in self.codes}
        self.last_upper = {code: None for code in self.codes}
        self.last_lower = {code: None for code in self.codes}

    def min_history_bars(self):
        return self.bollinger_period + 2

    def _bands(self, prices):
        if len(prices) < self.bollinger_period:
            return None, None, None
        window = prices[-self.bollinger_period:]
        middle = self._mean(window)
        stddev = self._stddev(window)
        upper = middle + self.stddev_multiplier * stddev
        lower = middle - self.stddev_multiplier * stddev
        return middle, upper, lower

    def startup_lines(self):
        return super().startup_lines() + [
            f"布林周期: {self.bollinger_period}",
            f"标准差倍数: {self.stddev_multiplier}",
        ]

    def refresh_reference_ma(self, code):
        middle, upper, lower = self._bands(self.prices[code])
        self.last_middle[code] = middle
        self.last_upper[code] = upper
        self.last_lower[code] = lower
        return middle, lower

    def format_history_init_log(self, code, bar_count):
        middle = self.last_middle.get(code)
        lower = self.last_lower.get(code)
        upper = self.last_upper.get(code)
        if middle is None:
            return f"  {code}: 获取到 {bar_count} 条K线"
        return (
            f"  {code}: 获取到 {bar_count} 条K线 | Boll({self.bollinger_period}) "
            f"中轨: {middle:.2f} 下轨: {lower:.2f} 上轨: {upper:.2f}"
        )

    def format_quote_log(self, result):
        return "[BOLL] %s 实时价: %.2f | 中轨: %.2f | 下轨: %.2f | 上轨: %.2f" % (
            result['code'],
            result['price'],
            result['middle'],
            result['lower'],
            result['upper'],
        )

    def initial_state_lines(self):
        lines = [f"当前布林状态: Boll({self.bollinger_period})"]
        for code in self.codes:
            middle = self.last_middle.get(code)
            lower = self.last_lower.get(code)
            upper = self.last_upper.get(code)
            if middle is None:
                lines.append(f"  {code}: 样本不足")
            else:
                lines.append(f"  {code}: 中轨={middle:.2f}, 下轨={lower:.2f}, 上轨={upper:.2f}")
        return lines

    def evaluate_quote(self, quote_data, position_qty=0):
        code = quote_data['code']
        price = quote_data['last_price']
        live_prices = self.calculate_live_prices(code, price)
        if len(live_prices) < self.bollinger_period:
            return None

        middle, upper, lower = self._bands(live_prices)
        prev_middle = self.last_middle.get(code)
        prev_lower = self.last_lower.get(code)
        if middle is None:
            return None
        if prev_middle is not None and abs(middle - prev_middle) < 0.01 and abs(lower - (prev_lower or lower)) < 0.01:
            return None

        prev_close = self.prices[code][-2] if len(self.prices[code]) >= 2 else self.prices[code][-1]
        prev_live_middle, _, prev_live_lower = self._bands(self.prices[code][:-1] if len(self.prices[code]) > 1 else live_prices)
        self.last_middle[code] = middle
        self.last_upper[code] = upper
        self.last_lower[code] = lower

        action = None
        qty = 0
        reason = None

        if prev_live_lower is not None and prev_close <= prev_live_lower and price > lower:
            if self.can_send_buy(code, position_qty, self.order_qty):
                self.add_pending_buy(code, self.order_qty)
                action = 'BUY'
                qty = self.order_qty
                reason = '布林下轨反转买入'
        elif position_qty > 0 and price >= middle:
            if self.can_send_sell(code, position_qty, position_qty):
                self.add_pending_sell(code, position_qty)
                action = 'SELL'
                qty = position_qty
                reason = '回归布林中轨卖出'

        return {
            'code': code,
            'price': price,
            'middle': middle,
            'upper': upper,
            'lower': lower,
            'action': action,
            'reason': reason,
            'qty': qty,
        }


class MacdTrendSignal(BaseDailyIndicatorSignal):
    strategy_name = 'macd_trend'

    def __init__(
        self,
        codes=DEFAULT_CODES,
        order_qty=DEFAULT_ORDER_QTY,
        macd_fast=12,
        macd_slow=26,
        macd_signal=9,
    ):
        super().__init__(codes=codes, order_qty=order_qty)
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal_period = macd_signal
        self.last_macd = {code: None for code in self.codes}
        self.last_signal = {code: None for code in self.codes}

    def min_history_bars(self):
        return self.macd_slow + self.macd_signal_period

    def _macd(self, prices):
        if len(prices) < self.min_history_bars():
            return None, None, None
        fast_ema = self._ema_series(prices, self.macd_fast)
        slow_ema = self._ema_series(prices, self.macd_slow)
        macd_line = [fast - slow for fast, slow in zip(fast_ema, slow_ema)]
        signal_line = self._ema_series(macd_line, self.macd_signal_period)
        histogram = macd_line[-1] - signal_line[-1]
        return macd_line[-1], signal_line[-1], histogram

    def startup_lines(self):
        return super().startup_lines() + [
            f"MACD 快线: {self.macd_fast}",
            f"MACD 慢线: {self.macd_slow}",
            f"信号线: {self.macd_signal_period}",
        ]

    def refresh_reference_ma(self, code):
        macd_line, signal_line, _ = self._macd(self.prices[code])
        self.last_macd[code] = macd_line
        self.last_signal[code] = signal_line
        return macd_line, signal_line

    def format_history_init_log(self, code, bar_count):
        macd_line = self.last_macd.get(code)
        signal_line = self.last_signal.get(code)
        if macd_line is None or signal_line is None:
            return f"  {code}: 获取到 {bar_count} 条K线"
        return f"  {code}: 获取到 {bar_count} 条K线 | MACD: {macd_line:.4f} | Signal: {signal_line:.4f}"

    def format_quote_log(self, result):
        return "[MACD] %s 实时价: %.2f | MACD: %.4f | Signal: %.4f | Hist: %.4f" % (
            result['code'],
            result['price'],
            result['macd'],
            result['signal_line'],
            result['histogram'],
        )

    def initial_state_lines(self):
        lines = ["当前 MACD 状态"]
        for code in self.codes:
            macd_line = self.last_macd.get(code)
            signal_line = self.last_signal.get(code)
            if macd_line is None or signal_line is None:
                lines.append(f"  {code}: 样本不足")
            else:
                lines.append(f"  {code}: MACD={macd_line:.4f}, Signal={signal_line:.4f}")
        return lines

    def evaluate_quote(self, quote_data, position_qty=0):
        code = quote_data['code']
        price = quote_data['last_price']
        live_prices = self.calculate_live_prices(code, price)
        macd_line, signal_line, histogram = self._macd(live_prices)
        prev_macd = self.last_macd.get(code)
        prev_signal = self.last_signal.get(code)
        if macd_line is None or signal_line is None:
            return None
        if prev_macd is not None and abs(macd_line - prev_macd) < 0.0005 and abs(signal_line - (prev_signal or signal_line)) < 0.0005:
            return None

        self.last_macd[code] = macd_line
        self.last_signal[code] = signal_line

        action = None
        qty = 0
        reason = None
        if prev_macd is not None and prev_signal is not None and prev_macd <= prev_signal and macd_line > signal_line:
            if self.can_send_buy(code, position_qty, self.order_qty):
                self.add_pending_buy(code, self.order_qty)
                action = 'BUY'
                qty = self.order_qty
                reason = 'MACD 金叉买入'
        elif position_qty > 0 and prev_macd is not None and prev_signal is not None and prev_macd >= prev_signal and macd_line < signal_line:
            if self.can_send_sell(code, position_qty, position_qty):
                self.add_pending_sell(code, position_qty)
                action = 'SELL'
                qty = position_qty
                reason = 'MACD 死叉卖出'

        return {
            'code': code,
            'price': price,
            'macd': macd_line,
            'signal_line': signal_line,
            'histogram': histogram,
            'action': action,
            'reason': reason,
            'qty': qty,
        }


class DonchianBreakoutSignal(BaseDailyIndicatorSignal):
    strategy_name = 'donchian_breakout'

    def __init__(
        self,
        codes=DEFAULT_CODES,
        order_qty=DEFAULT_ORDER_QTY,
        donchian_entry=20,
        donchian_exit=10,
    ):
        super().__init__(codes=codes, order_qty=order_qty)
        self.donchian_entry = donchian_entry
        self.donchian_exit = donchian_exit
        self.last_entry_high = {code: None for code in self.codes}
        self.last_exit_low = {code: None for code in self.codes}

    def min_history_bars(self):
        return max(self.donchian_entry, self.donchian_exit) + 1

    def startup_lines(self):
        return super().startup_lines() + [
            f"突破周期: {self.donchian_entry}",
            f"退出周期: {self.donchian_exit}",
        ]

    def _channels(self, prices):
        if len(prices) < self.min_history_bars():
            return None, None
        previous = prices[:-1]
        if len(previous) < max(self.donchian_entry, self.donchian_exit):
            return None, None
        entry_high = max(previous[-self.donchian_entry:])
        exit_low = min(previous[-self.donchian_exit:])
        return entry_high, exit_low

    def refresh_reference_ma(self, code):
        entry_high, exit_low = self._channels(self.prices[code])
        self.last_entry_high[code] = entry_high
        self.last_exit_low[code] = exit_low
        return entry_high, exit_low

    def format_history_init_log(self, code, bar_count):
        entry_high = self.last_entry_high.get(code)
        exit_low = self.last_exit_low.get(code)
        if entry_high is None:
            return f"  {code}: 获取到 {bar_count} 条K线"
        return f"  {code}: 获取到 {bar_count} 条K线 | 突破价: {entry_high:.2f} | 退出价: {exit_low:.2f}"

    def format_quote_log(self, result):
        return "[DONCHIAN] %s 实时价: %.2f | 突破价: %.2f | 退出价: %.2f" % (
            result['code'],
            result['price'],
            result['entry_high'],
            result['exit_low'],
        )

    def initial_state_lines(self):
        lines = [f"当前唐奇安状态: entry={self.donchian_entry}, exit={self.donchian_exit}"]
        for code in self.codes:
            entry_high = self.last_entry_high.get(code)
            exit_low = self.last_exit_low.get(code)
            if entry_high is None:
                lines.append(f"  {code}: 样本不足")
            else:
                lines.append(f"  {code}: 突破价={entry_high:.2f}, 退出价={exit_low:.2f}")
        return lines

    def evaluate_quote(self, quote_data, position_qty=0):
        code = quote_data['code']
        price = quote_data['last_price']
        live_prices = self.calculate_live_prices(code, price)
        entry_high, exit_low = self._channels(live_prices)
        prev_entry = self.last_entry_high.get(code)
        prev_exit = self.last_exit_low.get(code)
        if entry_high is None or exit_low is None:
            return None
        if prev_entry is not None and abs(entry_high - prev_entry) < 0.01 and abs(exit_low - (prev_exit or exit_low)) < 0.01:
            return None

        self.last_entry_high[code] = entry_high
        self.last_exit_low[code] = exit_low

        action = None
        qty = 0
        reason = None
        if price > entry_high:
            if self.can_send_buy(code, position_qty, self.order_qty):
                self.add_pending_buy(code, self.order_qty)
                action = 'BUY'
                qty = self.order_qty
                reason = '唐奇安通道突破买入'
        elif position_qty > 0 and price < exit_low:
            if self.can_send_sell(code, position_qty, position_qty):
                self.add_pending_sell(code, position_qty)
                action = 'SELL'
                qty = position_qty
                reason = '唐奇安通道跌破卖出'

        return {
            'code': code,
            'price': price,
            'entry_high': entry_high,
            'exit_low': exit_low,
            'action': action,
            'reason': reason,
            'qty': qty,
        }
