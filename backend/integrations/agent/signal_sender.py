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


def log_signal(code, action, price, quantity, note='', payload=None):
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
        if payload is not None:
            log_entry['payload'] = payload
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


def infer_market(code):
    return code.split('.', 1)[0] if '.' in code else 'HK'


def build_agent_signal_payload(
    code,
    action,
    price,
    quantity,
    *,
    note='',
    run_id=None,
    account_id=None,
    source='strategy',
    trade_env='SIMULATE',
    market=None,
    order_type='NORMAL',
):
    market = market or infer_market(code)
    execution_payload = {
        'code': code,
        'qty': quantity,
        'price': price,
        'side': action.upper(),
        'market': market,
        'tradeEnv': trade_env,
        'orderType': order_type,
        'runId': run_id,
        'source': source,
        'note': note or None,
    }

    if action.upper() == 'BUY':
        confirm_api = None
        confirm_payload = None
    elif source == 'guardian' and account_id:
        confirm_api = None
        confirm_payload = None
    else:
        confirm_api = None
        confirm_payload = None

    return {
        'signalType': 'TRADE_INTENT',
        'source': source,
        'runId': run_id,
        'accountId': account_id,
        'tradeIntent': {
            'code': code,
            'action': action.upper(),
            'price': price,
            'quantity': quantity,
            'market': market,
            'tradeEnv': trade_env,
            'orderType': order_type,
            'note': note,
        },
        'execution': {
            'api': '/api/trading/orders',
            'method': 'POST',
            'payload': execution_payload,
        },
        'settlement': {
            'mode': 'AUTO_BY_TRADE_ORDER',
            'description': '通过 /api/trading/orders 下单后，后端会基于 broker 订单实际成交量自动落账，无需再调 confirm 接口。',
        },
        'confirmation': {
            'api': confirm_api,
            'method': None,
            'payload': confirm_payload,
        },
    }


def send_signal(code, action, price, quantity, note='', **kwargs):
    """发送标准化交易信号给 agent。"""
    action_cn = '买入' if action.upper() == 'BUY' else '卖出'
    payload = build_agent_signal_payload(
        code,
        action,
        price,
        quantity,
        note=note,
        **kwargs,
    )
    message = f"【交易信号】\n股票: {code}\n动作: {action_cn}\n价格: {price}\n数量: {quantity}"
    if note:
        message += f"\n备注: {note}"
    message += (
        "\n\n请严格按以下流程执行："
        "\n1. 调用 execution.api 下单。"
        "\n2. 不要直接调用 FUTU API。"
        "\n3. 下单后由后端基于 broker 实际成交量自动落账，不需要再手动调用 confirm 接口。"
        f"\n\nsignal_payload={json.dumps(payload, ensure_ascii=False)}"
    )

    send_agent_message(message, log_prefix='信号')
    log_signal(code, action, price, quantity, note, payload=payload)
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
