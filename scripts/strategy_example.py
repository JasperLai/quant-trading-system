#!/usr/bin/env python3
"""
均线交叉策略示例

当短期均线从下方穿越长期均线时买入（金叉）
当短期均线从上方穿越长期均线时卖出（死叉）
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from futu import *
import signal_sender

# 策略参数
SHORT_MA = 5    # 短期均线周期
LONG_MA = 20    # 长期均线周期
CODES = ['HK.03690', 'HK.09896']  # 美团、MNSO
TRADE_QUANTITY = 100  # 每次交易数量


class MaCrossStrategy:
    def __init__(self, codes=CODES, short_ma=SHORT_MA, long_ma=LONG_MA):
        self.codes = codes
        self.short_ma_period = short_ma
        self.long_ma_period = long_ma
        # 每个股票独立维护价格序列和持仓状态
        self.prices = {code: [] for code in codes}
        self.positions = {code: 0 for code in codes}  # 0=空仓, 1=持仓
        self.last_short_ma = {code: 0 for code in codes}
        self.last_long_ma = {code: 0 for code in codes}

        # 连接行情
        self.quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)

    def calculate_ma(self, prices, period):
        """计算简单移动平均"""
        if len(prices) < period:
            return None
        return sum(prices[-period:]) / period

    def on_bar(self, bar_data):
        """K线数据回调"""
        code = bar_data['code']
        price = bar_data['close']
        self.prices[code].append(price)

        if len(self.prices[code]) < self.long_ma_period:
            print(f"[{code}] {bar_data['time_key']} 数据收集中... ({len(self.prices[code])}/{self.long_ma_period})")
            return

        short_ma = self.calculate_ma(self.prices[code], self.short_ma_period)
        long_ma = self.calculate_ma(self.prices[code], self.long_ma_period)

        print(f"[{code}] {bar_data['time_key']} 价格: {price:.2f} | "
              f"MA{self.short_ma_period}: {short_ma:.2f} | "
              f"MA{self.long_ma_period}: {long_ma:.2f} | "
              f"持仓: {'是' if self.positions[code] else '否'}")

        # 避免重复信号：至少等到均线有明显变化
        if abs(short_ma - self.last_short_ma[code]) < 0.01 and abs(long_ma - self.last_long_ma[code]) < 0.01:
            return

        self.last_short_ma[code] = short_ma
        self.last_long_ma[code] = long_ma

        # 金叉买入
        if short_ma > long_ma and self.positions[code] == 0:
            print(f"🟢 金叉信号！买入 {code} @ {price}")
            signal_sender.send_signal(code, 'BUY', price, TRADE_QUANTITY, '均线金叉买入')
            self.positions[code] = 1

        # 死叉卖出
        elif short_ma < long_ma and self.positions[code] == 1:
            print(f"🔴 死叉信号！卖出 {code} @ {price}")
            signal_sender.send_signal(code, 'SELL', price, TRADE_QUANTITY, '均线死叉卖出')
            self.positions[code] = 0

    def start(self):
        """启动策略"""
        print(f"=" * 50)
        print(f"启动均线交叉策略")
        print(f"代码: {', '.join(self.codes)}")
        print(f"短期均线周期: {self.short_ma_period}")
        print(f"长期均线周期: {self.long_ma_period}")
        print(f"=" * 50)

        # 订阅K线（多股票）
        ret, data = self.quote_ctx.subscribe(self.codes, [SubType.KLINE])
        if ret != RET_OK:
            print(f"订阅失败: {data}")
            return

        print(f"订阅成功: {', '.join(self.codes)}")

        # 设置K线回调
        self.quote_ctx.set_handler(KlineTest(self))
        self.quote_ctx.start()

        print("策略已启动，按 Ctrl+C 停止")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n停止策略...")
            self.stop()

    def stop(self):
        """停止策略"""
        self.quote_ctx.stop()
        self.quote_ctx.close()
        print("策略已停止")


class KlineTest(CurKlineHandlerBase):
    def __init__(self, strategy):
        self.strategy = strategy

    def on_recv(self, rsp_pb):
        """K线数据推送回调"""
        ret, data = super().on_recv(rsp_pb)
        if ret == RET_OK:
            for bar in data:
                self.strategy.on_bar(bar)


def main():
    strategy = MaCrossStrategy(codes=CODES)

    # 检查 OpenD 连接
    ret, state = strategy.quote_ctx.get_global_state()
    if ret != RET_OK:
        print(f"无法连接 OpenD: {state}")
        print("请确保 OpenD 已启动并登录")
        return

    print(f"OpenD 连接成功!")
    print(f"服务器版本: {state.get('server_ver', 'N/A')}")
    print(f"行情登录: {'是' if state.get('qot_logined') == '1' else '否'}")

    strategy.start()


if __name__ == '__main__':
    main()
