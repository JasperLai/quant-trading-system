#!/usr/bin/env python3
"""均线策略实时运行适配层。"""

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
    """实时报价回调。"""

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


class RealtimeMaStrategyRunner:
    """连接行情源并驱动纯信号层的运行时适配器。"""

    strategy_name = 'realtime_ma_cross'
    signal_class = None

    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, run_id=None, db_path=None, **signal_kwargs):
        if self.signal_class is None:
            raise ValueError('signal_class 未定义')

        self.signal = self.signal_class(**signal_kwargs)
        self.codes = self.signal.codes
        self.short_ma_period = self.signal.short_ma_period
        self.long_ma_period = self.signal.long_ma_period
        self.order_qty = self.signal.order_qty
        self.gateway = FutuQuoteGateway(host=host, port=port)
        # 兼容无数据库的本地测试/离线场景；正式架构下不再作为状态事实来源。
        self.monitor = PositionMonitor()
        self.quote_handler = QuoteHandler(self)
        self.run_id = run_id
        self.repository = RuntimeRepository(db_path=db_path) if run_id else None
        self.position_service = PositionService(self.repository) if self.repository is not None else None
        self._last_runtime_state_signature = None
        self._last_repository_refresh_ts = 0.0
        self._strategy_positions_by_code = {}

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
        result = self.signal.update_bar(bar_data)
        logger.info(
            "[K线] %s 时间: %s 收盘价: %.2f | 数据量: %s",
            result['code'],
            result['time_key'],
            result['close'],
            result['count'],
        )

    def sync_runtime_state(self, force=False):
        """将当前 pending 状态同步到数据库。"""
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

    def on_buy_signal(self, code, price, qty):
        logger.info("🟢 金叉信号！买入 %s @ %s", code, price)
        send_signal(code, 'BUY', price, qty, '均线金叉买入')
        logger.info("🟡 买入待确认: %s，等待 agent 成交后登记持仓", code)

    def on_sell_signal(self, code, price, qty):
        logger.info("🔴 死叉信号！卖出 %s @ %s", code, price)
        send_signal(code, 'SELL', price, qty, '均线死叉卖出')
        logger.info("🟠 卖出待确认: %s，等待 agent 成交后移除持仓", code)

    def on_quote(self, quote_data):
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
            logger.info(
                "[报价] %s 实时价: %.2f | 短期MA(%s): %.2f | 长期MA(%s): %.2f",
                code,
                price,
                self.short_ma_period,
                result['short_ma'],
                self.long_ma_period,
                result['long_ma'],
            )
            if result['action'] == 'BUY':
                self.on_buy_signal(code, price, result['qty'])
            elif result['action'] == 'SELL':
                self.on_sell_signal(code, price, result['qty'])

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

        真实架构下，成交确认应由主进程 API -> PositionService 统一落库。
        该方法仅保留给测试或极简离线场景，不再承载正式确认链路。
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

        正式成交确认统一由主进程 PositionService 处理；这里仅用于兼容测试。
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
        logger.info("=" * 50)
        logger.info("启动策略: %s", self.strategy_name)
        logger.info("代码: %s", ', '.join(self.codes))
        logger.info("短期均线周期: %s", self.short_ma_period)
        logger.info("长期均线周期: %s", self.long_ma_period)
        logger.info("单次下单数量: %s", self.order_qty)
        logger.info("止损比例: %.1f%%", STOP_LOSS_PCT * 100)
        logger.info("止盈比例: %.1f%%", TAKE_PROFIT_PCT * 100)
        logger.info("=" * 50)
        if self.repository is not None and self.run_id is not None:
            self.repository.update_run_status(self.run_id, 'running')

        ret = self.gateway.set_handler(self.quote_handler)
        if ret != RET_OK:
            logger.error("报价回调处理器设置失败")
            return

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

        logger.info("初始化历史K线数据...")
        for code in self.codes:
            ret, data = self.gateway.get_daily_bars(code, self.long_ma_period + 5)
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
        logger.info("当前均线状态: 短期MA(%s) vs 长期MA(%s)", self.short_ma_period, self.long_ma_period)
        for code in self.codes:
            logger.info(
                "  %s: 短期MA(%s)=%.2f, 长期MA(%s)=%.2f",
                code,
                self.short_ma_period,
                self.last_short_ma[code],
                self.long_ma_period,
                self.last_long_ma[code],
            )
        logger.info("按 Ctrl+C 停止")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("停止策略...")
            self.stop()

    def stop(self):
        self.gateway.stop()
        if self.repository is not None and self.run_id is not None:
            self.repository.update_run_status(self.run_id, 'stopped', stopped_at=time.time())
        logger.info("策略已停止")
