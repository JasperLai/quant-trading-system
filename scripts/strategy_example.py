#!/usr/bin/env python3
"""
单仓版均线交叉策略。

同一标的同一时间只允许一笔正式持仓，
买入成交前只保留一个 pending BUY。
"""

from futu import RET_OK

from ma_signal import SinglePositionMaSignal
from realtime_strategy_runner import RealtimeMaStrategyRunner


class MaCrossStrategy(RealtimeMaStrategyRunner):
    strategy_name = 'single_position_ma_cross'
    signal_class = SinglePositionMaSignal


def main():
    strategy = MaCrossStrategy()
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
