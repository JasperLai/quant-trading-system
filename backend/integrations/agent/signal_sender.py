#!/usr/bin/env python3
"""
Agent 对接层。

负责：
1. 构造标准化交易/通知消息
2. 调用 openclaw agent
3. 写入 backend 统一日志目录
"""

import argparse
import json
import subprocess
from datetime import datetime

from backend.core.config import AGENT_TEST_MODE, LOG_DIR
from backend.core.logging import get_logger

SIGNAL_LOG_FILE = LOG_DIR / 'signals.log'
logger = get_logger(__name__)


def ensure_log_dir():
    """确保 backend 日志目录存在。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def log_signal(code, action, price, quantity, note=''):
    """记录标准化交易信号。"""
    ensure_log_dir()
    with SIGNAL_LOG_FILE.open('a') as file:
        log_entry = {
            'time': datetime.now().isoformat(),
            'code': code,
            'action': action,
            'price': price,
            'quantity': quantity,
            'note': note,
        }
        file.write(json.dumps(log_entry, ensure_ascii=False) + '\n')


def send_agent_message(message, *, log_prefix='消息'):
    """向 openclaw agent 发送原始文本消息。"""
    ensure_log_dir()
    logger.info("发送%s: %s", log_prefix, message)
    if AGENT_TEST_MODE:
        logger.info("[TEST MODE] 跳过 openclaw 调用，内容: %s", message)
        return

    subprocess.run(
        [
            'openclaw',
            'agent',
            '--message',
            message,
            '--channel',
            'feishu',
        ],
        timeout=5,
        check=False,
    )


def send_signal(code, action, price, quantity, note=''):
    """发送标准化交易信号给 agent。"""
    action_cn = '买入' if action.upper() == 'BUY' else '卖出'
    message = f"【交易信号】\n股票: {code}\n动作: {action_cn}\n价格: {price}\n数量: {quantity}"
    if note:
        message += f"\n备注: {note}"

    send_agent_message(message, log_prefix='信号')
    log_signal(code, action, price, quantity, note)
    logger.info("信号已发送！")


def main():
    parser = argparse.ArgumentParser(description='发送交易信号给 OpenClaw')
    parser.add_argument('--code', required=True, help='股票代码，如 HK.00700')
    parser.add_argument('--action', required=True, choices=['BUY', 'SELL'], help='交易动作: BUY 或 SELL')
    parser.add_argument('--price', type=float, required=True, help='挂单价格')
    parser.add_argument('--qty', type=int, required=True, help='数量')
    parser.add_argument('--note', default='', help='备注信息')

    args = parser.parse_args()
    send_signal(args.code, args.action.upper(), args.price, args.qty, args.note)


if __name__ == '__main__':
    main()
