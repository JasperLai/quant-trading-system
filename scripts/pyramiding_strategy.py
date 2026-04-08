#!/usr/bin/env python3
"""
有上限加仓版均线交叉策略。

允许在单标的持仓未达到上限时继续发 BUY，
并把待确认买单数量计入可用仓位判断。
"""

from futu import RET_OK

from ma_signal import PyramidingMaSignal
from realtime_strategy_runner import RealtimeMaStrategyRunner


class PyramidingMaCrossStrategy(RealtimeMaStrategyRunner):
    strategy_name = 'pyramiding_ma_cross'
    signal_class = PyramidingMaSignal

    def start(self):
        print(f"单标的最大仓位: {self.signal.max_position_per_stock}", flush=True)
        super().start()


def main():
    strategy = PyramidingMaCrossStrategy()
    ret, state = strategy.quote_ctx.get_global_state()
    if ret != RET_OK:
        print(f"无法连接 OpenD: {state}")
        print("请确保 OpenD 已启动并登录")
        return

    print("OpenD 连接成功!")
    print(f"服务器版本: {state.get('server_ver', 'N/A')}")
    print(f"行情登录: {'是' if state.get('qot_logined') in (True, '1', 1) else '否'}")
    strategy.start()


if __name__ == '__main__':
    main()
