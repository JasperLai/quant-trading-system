#!/usr/bin/env python3
"""
单仓版均线交叉策略。

同一标的同一时间只允许一笔正式持仓，
买入成交前只保留一个 pending BUY。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from futu import RET_OK

from ma_strategy_base import BaseMaCrossStrategy


class MaCrossStrategy(BaseMaCrossStrategy):
    strategy_name = 'single_position_ma_cross'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pending_buys = set()

    def get_pending_qty(self, code):
        return self.order_qty if code in self.pending_buys else 0

    def add_pending_buy(self, code, qty):
        self.pending_buys.add(code)

    def clear_pending_buy(self, code, qty=None):
        self.pending_buys.discard(code)

    def can_send_buy(self, code, pos_info, qty):
        return pos_info is None and code not in self.pending_buys


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
