#!/usr/bin/env python3
"""
信号发送脚本 - 策略产生信号后调用此脚本发送给 OpenClaw

Usage:
    python signal_sender.py --code HK.00700 --action BUY --price 400.0 --qty 100
"""

import argparse
import subprocess
import json
import os
from datetime import datetime

LOG_DIR = os.path.dirname(os.path.abspath(__file__)) + '/logs'
LOG_FILE = os.path.join(LOG_DIR, 'signals.log')


def ensure_log_dir():
    """确保日志目录存在"""
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)


def log_signal(code, action, price, quantity, note=''):
    """记录信号到日志"""
    ensure_log_dir()
    with open(LOG_FILE, 'a') as f:
        log_entry = {
            'time': datetime.now().isoformat(),
            'code': code,
            'action': action,
            'price': price,
            'quantity': quantity,
            'note': note
        }
        f.write(json.dumps(log_entry) + '\n')


def send_signal(code, action, price, quantity, note=''):
    """
    发送交易信号给 OpenClaw AI 助手

    Args:
        code: 股票代码，如 HK.00700, US.AAPL
        action: 交易动作，BUY / SELL
        price: 挂单价格
        quantity: 数量
        note: 备注信息
    """
    # 构建消息
    action_cn = '买入' if action.upper() == 'BUY' else '卖出'
    message = f"【交易信号】\n股票: {code}\n动作: {action_cn}\n价格: {price}\n数量: {quantity}"
    if note:
        message += f"\n备注: {note}"

    # 调用 OpenClaw CLI 发送信号
    print(f"发送信号: {action} {code} @ {price}")
    subprocess.run([
        'openclaw', 'agent',
        '--message', message,
        '--channel', 'feishu'
    ])

    # 记录日志
    log_signal(code, action, price, quantity, note)
    print("信号已发送！")


def main():
    parser = argparse.ArgumentParser(description='发送交易信号给 OpenClaw')
    parser.add_argument('--code', required=True, help='股票代码，如 HK.00700')
    parser.add_argument('--action', required=True, choices=['BUY', 'SELL'],
                        help='交易动作: BUY 或 SELL')
    parser.add_argument('--price', type=float, required=True, help='挂单价格')
    parser.add_argument('--qty', type=int, required=True, help='数量')
    parser.add_argument('--note', default='', help='备注信息')

    args = parser.parse_args()
    send_signal(args.code, args.action.upper(), args.price, args.qty, args.note)


if __name__ == '__main__':
    main()
