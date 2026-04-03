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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from futu import *
import signal_sender
import position_monitor

# 策略参数
SHORT_MA = 5    # 短期均线周期
LONG_MA = 20    # 长期均线周期
CODES = ['HK.03690', 'HK.09896']  # 美团、MNSO

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

        # 数据收集阶段
        if len(self.prices[code]) < self.long_ma_period:
            return

        short_ma = self.calculate_ma(self.prices[code], self.short_ma_period)
        long_ma = self.calculate_ma(self.prices[code], self.long_ma_period)

        print(f"[{code}] {bar_data['time_key']} 价格: {price:.2f} | "
              f"MA{self.short_ma_period}: {short_ma:.2f} | "
              f"MA{self.long_ma_period}: {long_ma:.2f}")

        # 避免重复信号
        if abs(short_ma - self.last_short_ma[code]) < 0.01 and abs(long_ma - self.last_long_ma[code]) < 0.01:
            return

        self.last_short_ma[code] = short_ma
        self.last_long_ma[code] = long_ma

        # ========== 策略核心：只判断金叉买入 ==========
        if short_ma > long_ma:
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

        # ========== 每个tick都检查持仓的风控条件 ==========
        self.monitor.on_tick(code, price)

    def start(self):
        """启动策略"""
        print(f"=" * 50)
        print(f"启动均线交叉策略")
        print(f"代码: {', '.join(self.codes)}")
        print(f"短期均线周期: {self.short_ma_period}")
        print(f"长期均线周期: {self.long_ma_period}")
        print(f"止损比例: {STOP_LOSS_PCT:.1%}")
        print(f"止盈比例: {TAKE_PROFIT_PCT:.1%}")
        print("=" * 50)

        # 订阅K线
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
    strategy = MaCrossStrategy()

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
