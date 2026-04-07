#!/usr/bin/env python3
"""
有上限加仓版均线交叉策略。

允许在单标的持仓未达到上限时继续发 BUY，
并把待确认买单数量计入可用仓位判断。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from futu import RET_OK

from ma_strategy_base import BaseMaCrossStrategy


class PyramidingMaCrossStrategy(BaseMaCrossStrategy):
    strategy_name = 'pyramiding_ma_cross'

    def __init__(self, *args, max_position_per_stock=300, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_position_per_stock = max_position_per_stock
        self.pending_buys = {}

    def get_pending_qty(self, code):
        return self.pending_buys.get(code, 0)

    def add_pending_buy(self, code, qty):
        self.pending_buys[code] = self.pending_buys.get(code, 0) + qty

    def clear_pending_buy(self, code, qty=None):
        if code not in self.pending_buys:
            return
        if qty is None or qty >= self.pending_buys[code]:
            self.pending_buys.pop(code, None)
            return
        self.pending_buys[code] -= qty

    def can_send_buy(self, code, pos_info, qty):
        current_qty = pos_info['qty'] if pos_info else 0
        pending_qty = self.get_pending_qty(code)
        return current_qty + pending_qty + qty <= self.max_position_per_stock

    def start(self):
        print(f"单标的最大仓位: {self.max_position_per_stock}", flush=True)
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
