#!/usr/bin/env python3
"""
持仓监控模块 - 监控止损/止盈价格，触发时发送信号给 OpenClaw

使用方式：
1. 策略执行买入后，调用 monitor.add_position() 添加持仓
2. 策略收到行情推送时，调用 monitor.on_tick() 检查是否触发
3. 触发条件时，自动发送 SELL 信号给 OpenClaw

示例：
    monitor = PositionMonitor()
    monitor.add_position('HK.00700', 100, 400.0, 388.0, 420.0)
    # 在策略的行情回调中：
    monitor.on_tick('HK.00700', current_price)
"""

import subprocess
import json
import os
from datetime import datetime
from typing import Dict, Optional, List

LOG_DIR = os.path.dirname(os.path.abspath(__file__)) + '/logs'
LOG_FILE = os.path.join(LOG_DIR, 'monitor.log')

# 测试模式：设置为 True 时跳过 openclaw 调用
TEST_MODE = True


class PositionMonitor:
    def __init__(self):
        self.positions: Dict[str, Dict] = {}  # {code: position_info}
        self.sold_today: Dict[str, int] = {}  # {code: count} 当日卖出次数
    
    def add_position(self, code: str, qty: int, entry_price: float, 
                     stop_loss: float, take_profit: float,
                     stop_loss_pct: float = -0.03,
                     take_profit_pct: float = 0.05,
                     reason: str = ""):
        """
        添加持仓监控
        
        Args:
            code: 股票代码
            qty: 持仓数量
            entry_price: 买入价格
            stop_loss: 止损价格（绝对值）
            take_profit: 止盈价格（绝对值）
            stop_loss_pct: 止损比例（用于显示）
            take_profit_pct: 止盈比例（用于显示）
            reason: 买入原因（记录用）
        """
        self.positions[code] = {
            'qty': qty,
            'entry': entry_price,
            'stop': stop_loss,
            'profit': take_profit,
            'stop_pct': stop_loss_pct,
            'profit_pct': take_profit_pct,
            'reason': reason,
            'entry_time': datetime.now().isoformat()
        }
        
        # 记录日志
        self._log(f"➕ 添加持仓监控: {code} 数量:{qty} 买入价:{entry_price} 止损:{stop_loss}({stop_loss_pct:.1%}) 止盈:{take_profit}({take_profit_pct:.1%})")
        
        # 通知 OpenClaw
        self._notify_openclaw(
            f"📋 【持仓记录】\n"
            f"股票: {code}\n"
            f"数量: {qty}股\n"
            f"买入价: {entry_price}\n"
            f"止损: {stop_loss} ({stop_loss_pct:.1%})\n"
            f"止盈: {take_profit} ({take_profit_pct:.1%})\n"
            f"原因: {reason}"
        )
    
    def remove_position(self, code: str):
        """移除持仓监控（手动平仓时调用）"""
        if code in self.positions:
            info = self.positions.pop(code)
            self._log(f"➖ 移除持仓监控: {code}")
            self._notify_openclaw(f"📤 【持仓移除】{code} 已平仓")
    
    def on_tick(self, code: str, current_price: float) -> Optional[str]:
        """
        检查是否触发止损/止盈
        
        Args:
            code: 股票代码
            current_price: 当前价格
            
        Returns:
            触发的条件类型: 'STOP_LOSS' / 'TAKE_PROFIT' / None
        """
        if code not in self.positions:
            return None
        
        pos = self.positions[code]
        entry = pos['entry']
        qty = pos['qty']
        change_pct = (current_price - entry) / entry
        
        # 检查止损
        if current_price <= pos['stop']:
            self._emit_sell(code, 'STOP_LOSS', current_price, qty, pos)
            self.positions.pop(code)
            return 'STOP_LOSS'
        
        # 检查止盈
        if current_price >= pos['profit']:
            self._emit_sell(code, 'TAKE_PROFIT', current_price, qty, pos)
            self.positions.pop(code)
            return 'TAKE_PROFIT'
        
        return None
    
    def on_bar(self, code: str, close_price: float) -> Optional[str]:
        """
        K线收盘时检查（更稳健）
        """
        return self.on_tick(code, close_price)
    
    def get_position_info(self, code: str) -> Optional[Dict]:
        """获取持仓信息"""
        return self.positions.get(code)
    
    def get_all_positions(self) -> Dict[str, Dict]:
        """获取所有持仓"""
        return self.positions.copy()
    
    def get_position_count(self) -> int:
        """获取当前持仓数量"""
        return len(self.positions)
    
    def can_buy(self, code: str, max_position_per_stock: int = 5000) -> bool:
        """检查是否可以买入"""
        if code in self.positions:
            return self.positions[code]['qty'] < max_position_per_stock
        return True
    
    def _emit_sell(self, code: str, reason: str, price: float, qty: int, pos: Dict):
        """发送卖出信号"""
        reason_cn = '止损' if reason == 'STOP_LOSS' else '止盈'
        profit = (price - pos['entry']) * qty
        profit_pct = (price - pos['entry']) / pos['entry']
        
        self._log(f"🚨 触发{reason_cn}: {code} @ {price} qty:{qty} 浮盈:{profit:.2f}({profit_pct:.2%})")
        
        # 发送信号给 OpenClaw
        self._notify_openclaw(
            f"【卖出信号】\n"
            f"股票: {code}\n"
            f"动作: SELL\n"
            f"价格: {price}\n"
            f"数量: {qty}\n"
            f"触发原因: {reason_cn}\n"
            f"浮盈: {profit:.2f} ({profit_pct:.2%})"
        )
    
    def _notify_openclaw(self, message: str):
        """通知 OpenClaw"""
        if TEST_MODE:
            print(f"[TEST MODE] 跳过 openclaw 调用，通知内容: {message}")
            return
        try:
            subprocess.run([
                'openclaw', 'agent',
                '--message', message,
                '--channel', 'feishu'
            ], timeout=5)
        except Exception as e:
            self._log(f"⚠️ 通知 OpenClaw 失败: {e}")
    
    def _log(self, message: str):
        """写日志"""
        if not os.path.exists(LOG_DIR):
            os.makedirs(LOG_DIR)

        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_line = f"[{timestamp}] {message}\n"

        print(log_line.strip(), flush=True)

        with open(LOG_FILE, 'a') as f:
            f.write(log_line)


# ============ 使用示例 ============

if __name__ == '__main__':
    # 创建监控器
    monitor = PositionMonitor()
    
    # 模拟：买入后添加监控
    print("\n" + "="*50)
    print("测试：添加持仓监控")
    print("="*50)
    
    monitor.add_position(
        code='HK.00700',
        qty=100,
        entry_price=400.0,
        stop_loss=388.0,      # -3%
        take_profit=420.0,    # +5%
        stop_loss_pct=-0.03,
        take_profit_pct=0.05,
        reason='MA金叉买入'
    )
    
    # 模拟：行情更新
    print("\n" + "="*50)
    print("测试：价格波动检查")
    print("="*50)
    
    test_prices = [402.0, 410.0, 418.0, 420.0, 422.0]
    for price in test_prices:
        result = monitor.on_tick('HK.00700', price)
        if result:
            print(f"✅ 止盈触发！当前价: {price}")
            break
        else:
            print(f"价格 {price} - 未触发")
