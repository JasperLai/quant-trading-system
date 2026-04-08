#!/usr/bin/env python3
"""
持仓监控模块。

负责：
1. 维护已确认成交的持仓状态
2. 在行情更新时检查止损/止盈
3. 触发卖出时通过 agent 对接层发送 SELL 信号
"""

from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from backend.integrations.agent.signal_sender import send_agent_message

LOG_DIR = Path(__file__).resolve().parents[1] / 'logs'
LOG_FILE = LOG_DIR / 'monitor.log'


class PositionMonitor:
    def __init__(self):
        self.positions: Dict[str, Dict] = {}
        self.sold_today: Dict[str, int] = {}

    def add_position(
        self,
        code: str,
        qty: int,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        stop_loss_pct: float = -0.03,
        take_profit_pct: float = 0.05,
        reason: str = "",
    ):
        """登记已成交持仓；如果已有仓位则按加权均价合并。"""
        existing = self.positions.get(code)
        if existing is None:
            total_qty = qty
            avg_entry = entry_price
            entry_time = datetime.now().isoformat()
        else:
            total_qty = existing['qty'] + qty
            avg_entry = round(
                (existing['entry'] * existing['qty'] + entry_price * qty) / total_qty,
                4,
            )
            stop_loss = round(avg_entry * (1 + stop_loss_pct), 2)
            take_profit = round(avg_entry * (1 + take_profit_pct), 2)
            entry_time = existing.get('entry_time', datetime.now().isoformat())

        self.positions[code] = {
            'qty': total_qty,
            'entry': avg_entry,
            'stop': stop_loss,
            'profit': take_profit,
            'stop_pct': stop_loss_pct,
            'profit_pct': take_profit_pct,
            'reason': reason,
            'entry_time': entry_time,
        }

        self._log(
            f"➕ 添加持仓监控: {code} 新增数量:{qty} "
            f"持仓总数:{total_qty} 均价:{avg_entry} "
            f"止损:{stop_loss}({stop_loss_pct:.1%}) 止盈:{take_profit}({take_profit_pct:.1%})"
        )
        send_agent_message(
            f"📋 【持仓记录】\n"
            f"股票: {code}\n"
            f"新增数量: {qty}股\n"
            f"持仓总数: {total_qty}股\n"
            f"持仓均价: {avg_entry}\n"
            f"止损: {stop_loss} ({stop_loss_pct:.1%})\n"
            f"止盈: {take_profit} ({take_profit_pct:.1%})\n"
            f"原因: {reason}",
            log_prefix='持仓通知',
        )

    def remove_position(self, code: str):
        """移除持仓监控（手动平仓时调用）。"""
        if code in self.positions:
            self.positions.pop(code)
            self._log(f"➖ 移除持仓监控: {code}")
            send_agent_message(f"📤 【持仓移除】{code} 已平仓", log_prefix='持仓通知')

    def on_tick(self, code: str, current_price: float) -> Optional[str]:
        """检查当前价格是否触发止损/止盈。"""
        if code not in self.positions:
            return None

        pos = self.positions[code]
        qty = pos['qty']

        if current_price <= pos['stop']:
            self._emit_sell(code, 'STOP_LOSS', current_price, qty, pos)
            self.positions.pop(code)
            return 'STOP_LOSS'

        if current_price >= pos['profit']:
            self._emit_sell(code, 'TAKE_PROFIT', current_price, qty, pos)
            self.positions.pop(code)
            return 'TAKE_PROFIT'

        return None

    def on_bar(self, code: str, close_price: float) -> Optional[str]:
        """K 线收盘时检查；当前实现直接复用 tick 逻辑。"""
        return self.on_tick(code, close_price)

    def get_position_info(self, code: str) -> Optional[Dict]:
        return self.positions.get(code)

    def get_all_positions(self) -> Dict[str, Dict]:
        return self.positions.copy()

    def get_position_count(self) -> int:
        return len(self.positions)

    def can_buy(self, code: str, max_position_per_stock: int = 5000) -> bool:
        if code in self.positions:
            return self.positions[code]['qty'] < max_position_per_stock
        return True

    def _emit_sell(self, code: str, reason: str, price: float, qty: int, pos: Dict):
        reason_cn = '止损' if reason == 'STOP_LOSS' else '止盈'
        profit = (price - pos['entry']) * qty
        profit_pct = (price - pos['entry']) / pos['entry']
        self._log(f"🚨 触发{reason_cn}: {code} @ {price} qty:{qty} 浮盈:{profit:.2f}({profit_pct:.2%})")
        send_agent_message(
            f"【卖出信号】\n"
            f"股票: {code}\n"
            f"动作: SELL\n"
            f"价格: {price}\n"
            f"数量: {qty}\n"
            f"触发原因: {reason_cn}\n"
            f"浮盈: {profit:.2f} ({profit_pct:.2%})",
            log_prefix='卖出信号',
        )

    def _log(self, message: str):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_line = f"[{timestamp}] {message}\n"
        print(log_line.strip(), flush=True)
        with LOG_FILE.open('a') as file:
            file.write(log_line)
