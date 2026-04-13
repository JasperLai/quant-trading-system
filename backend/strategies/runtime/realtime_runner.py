#!/usr/bin/env python3
"""策略实时运行适配层。

这个模块的职责不是定义具体交易策略，而是把“纯策略逻辑类”接到真实运行环境上。

新的分层方式是：
1. signal / strategy logic:
   只负责维护策略内部状态，并在收到 bar / quote 后给出 BUY / SELL / HOLD 意图。
2. runtime adapter:
   负责连接 OpenD、注册回调、同步数据库状态、调用 send_signal 发给 agent。

因此，新增策略时默认只需要新增 signal 类，并在 StrategyManager 里注册；
RealtimeStrategyRunner 会根据 signal 暴露出来的统一接口去驱动运行。
"""

import json
import time

from futu import RET_ERROR, RET_OK, StockQuoteHandlerBase

from backend.core.config import DEFAULT_HOST, DEFAULT_PORT, RUNTIME_STATE_REFRESH_INTERVAL_SEC, STOP_LOSS_PCT, TAKE_PROFIT_PCT
from backend.core.logging import get_logger
from backend.integrations.agent.signal_sender import send_signal
from backend.integrations.futu.quote_gateway import FutuQuoteGateway
from backend.monitoring.position_monitor import PositionMonitor
from backend.repositories.runtime_repository import RuntimeRepository
from backend.services.position_service import PositionService

logger = get_logger(__name__)


class QuoteHandler(StockQuoteHandlerBase):
    """实时报价回调。

    Futu/OpenD 的推送先进入 handler，再转发给运行时对象的 on_quote。
    handler 本身不做业务判断，避免把策略逻辑散落到 SDK 回调类里。
    """

    def __init__(self, strategy):
        self.strategy = strategy

    def on_recv_rsp(self, rsp_pb):
        ret_code, data = super().on_recv_rsp(rsp_pb)
        if ret_code != RET_OK:
            logger.error("QuoteHandler error: %s", data)
            return RET_ERROR, data
        for quote in data.to_dict('records'):
            logger.info(
                "[QUOTE回调] %s %s %s last=%s volume=%s",
                quote['code'],
                quote.get('data_date', ''),
                quote.get('data_time', ''),
                quote['last_price'],
                quote.get('volume', 'N/A'),
            )
            self.strategy.on_quote(quote)
        return RET_OK, data


class RealtimeStrategyRunner:
    """连接行情源并驱动策略逻辑的通用运行时适配器。

    这个类是“策略逻辑”和“真实运行环境”的胶水层，核心职责有 4 个：

    1. 连接 OpenD 行情并注册实时报价回调。
    2. 从数据库刷新当前 run 的持仓与 pending 状态，避免只依赖进程内存。
    3. 在收到 quote 时调用 signal.evaluate_quote()，把策略意图转成运行动作。
    4. 把 BUY / SELL 意图通过 send_signal 发给 agent，而不是在策略进程里直接下单。

    它刻意不关心：
    - 订单如何实际成交
    - 成交后如何最终落账
    这些由主进程里的 trading / settlement / repository 体系处理。
    """

    strategy_name = 'realtime_strategy'
    signal_class = None

    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, run_id=None, db_path=None, signal_class=None, strategy_name=None, **signal_kwargs):
        if signal_class is not None:
            self.signal_class = signal_class
        if strategy_name is not None:
            self.strategy_name = strategy_name
        if self.signal_class is None:
            raise ValueError('signal_class 未定义')

        # signal 是纯策略逻辑对象。runtime 只驱动它，不在这里写具体交易规则。
        self.signal = self.signal_class(**signal_kwargs)
        self.codes = self.signal.codes
        self.short_ma_period = self.signal.short_ma_period
        self.long_ma_period = self.signal.long_ma_period
        self.order_qty = self.signal.order_qty
        self.gateway = FutuQuoteGateway(host=host, port=port)
        # monitor 仅保留给无数据库的测试/离线路径；正式状态事实来源是数据库。
        self.monitor = PositionMonitor()
        self.quote_handler = QuoteHandler(self)
        self.run_id = run_id
        self.repository = RuntimeRepository(db_path=db_path) if run_id else None
        self.position_service = PositionService(self.repository) if self.repository is not None else None
        # 通过签名避免每次 quote 都重复写相同的 pending 状态。
        self._last_runtime_state_signature = None
        self._last_repository_refresh_ts = 0.0
        # 当前 run 在数据库中的策略级持仓快照，key=code。
        self._strategy_positions_by_code = {}

    def requires_daily_bars(self):
        """策略是否需要启动时拉取并初始化日 K 数据。"""
        return getattr(self.signal, 'requires_daily_bars', getattr(self.signal, 'long_ma_period', 0) > 0)

    def history_bar_count(self):
        """策略初始化时需要的历史 bar 数量。"""
        hook = getattr(self.signal, 'history_bar_count', None)
        if callable(hook):
            return hook()
        if isinstance(hook, int):
            return hook
        long_ma_period = getattr(self.signal, 'long_ma_period', 0) or 0
        return long_ma_period + 5 if long_ma_period > 0 else 0

    def startup_lines(self):
        """启动日志文案钩子，优先由 signal 自定义。"""
        hook = getattr(self.signal, 'startup_lines', None)
        if callable(hook):
            return hook()
        lines = [
            f"启动策略: {self.strategy_name}",
            f"代码: {', '.join(self.codes)}",
            f"单次下单数量: {self.order_qty}",
        ]
        if getattr(self.signal, 'short_ma_period', 0) and getattr(self.signal, 'long_ma_period', 0):
            lines.extend(
                [
                    f"短期均线周期: {self.short_ma_period}",
                    f"长期均线周期: {self.long_ma_period}",
                ]
            )
        return lines

    def format_bar_log(self, result):
        """bar 更新日志文案钩子。"""
        hook = getattr(self.signal, 'format_bar_log', None)
        if callable(hook):
            return hook(result)
        return "[K线] %s 时间: %s 收盘价: %.2f | 数据量: %s" % (
            result['code'],
            result['time_key'],
            result['close'],
            result['count'],
        )

    def format_quote_log(self, result):
        """quote 评估日志文案钩子。"""
        hook = getattr(self.signal, 'format_quote_log', None)
        if callable(hook):
            return hook(result)
        return "[报价] %s 实时价: %.2f | 短期MA(%s): %.2f | 长期MA(%s): %.2f" % (
            result['code'],
            result['price'],
            self.short_ma_period,
            result['short_ma'],
            self.long_ma_period,
            result['long_ma'],
        )

    def initial_state_lines(self):
        """启动完成后的初始状态输出钩子。"""
        hook = getattr(self.signal, 'initial_state_lines', None)
        if callable(hook):
            return hook()
        if not self.requires_daily_bars():
            return []
        lines = [f"当前均线状态: 短期MA({self.short_ma_period}) vs 长期MA({self.long_ma_period})"]
        for code in self.codes:
            lines.append(
                "  %s: 短期MA(%s)=%.2f, 长期MA(%s)=%.2f"
                % (code, self.short_ma_period, self.last_short_ma[code], self.long_ma_period, self.last_long_ma[code])
            )
        return lines

    @property
    def quote_ctx(self):
        return self.gateway.context

    @property
    def prices(self):
        return self.signal.prices

    @property
    def bar_time_keys(self):
        return self.signal.bar_time_keys

    @property
    def last_short_ma(self):
        return self.signal.last_short_ma

    @property
    def last_long_ma(self):
        return self.signal.last_long_ma

    @property
    def pending_buys(self):
        return self.signal.pending_buys

    @property
    def pending_sells(self):
        return self.signal.pending_sells

    @property
    def max_position_per_stock(self):
        return getattr(self.signal, 'max_position_per_stock', None)

    def calculate_ma(self, prices, period):
        return self.signal.calculate_ma(prices, period)

    def calculate_live_ma(self, code, latest_price):
        return self.signal.calculate_live_ma(code, latest_price)

    def get_pending_buy_qty(self, code):
        return self.signal.get_pending_buy_qty(code)

    def clear_pending_buy(self, code, qty=None):
        self.signal.clear_pending_buy(code, qty)

    def get_pending_sell_qty(self, code):
        return self.signal.get_pending_sell_qty(code)

    def clear_pending_sell(self, code, qty=None):
        self.signal.clear_pending_sell(code, qty)

    def on_bar(self, bar_data):
        """把历史 bar 喂给 signal，并输出统一日志。"""
        result = self.signal.update_bar(bar_data)
        logger.info(self.format_bar_log(result))

    def sync_runtime_state(self, force=False):
        """将当前 pending 状态同步到数据库。

        signal 在收到 quote 后可能会更新 pending_buys / pending_sells。
        runtime 负责把这些“尚未成交”的状态同步到数据库，供：
        - agent / UI 查询
        - 主进程对账
        - 重启后状态恢复
        """
        if self.repository is None or self.run_id is None:
            return

        pending_orders = []
        for code in self.codes:
            buy_qty = self.get_pending_buy_qty(code)
            if buy_qty:
                pending_orders.append({'code': code, 'side': 'BUY', 'qty': buy_qty})
            sell_qty = self.get_pending_sell_qty(code)
            if sell_qty:
                pending_orders.append({'code': code, 'side': 'SELL', 'qty': sell_qty})

        state_signature = json.dumps(
            {'pending_orders': pending_orders},
            ensure_ascii=False,
            sort_keys=True,
        )
        if not force and state_signature == self._last_runtime_state_signature:
            return

        self.repository.replace_pending_orders(self.run_id, pending_orders)
        self._last_runtime_state_signature = state_signature

    def refresh_runtime_state_from_repository(self, force=False):
        """从数据库刷新当前 run 的策略级持仓与 pending 状态。

        正式架构下，成交回报和最终落账都在主进程处理，所以子进程不能只相信本地内存。
        每隔一个较短时间窗口把数据库状态拉回进来，避免：
        - agent 已成交，但子进程不知道
        - 本地 pending 与数据库事实不一致
        """
        if self.repository is None or self.run_id is None:
            return
        now = time.time()
        if not force and now - self._last_repository_refresh_ts < RUNTIME_STATE_REFRESH_INTERVAL_SEC:
            return
        positions = self.repository.list_strategy_positions(self.run_id)
        pending_orders = self.repository.list_pending_orders(self.run_id)
        self._strategy_positions_by_code = {item['code']: item for item in positions}
        self.signal.replace_pending_orders(pending_orders)
        self._last_repository_refresh_ts = now

    def on_buy_signal(self, code, price, qty, reason):
        """把策略 BUY 意图发给 agent。

        这里不直接调用 broker，下单动作由 agent 通过我们的交易 API 执行。
        """
        logger.info("🟢 策略信号！买入 %s @ %s | 原因: %s", code, price, reason)
        send_signal(
            code,
            'BUY',
            price,
            qty,
            reason,
            run_id=self.run_id,
            source='strategy',
            trade_env='SIMULATE',
        )
        logger.info("🟡 买入待确认: %s，等待 agent 下单 API 成交回报", code)

    def on_sell_signal(self, code, price, qty, reason):
        """把策略 SELL 意图发给 agent。"""
        logger.info("🔴 策略信号！卖出 %s @ %s | 原因: %s", code, price, reason)
        send_signal(
            code,
            'SELL',
            price,
            qty,
            reason,
            run_id=self.run_id,
            source='strategy',
            trade_env='SIMULATE',
        )
        logger.info("🟠 卖出待确认: %s，等待 agent 下单 API 成交回报", code)

    def on_quote(self, quote_data):
        """处理一条实时报价。

        这是 runtime 的主循环入口，处理顺序是：
        1. 从数据库刷新当前持仓/待确认状态。
        2. 读取该 code 当前持仓数量。
        3. 调用 signal.evaluate_quote() 计算策略意图。
        4. 如有 BUY/SELL，则转发给 agent。
        5. 把新的 pending 状态同步回数据库。
        """
        code = quote_data['code']
        price = quote_data['last_price']
        self.refresh_runtime_state_from_repository()
        if self.repository is not None and self.run_id is not None:
            pos_info = self._strategy_positions_by_code.get(code)
        else:
            pos_info = self.monitor.get_position_info(code)
        position_qty = pos_info['qty'] if pos_info else 0

        result = self.signal.evaluate_quote(quote_data, position_qty=position_qty)
        if result is not None:
            logger.info(self.format_quote_log(result))
            if result['action'] == 'BUY':
                self.on_buy_signal(code, price, result['qty'], result['reason'])
            elif result['action'] == 'SELL':
                self.on_sell_signal(code, price, result['qty'], result['reason'])

        self.sync_runtime_state()

    def confirm_position(
        self,
        code,
        qty,
        entry_price,
        stop_loss=None,
        take_profit=None,
        reason='均线金叉买入',
    ):
        """兼容入口。

        正式流程里，agent 通过交易 API 下单后，由主进程依据 broker 回报自动落账；
        因此运行中子进程通常不应主动调用这里。

        之所以保留，是为了：
        - 单元测试可直接驱动状态变化
        - 离线/最小化调试场景仍能手工登记持仓
        """
        self.clear_pending_buy(code, qty)
        if self.position_service is not None and self.run_id is not None:
            self.position_service.confirm_position(
                run_id=self.run_id,
                code=code,
                qty=qty,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                reason=reason,
            )
        else:
            stop_loss = stop_loss if stop_loss is not None else round(entry_price * (1 + STOP_LOSS_PCT), 2)
            take_profit = take_profit if take_profit is not None else round(entry_price * (1 + TAKE_PROFIT_PCT), 2)
            self.monitor.add_position(
                code=code,
                qty=qty,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                stop_loss_pct=STOP_LOSS_PCT,
                take_profit_pct=TAKE_PROFIT_PCT,
                reason=reason,
            )
            logger.warning("confirm_position() 在无 repository 模式下被调用；该路径仅用于兼容测试。")
        self.refresh_runtime_state_from_repository(force=True)
        self.sync_runtime_state(force=True)

    def confirm_exit(self, code, qty=None, exit_price=None, reason='均线死叉卖出'):
        """兼容入口。

        与 confirm_position 相同，这里仅用于测试或离线路径。
        正式卖出成交应由主进程统一落账，再由子进程从数据库刷新结果。
        """
        pos_info = self.repository.get_strategy_position(self.run_id, code) if self.repository is not None and self.run_id is not None else self.monitor.get_position_info(code)
        exit_qty = qty if qty is not None else (pos_info['qty'] if pos_info else None)
        self.clear_pending_sell(code, exit_qty)
        if self.position_service is not None and self.run_id is not None:
            self.position_service.confirm_exit(
                run_id=self.run_id,
                code=code,
                qty=exit_qty,
                exit_price=exit_price,
                reason=reason,
            )
        else:
            self.monitor.remove_position(code)
            logger.warning("confirm_exit() 在无 repository 模式下被调用；该路径仅用于兼容测试。")
        self.refresh_runtime_state_from_repository(force=True)
        self.sync_runtime_state(force=True)

    def start(self):
        """启动策略运行循环。

        统一启动流程：
        1. 输出启动配置日志。
        2. 将 run 状态更新为 running。
        3. 注册报价回调。
        4. 按 signal 需求决定是否订阅/初始化日 K。
        5. 订阅 QUOTE。
        6. 进入常驻循环，直到外部停止。
        """
        logger.info("=" * 50)
        for line in self.startup_lines():
            logger.info(line)
        logger.info("止损比例: %.1f%%", STOP_LOSS_PCT * 100)
        logger.info("止盈比例: %.1f%%", TAKE_PROFIT_PCT * 100)
        logger.info("=" * 50)
        if self.repository is not None and self.run_id is not None:
            self.repository.update_run_status(self.run_id, 'running')

        ret = self.gateway.set_handler(self.quote_handler)
        if ret != RET_OK:
            logger.error("报价回调处理器设置失败")
            return

        if self.requires_daily_bars():
            logger.info("正在订阅日K线...")
            ret, data = self.gateway.subscribe_daily_bars(self.codes)
            if ret != RET_OK:
                logger.error("日K订阅失败: %s", data)
                return
            logger.info("日K订阅成功")

        logger.info("正在订阅实时报价...")
        ret, data = self.gateway.subscribe_quotes(self.codes)
        if ret != RET_OK:
            logger.error("报价订阅失败: %s", data)
            return
        logger.info("订阅成功: %s", ', '.join(self.codes))

        if self.requires_daily_bars():
            logger.info("初始化历史K线数据...")
            for code in self.codes:
                ret, data = self.gateway.get_daily_bars(code, self.history_bar_count())
                if ret == RET_OK:
                    for bar in data.to_dict('records'):
                        self.on_bar(bar)
                    short_ma, long_ma = self.signal.refresh_reference_ma(code)
                    logger.info(
                        "  %s: 获取到 %s 条K线 | 短期MA(%s): %.2f | 长期MA(%s): %.2f",
                        code,
                        len(data),
                        self.short_ma_period,
                        short_ma,
                        self.long_ma_period,
                        long_ma,
                    )
                else:
                    logger.error("  %s: 获取失败 %s", code, data)

        logger.info("=== 策略初始化完成，等待实时报价... ===")
        for line in self.initial_state_lines():
            logger.info(line)
        logger.info("按 Ctrl+C 停止")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("停止策略...")
            self.stop()

    def stop(self):
        """停止行情连接并把 run 状态写回数据库。"""
        self.gateway.stop()
        if self.repository is not None and self.run_id is not None:
            self.repository.update_run_status(self.run_id, 'stopped', stopped_at=time.time())
        logger.info("策略已停止")


RealtimeMaStrategyRunner = RealtimeStrategyRunner
