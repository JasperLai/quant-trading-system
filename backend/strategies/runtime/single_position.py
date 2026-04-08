#!/usr/bin/env python3
"""单仓版实时均线策略。"""

from futu import RET_OK

from backend.strategies.runtime.realtime_runner import RealtimeMaStrategyRunner
from backend.strategies.signals.ma_signal import SinglePositionMaSignal


class MaCrossStrategy(RealtimeMaStrategyRunner):
    strategy_name = 'single_position_ma_cross'
    signal_class = SinglePositionMaSignal


def main():
    strategy = MaCrossStrategy()
    ret, state = strategy.gateway.get_global_state()
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
