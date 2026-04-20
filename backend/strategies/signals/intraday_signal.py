#!/usr/bin/env python3
"""日内策略纯信号层。"""

from datetime import datetime

DEFAULT_CODES = ['HK.03690']
DEFAULT_ORDER_QTY = 100
DEFAULT_BREAKOUT_PCT = 0.004
DEFAULT_PULLBACK_PCT = 0.003
DEFAULT_STOP_LOSS_PCT = 0.004
DEFAULT_ENTRY_START_TIME = '09:45:00'
DEFAULT_FLAT_TIME = '15:45:00'
DEFAULT_MIN_HOLD_MINUTES = 3
DEFAULT_MAX_TRADES_PER_DAY = 3
DEFAULT_REENTRY_COOLDOWN_MINUTES = 5


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
        stop_loss_pct=DEFAULT_STOP_LOSS_PCT,
        entry_start_time=DEFAULT_ENTRY_START_TIME,
        flat_time=DEFAULT_FLAT_TIME,
        min_hold_minutes=DEFAULT_MIN_HOLD_MINUTES,
        max_trades_per_day=DEFAULT_MAX_TRADES_PER_DAY,
        reentry_cooldown_minutes=DEFAULT_REENTRY_COOLDOWN_MINUTES,
    ):
        self.codes = list(codes)
        self.order_qty = order_qty
        self.breakout_pct = breakout_pct
        self.pullback_pct = pullback_pct
        self.stop_loss_pct = stop_loss_pct
        self.entry_start_time = entry_start_time
        self.flat_time = flat_time
        self.min_hold_minutes = min_hold_minutes
        self.max_trades_per_day = max_trades_per_day
        self.reentry_cooldown_minutes = reentry_cooldown_minutes

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
        self.trades_today = {code: 0 for code in self.codes}
        self.last_entry_time = {code: None for code in self.codes}
        self.last_exit_time = {code: None for code in self.codes}
        self.entry_price_hint = {code: None for code in self.codes}
        self.high_since_entry = {code: None for code in self.codes}
        self.last_position_qty = {code: 0 for code in self.codes}

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

    def _parse_trade_dt(self, trade_date, trade_time):
        if not trade_date or not trade_time:
            return None
        try:
            return datetime.strptime(f'{trade_date} {trade_time}', '%Y-%m-%d %H:%M:%S')
        except ValueError:
            return None

    def _reset_session(self, code, trade_date, open_price, reference_price, last_price):
        session_open = open_price if open_price is not None else last_price
        reference = reference_price if reference_price is not None else session_open
        self.session_date[code] = trade_date
        self.session_open[code] = session_open
        self.reference_price[code] = reference
        self.session_high[code] = last_price
        self.trades_today[code] = 0
        self.last_entry_time[code] = None
        self.last_exit_time[code] = None
        self.entry_price_hint[code] = None
        self.high_since_entry[code] = None
        self.last_position_qty[code] = 0

    @staticmethod
    def _parse_iso_dt(value):
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None

    def _sync_session_state(self, quote_data):
        code = quote_data['code']
        last_price = self._to_float(quote_data.get('last_price')) or 0.0
        high_price = self._to_float(quote_data.get('high_price')) or last_price
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
            self._reset_session(code, trade_date, open_price, reference_price, high_price)
        else:
            if self.session_open.get(code) is None and open_price is not None:
                self.session_open[code] = open_price
            if self.reference_price.get(code) is None:
                self.reference_price[code] = reference_price
            self.session_high[code] = max(self.session_high.get(code) or high_price, high_price)

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
            f"止损阈值: {self.stop_loss_pct * 100:.2f}%",
            f"入场开始时间: {self.entry_start_time}",
            f"日内平仓时间: {self.flat_time}",
            f"最短持有分钟: {self.min_hold_minutes}",
            f"单日最多交易次数: {self.max_trades_per_day}",
            f"再次入场冷却分钟: {self.reentry_cooldown_minutes}",
            f"单次下单数量: {self.order_qty}",
        ]

    def to_config(self):
        return {
            'codes': list(self.codes),
            'order_qty': self.order_qty,
            'breakout_pct': self.breakout_pct,
            'pullback_pct': self.pullback_pct,
            'stop_loss_pct': self.stop_loss_pct,
            'entry_start_time': self.entry_start_time,
            'flat_time': self.flat_time,
            'min_hold_minutes': self.min_hold_minutes,
            'max_trades_per_day': self.max_trades_per_day,
            'reentry_cooldown_minutes': self.reentry_cooldown_minutes,
        }

    def format_quote_log(self, result):
        return "[日内报价] %s 实时价: %.2f | 参考价: %.2f | 日内高点: %.2f | 当日已交易: %s | 时间: %s" % (
            result['code'],
            result['price'],
            result['reference_price'],
            result['session_high'],
            result['trades_today'],
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
        return (
            position_qty == 0
            and code not in self.pending_buys
            and self.trades_today.get(code, 0) < self.max_trades_per_day
        )

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

    def _sync_confirmed_position_state(self, code, position_qty, position_info, trade_dt, price, bar_high_price):
        prev_qty = self.last_position_qty.get(code, 0)
        current_high = bar_high_price if bar_high_price is not None else price

        if position_qty > 0:
            entry_price = self._to_float((position_info or {}).get('entry')) or self.entry_price_hint.get(code) or price
            entry_time = self._parse_iso_dt((position_info or {}).get('entry_time')) or self.last_entry_time.get(code) or trade_dt

            if prev_qty <= 0:
                self.trades_today[code] += 1
                self.last_entry_time[code] = entry_time
                self.entry_price_hint[code] = entry_price
                self.high_since_entry[code] = max(entry_price, current_high)
            else:
                self.last_entry_time[code] = entry_time
                self.entry_price_hint[code] = entry_price
                self.high_since_entry[code] = max(self.high_since_entry.get(code) or entry_price or current_high, current_high)
        else:
            if prev_qty > 0:
                self.last_exit_time[code] = trade_dt
            self.entry_price_hint[code] = None
            self.high_since_entry[code] = None

        self.last_position_qty[code] = position_qty

    def evaluate_quote(self, quote_data, position_qty=0, position_info=None):
        code = quote_data['code']
        session = self._sync_session_state(quote_data)
        price = session['last_price']
        trade_date = session['trade_date']
        trade_time = session['trade_time']
        trade_dt = self._parse_trade_dt(trade_date, trade_time)
        bar_high_price = self._to_float(quote_data.get('bar_high_price'))
        reference_price = session['reference_price'] or price
        session_high = max(session['session_high'] or price, price)
        self.session_high[code] = session_high
        self._sync_confirmed_position_state(code, position_qty, position_info, trade_dt, price, bar_high_price)

        action = None
        signal_qty = 0
        reason = None

        if position_qty > 0:
            entry_price = self.entry_price_hint[code]
            peak_since_entry = self.high_since_entry[code]
            hold_minutes = 0
            if trade_dt is not None and self.last_entry_time.get(code) is not None:
                hold_minutes = max(int((trade_dt - self.last_entry_time[code]).total_seconds() // 60), 0)
            trailing_activation_pct = max(self.breakout_pct, self.pullback_pct * 1.5)
            signal_qty = position_qty
            if trade_time >= self.flat_time:
                if self.can_send_sell(code, position_qty, signal_qty):
                    self.add_pending_sell(code, signal_qty)
                    action = 'SELL'
                    reason = '日内收盘前平仓'
            elif price <= entry_price * (1 - self.stop_loss_pct):
                if self.can_send_sell(code, position_qty, signal_qty):
                    self.add_pending_sell(code, signal_qty)
                    action = 'SELL'
                    reason = '日内止损卖出'
            elif (
                hold_minutes >= self.min_hold_minutes
                and peak_since_entry >= entry_price * (1 + trailing_activation_pct)
                and price <= peak_since_entry * (1 - self.pullback_pct)
            ):
                if self.can_send_sell(code, position_qty, signal_qty):
                    self.add_pending_sell(code, signal_qty)
                    action = 'SELL'
                    reason = '日内冲高回落卖出'
        else:
            cooldown_ready = True
            if trade_dt is not None and self.last_exit_time.get(code) is not None:
                cooldown_ready = (trade_dt - self.last_exit_time[code]).total_seconds() >= self.reentry_cooldown_minutes * 60
            breakout_price = reference_price * (1 + self.breakout_pct)
            if (
                trade_time >= self.entry_start_time
                and trade_time < self.flat_time
                and cooldown_ready
                and price >= breakout_price
                and self.can_send_buy(code, position_qty, self.order_qty)
            ):
                self.add_pending_buy(code, self.order_qty)
                action = 'BUY'
                signal_qty = self.order_qty
                reason = '日内突破买入'

        return {
            'code': code,
            'price': price,
            'reference_price': reference_price,
            'session_high': session_high,
            'trade_time': trade_time,
            'trades_today': self.trades_today.get(code, 0),
            'action': action,
            'reason': reason,
            'qty': signal_qty if action is not None else 0,
        }
