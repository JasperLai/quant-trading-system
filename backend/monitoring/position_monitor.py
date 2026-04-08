#!/usr/bin/env python3
"""
持仓监控模块。

负责：
1. 维护已确认成交的持仓状态
2. 在行情更新时检查止损/止盈
3. 触发卖出时通过 agent 对接层发送 SELL 信号
"""

from datetime import datetime
import threading
from typing import Dict, Optional

from backend.core.config import LOG_DIR, STOP_LOSS_PCT, TAKE_PROFIT_PCT
from backend.core.logging import get_logger
from backend.integrations.agent.signal_sender import send_agent_message

LOG_FILE = LOG_DIR / 'monitor.log'
logger = get_logger(__name__)


class PositionMonitor:
    def __init__(self):
        self.positions: Dict[str, Dict] = {}
        self.sold_today: Dict[str, int] = {}
        self._lock = threading.RLock()

    def add_position(
        self,
        code: str,
        qty: int,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        stop_loss_pct: float = STOP_LOSS_PCT,
        take_profit_pct: float = TAKE_PROFIT_PCT,
        reason: str = "",
    ):
        """登记已成交持仓；如果已有仓位则按加权均价合并。"""
        with self._lock:
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
        existed = False
        with self._lock:
            existed = code in self.positions
            if existed:
                self.positions.pop(code)
        if existed:
            self._log(f"➖ 移除持仓监控: {code}")
            send_agent_message(f"📤 【持仓移除】{code} 已平仓", log_prefix='持仓通知')

    def on_tick(self, code: str, current_price: float) -> Optional[str]:
        """检查当前价格是否触发止损/止盈。"""
        with self._lock:
            pos = self.positions.get(code)
            if pos is None:
                return None
            qty = pos['qty']

            if current_price <= pos['stop']:
                self.positions.pop(code, None)
                trigger = 'STOP_LOSS'
            elif current_price >= pos['profit']:
                self.positions.pop(code, None)
                trigger = 'TAKE_PROFIT'
            else:
                trigger = None

        if trigger is not None:
            self._emit_sell(code, trigger, current_price, qty, pos)
            return trigger

        return None

    def on_bar(self, code: str, close_price: float) -> Optional[str]:
        """K 线收盘时检查；当前实现直接复用 tick 逻辑。"""
        return self.on_tick(code, close_price)

    def get_position_info(self, code: str) -> Optional[Dict]:
        with self._lock:
            pos = self.positions.get(code)
            return dict(pos) if pos is not None else None

    def get_all_positions(self) -> Dict[str, Dict]:
        with self._lock:
            return {code: dict(pos) for code, pos in self.positions.items()}

    def get_position_count(self) -> int:
        with self._lock:
            return len(self.positions)

    def can_buy(self, code: str, max_position_per_stock: int = 5000) -> bool:
        with self._lock:
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
        logger.info(message)
        with LOG_FILE.open('a') as file:
            file.write(log_line)
