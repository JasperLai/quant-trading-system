#!/usr/bin/env python3
"""
均线策略基类。

负责：
1. OpenD 连接和订阅管理
2. 日线初始化
3. QUOTE 回调和实时均线计算
4. 买入确认后的持仓登记
"""

import os
import time
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from futu import *

import position_monitor
import signal_sender

SHORT_MA = 5
LONG_MA = 20
CODES = ['HK.03690', 'HK.09896', 'SZ.000001']
STOP_LOSS_PCT = -0.03
TAKE_PROFIT_PCT = 0.05
DEFAULT_ORDER_QTY = 100


class QuoteHandler(StockQuoteHandlerBase):
    """实时报价回调"""

    def __init__(self, strategy):
        self.strategy = strategy

    def on_recv_rsp(self, rsp_pb):
        ret_code, data = super().on_recv_rsp(rsp_pb)
        if ret_code != RET_OK:
            print("QuoteHandler error: %s" % data)
            return RET_ERROR, data
        for quote in data.to_dict('records'):
            print(
                f"[QUOTE回调] {quote['code']} "
                f"{quote.get('data_date', '')} {quote.get('data_time', '')} "
                f"last={quote['last_price']} volume={quote.get('volume', 'N/A')}",
                flush=True,
            )
            self.strategy.on_quote(quote)
        return RET_OK, data


class BaseMaCrossStrategy:
    strategy_name = 'base_ma_cross'

    def __init__(
        self,
        codes=CODES,
        short_ma=SHORT_MA,
        long_ma=LONG_MA,
        order_qty=DEFAULT_ORDER_QTY,
        host='127.0.0.1',
        port=11111,
    ):
        self.codes = codes
        self.short_ma_period = short_ma
        self.long_ma_period = long_ma
        self.order_qty = order_qty
        self.host = host
        self.port = port

        self.prices = {code: [] for code in codes}
        self.bar_time_keys = {code: [] for code in codes}
        self.last_short_ma = {code: 0 for code in codes}
        self.last_long_ma = {code: 0 for code in codes}

        self.quote_ctx = OpenQuoteContext(host=host, port=port)
        self.monitor = position_monitor.PositionMonitor()
        self.quote_handler = QuoteHandler(self)

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

    def on_bar(self, bar_data):
        code = bar_data['code']
        close_price = bar_data['close']
        time_key = bar_data.get('time_key')

        if not self.bar_time_keys[code] or self.bar_time_keys[code][-1] != time_key:
            self.bar_time_keys[code].append(time_key)
            self.prices[code].append(close_price)
        else:
            self.prices[code][-1] = close_price

        if len(self.prices[code]) > self.long_ma_period + 10:
            self.prices[code] = self.prices[code][-(self.long_ma_period + 10):]
            self.bar_time_keys[code] = self.bar_time_keys[code][-(self.long_ma_period + 10):]

        print(f"[K线] {code} 时间: {time_key} 收盘价: {close_price:.2f} | 数据量: {len(self.prices[code])}")

    def get_pending_qty(self, code):
        raise NotImplementedError

    def add_pending_buy(self, code, qty):
        raise NotImplementedError

    def clear_pending_buy(self, code, qty=None):
        raise NotImplementedError

    def can_send_buy(self, code, pos_info, qty):
        raise NotImplementedError

    def on_buy_signal(self, code, price, qty):
        print(f"🟢 金叉信号！买入 {code} @ {price}")
        signal_sender.send_signal(code, 'BUY', price, qty, '均线金叉买入')
        self.add_pending_buy(code, qty)
        print(f"🟡 买入待确认: {code}，等待 agent 成交后登记持仓", flush=True)

    def on_quote(self, quote_data):
        code = quote_data['code']
        price = quote_data['last_price']
        pos_info = self.monitor.get_position_info(code)

        if len(self.prices[code]) < self.long_ma_period:
            return

        short_ma, long_ma = self.calculate_live_ma(code, price)
        if short_ma is None or long_ma is None:
            return

        if abs(short_ma - self.last_short_ma[code]) < 0.01 and abs(long_ma - self.last_long_ma[code]) < 0.01:
            return

        prev_short_ma = self.last_short_ma[code]
        prev_long_ma = self.last_long_ma[code]
        self.last_short_ma[code] = short_ma
        self.last_long_ma[code] = long_ma

        print(
            f"[报价] {code} 实时价: {price:.2f} | "
            f"短期MA({self.short_ma_period}): {short_ma:.2f} | "
            f"长期MA({self.long_ma_period}): {long_ma:.2f}"
        )

        if prev_short_ma <= prev_long_ma and short_ma > long_ma:
            qty = self.order_qty
            if self.can_send_buy(code, pos_info, qty):
                self.on_buy_signal(code, price, qty)

        self.monitor.on_tick(code, price)

    def confirm_position(
        self,
        code,
        qty,
        entry_price,
        stop_loss=None,
        take_profit=None,
        reason='均线金叉买入',
    ):
        stop_loss = stop_loss if stop_loss is not None else round(entry_price * (1 + STOP_LOSS_PCT), 2)
        take_profit = take_profit if take_profit is not None else round(entry_price * (1 + TAKE_PROFIT_PCT), 2)
        self.clear_pending_buy(code, qty)
        self.monitor.add_position(
            code=code,
            qty=qty,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            stop_loss_pct=STOP_LOSS_PCT,
            take_profit_pct=TAKE_PROFIT_PCT,
            reason=reason,
        )

    def start(self):
        print("=" * 50, flush=True)
        print(f"启动策略: {self.strategy_name}", flush=True)
        print(f"代码: {', '.join(self.codes)}", flush=True)
        print(f"短期均线周期: {self.short_ma_period}", flush=True)
        print(f"长期均线周期: {self.long_ma_period}", flush=True)
        print(f"单次下单数量: {self.order_qty}", flush=True)
        print(f"止损比例: {STOP_LOSS_PCT:.1%}", flush=True)
        print(f"止盈比例: {TAKE_PROFIT_PCT:.1%}", flush=True)
        print("=" * 50, flush=True)

        ret = self.quote_ctx.set_handler(self.quote_handler)
        if ret != RET_OK:
            print("报价回调处理器设置失败", flush=True)
            return

        print("正在订阅日K线...", flush=True)
        ret, data = self.quote_ctx.subscribe(self.codes, [SubType.K_DAY], subscribe_push=False)
        if ret != RET_OK:
            print(f"日K订阅失败: {data}", flush=True)
            return
        print("日K订阅成功", flush=True)

        print("正在订阅实时报价...", flush=True)
        ret, data = self.quote_ctx.subscribe(self.codes, [SubType.QUOTE])
        if ret != RET_OK:
            print(f"报价订阅失败: {data}", flush=True)
            return
        print(f"订阅成功: {', '.join(self.codes)}", flush=True)

        print("初始化历史K线数据...", flush=True)
        for code in self.codes:
            ret, data = self.quote_ctx.get_cur_kline(code, self.long_ma_period + 5, KLType.K_DAY)
            if ret == RET_OK:
                for bar in data.to_dict('records'):
                    self.on_bar(bar)
                short_ma = self.calculate_ma(self.prices[code], self.short_ma_period)
                long_ma = self.calculate_ma(self.prices[code], self.long_ma_period)
                self.last_short_ma[code] = short_ma if short_ma else 0
                self.last_long_ma[code] = long_ma if long_ma else 0
                print(
                    f"  {code}: 获取到 {len(data)} 条K线 | "
                    f"短期MA({self.short_ma_period}): {short_ma:.2f} | "
                    f"长期MA({self.long_ma_period}): {long_ma:.2f}",
                    flush=True,
                )
            else:
                print(f"  {code}: 获取失败 {data}", flush=True)

        print("\n=== 策略初始化完成，等待实时报价... ===", flush=True)
        print(
            f"当前均线状态: 短期MA({self.short_ma_period}) vs 长期MA({self.long_ma_period})",
            flush=True,
        )
        for code in self.codes:
            print(
                f"  {code}: "
                f"短期MA({self.short_ma_period})={self.last_short_ma[code]:.2f}, "
                f"长期MA({self.long_ma_period})={self.last_long_ma[code]:.2f}",
                flush=True,
            )
        print("按 Ctrl+C 停止", flush=True)

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n停止策略...", flush=True)
            self.stop()

    def stop(self):
        self.quote_ctx.stop()
        self.quote_ctx.close()
        print("策略已停止")
