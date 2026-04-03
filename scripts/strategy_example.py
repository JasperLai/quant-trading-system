#!/usr/bin/env python3
"""
均线交叉策略示例

策略只负责判断信号，产生 BUY 信号后交给 position_monitor 管理持仓和风控。
止损/止盈触发 SELL 由 position_monitor 负责，策略不介入。

当短期均线从下方穿越长期均线时买入（金叉）
当短期均线从上方穿越长期均线时——策略不做判断，交由 position_monitor 处理
"""

import sys
import os
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from futu import *
import signal_sender
import position_monitor

# 策略参数
SHORT_MA = 5    # 短期均线周期
LONG_MA = 20    # 长期均线周期
CODES = ['HK.03690', 'HK.09896', 'SZ.000001']  # 美团、MNSO、平安银行

# 止损止盈参数
STOP_LOSS_PCT = -0.03   # 止损 3%
TAKE_PROFIT_PCT = 0.05  # 止盈 5%


class MaCrossStrategy:
    def __init__(self, codes=CODES, short_ma=SHORT_MA, long_ma=LONG_MA):
        self.codes = codes
        self.short_ma_period = short_ma
        self.long_ma_period = long_ma

        # 每个股票独立维护价格序列
        self.prices = {code: [] for code in codes}
        self.last_short_ma = {code: 0 for code in codes}
        self.last_long_ma = {code: 0 for code in codes}

        # 连接行情
        self.quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)

        # 持仓监控器（风控 + 持仓维护）
        self.monitor = position_monitor.PositionMonitor()

        # 盘中只依赖实时报价推送
        self.quote_handler = QuoteHandler(self)

    def calculate_ma(self, prices, period):
        """计算简单移动平均"""
        if len(prices) < period:
            return None
        return sum(prices[-period:]) / period

    def calculate_live_ma(self, code, latest_price):
        """用最新报价覆盖最后一根价格，计算盘中实时均线。"""
        history = self.prices[code]
        if len(history) < self.long_ma_period:
            return None, None

        live_prices = history[:-1] + [latest_price]
        short_ma = self.calculate_ma(live_prices, self.short_ma_period)
        long_ma = self.calculate_ma(live_prices, self.long_ma_period)
        return short_ma, long_ma

    def on_bar(self, bar_data):
        """加载历史日线收盘价，用于初始化均线。"""
        code = bar_data['code']
        close_price = bar_data['close']

        # 只添加收盘价到价格序列
        if not self.prices[code] or self.prices[code][-1] != close_price:
            self.prices[code].append(close_price)

        # 保持足够的历史数据
        if len(self.prices[code]) > self.long_ma_period + 10:
            self.prices[code] = self.prices[code][-(self.long_ma_period + 10):]

        print(f"[K线] {code} 收盘价: {close_price:.2f} | 数据量: {len(self.prices[code])}")

    def on_quote(self, quote_data):
        """实时报价回调 - 基于实时价格判断金叉死叉"""
        code = quote_data['code']
        price = quote_data['last_price']

        # 数据不足时不判断
        if len(self.prices[code]) < self.long_ma_period:
            return

        # 用最新报价替换最后一根K线收盘价，得到盘中实时均线
        short_ma, long_ma = self.calculate_live_ma(code, price)
        if short_ma is None or long_ma is None:
            return

        # 避免重复信号
        if abs(short_ma - self.last_short_ma[code]) < 0.01 and abs(long_ma - self.last_long_ma[code]) < 0.01:
            return

        prev_short_ma = self.last_short_ma[code]
        prev_long_ma = self.last_long_ma[code]

        self.last_short_ma[code] = short_ma
        self.last_long_ma[code] = long_ma

        print(f"[报价] {code} 实时价: {price:.2f} | MA5: {short_ma:.2f} | MA20: {long_ma:.2f}")

        # ========== 策略核心：只判断金叉买入 ==========
        # 金叉：短期均线从下方穿越长期均线
        if prev_short_ma <= prev_long_ma and short_ma > long_ma:
            pos_info = self.monitor.get_position_info(code)
            if pos_info is None:
                # 空仓且金叉 → 买入
                qty = 100
                stop_loss = round(price * (1 + STOP_LOSS_PCT), 2)
                take_profit = round(price * (1 + TAKE_PROFIT_PCT), 2)

                print(f"🟢 金叉信号！买入 {code} @ {price}")
                signal_sender.send_signal(code, 'BUY', price, qty, '均线金叉买入')

                # 登记到持仓监控器（负责止损/止盈/风控）
                self.monitor.add_position(
                    code=code,
                    qty=qty,
                    entry_price=price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    stop_loss_pct=STOP_LOSS_PCT,
                    take_profit_pct=TAKE_PROFIT_PCT,
                    reason='均线金叉买入'
                )

        # ========== 死叉时策略不做任何操作 ==========
        # SELL 信号由 position_monitor 根据止损/止盈条件触发
        # 策略不介入，避免双重判断

        # ========== 检查持仓的风控条件 ==========
        self.monitor.on_tick(code, price)

    def start(self):
        """启动策略"""
        print(f"=" * 50, flush=True)
        print(f"启动均线交叉策略", flush=True)
        print(f"代码: {', '.join(self.codes)}", flush=True)
        print(f"短期均线周期: {self.short_ma_period}", flush=True)
        print(f"长期均线周期: {self.long_ma_period}", flush=True)
        print(f"止损比例: {STOP_LOSS_PCT:.1%}", flush=True)
        print(f"止盈比例: {TAKE_PROFIT_PCT:.1%}", flush=True)
        print("=" * 50, flush=True)

        ret = self.quote_ctx.set_handler(self.quote_handler)
        if ret != RET_OK:
            print("报价回调处理器设置失败", flush=True)
            return

        # 先订阅日线，确保 get_cur_kline(K_DAY) 可正常返回初始化数据
        print("正在订阅日K线...", flush=True)
        ret, data = self.quote_ctx.subscribe(self.codes, [SubType.K_DAY], subscribe_push=False)
        if ret != RET_OK:
            print(f"日K订阅失败: {data}", flush=True)
            return
        print("日K订阅成功", flush=True)

        # 盘中策略只依赖实时报价推送
        print("正在订阅实时报价...", flush=True)
        ret, data = self.quote_ctx.subscribe(self.codes, [SubType.QUOTE])
        if ret != RET_OK:
            print(f"报价订阅失败: {data}", flush=True)
            return
        print(f"订阅成功: {', '.join(self.codes)}", flush=True)

        # 初始化：用 get_cur_kline 主动获取历史K线数据
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
                print(f"  {code}: 获取到 {len(data)} 条K线 | MA5: {short_ma:.2f} | MA20: {long_ma:.2f}", flush=True)
            else:
                print(f"  {code}: 获取失败 {data}", flush=True)

        # 初始化均线值
        for code in self.codes:
            short_ma = self.calculate_ma(self.prices[code], self.short_ma_period)
            long_ma = self.calculate_ma(self.prices[code], self.long_ma_period)
            self.last_short_ma[code] = short_ma if short_ma else 0
            self.last_long_ma[code] = long_ma if long_ma else 0

        print("\n=== 策略初始化完成，等待实时报价... ===", flush=True)
        print(f"当前均线状态: MA5 vs MA20", flush=True)
        for code in self.codes:
            print(f"  {code}: MA5={self.last_short_ma[code]:.2f}, MA20={self.last_long_ma[code]:.2f}", flush=True)
        print("按 Ctrl+C 停止", flush=True)

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n停止策略...", flush=True)
            self.stop()

    def stop(self):
        """停止策略"""
        self.quote_ctx.stop()
        self.quote_ctx.close()
        print("策略已停止")


class QuoteHandler(StockQuoteHandlerBase):
    """实时报价回调"""
    def __init__(self, strategy):
        self.strategy = strategy

    def on_recv_rsp(self, rsp_pb):
        """实时报价推送"""
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


def main():
    strategy = MaCrossStrategy()

    # 检查 OpenD 连接
    ret, state = strategy.quote_ctx.get_global_state()
    if ret != RET_OK:
        print(f"无法连接 OpenD: {state}")
        print("请确保 OpenD 已启动并登录")
        return

    print(f"OpenD 连接成功!")
    print(f"服务器版本: {state.get('server_ver', 'N/A')}")
    print(f"行情登录: {'是' if state.get('qot_logined') in (True, '1', 1) else '否'}")

    strategy.start()


if __name__ == '__main__':
    main()
