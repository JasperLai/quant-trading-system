#!/usr/bin/env python3
"""均线策略实时运行适配层。"""

import json
import time

from futu import RET_ERROR, RET_OK, StockQuoteHandlerBase

from backend.integrations.agent.signal_sender import send_signal
from backend.integrations.futu.quote_gateway import FutuQuoteGateway
from backend.monitoring.position_monitor import PositionMonitor
from backend.repositories.runtime_repository import RuntimeRepository

STOP_LOSS_PCT = -0.20
TAKE_PROFIT_PCT = 0.30


class QuoteHandler(StockQuoteHandlerBase):
    """实时报价回调。"""

    def __init__(self, strategy):
        self.strategy = strategy

    def on_recv_rsp(self, rsp_pb):
        ret_code, data = super().on_recv_rsp(rsp_pb)
        if ret_code != RET_OK:
            print("QuoteHandler error: %s" % data)
            return RET_ERROR, data
        for quote in data.to_dict('records'):
            print(
                f"[QUOTE回调] {quote['code']} "
                f"{quote.get('data_date', '')} {quote.get('data_time', '')} "
                f"last={quote['last_price']} volume={quote.get('volume', 'N/A')}",
                flush=True,
            )
            self.strategy.on_quote(quote)
        return RET_OK, data


class RealtimeMaStrategyRunner:
    """连接行情源并驱动纯信号层的运行时适配器。"""

    strategy_name = 'realtime_ma_cross'
    signal_class = None

    def __init__(self, host='127.0.0.1', port=11111, run_id=None, db_path=None, **signal_kwargs):
        if self.signal_class is None:
            raise ValueError('signal_class 未定义')

        self.signal = self.signal_class(**signal_kwargs)
        self.codes = self.signal.codes
        self.short_ma_period = self.signal.short_ma_period
        self.long_ma_period = self.signal.long_ma_period
        self.order_qty = self.signal.order_qty
        self.gateway = FutuQuoteGateway(host=host, port=port)
        self.monitor = PositionMonitor()
        self.quote_handler = QuoteHandler(self)
        self.run_id = run_id
        self.repository = RuntimeRepository(db_path=db_path) if run_id else None

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
        print(
            f"[K线] {result['code']} 时间: {result['time_key']} "
            f"收盘价: {result['close']:.2f} | 数据量: {result['count']}"
        )

    def sync_runtime_state(self):
        """将当前持仓和 pending 状态同步到数据库。"""
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

        self.repository.replace_positions(self.run_id, self.monitor.get_all_positions())
        self.repository.replace_pending_orders(self.run_id, pending_orders)

    def on_buy_signal(self, code, price, qty):
        print(f"🟢 金叉信号！买入 {code} @ {price}")
        send_signal(code, 'BUY', price, qty, '均线金叉买入')
        print(f"🟡 买入待确认: {code}，等待 agent 成交后登记持仓", flush=True)

    def on_sell_signal(self, code, price, qty):
        print(f"🔴 死叉信号！卖出 {code} @ {price}")
        send_signal(code, 'SELL', price, qty, '均线死叉卖出')
        print(f"🟠 卖出待确认: {code}，等待 agent 成交后移除持仓", flush=True)

    def on_quote(self, quote_data):
        code = quote_data['code']
        price = quote_data['last_price']
        pos_info = self.monitor.get_position_info(code)
        position_qty = pos_info['qty'] if pos_info else 0

        result = self.signal.evaluate_quote(quote_data, position_qty=position_qty)
        if result is not None:
            print(
                f"[报价] {code} 实时价: {price:.2f} | "
                f"短期MA({self.short_ma_period}): {result['short_ma']:.2f} | "
                f"长期MA({self.long_ma_period}): {result['long_ma']:.2f}"
            )
            if result['action'] == 'BUY':
                self.on_buy_signal(code, price, result['qty'])
            elif result['action'] == 'SELL':
                self.on_sell_signal(code, price, result['qty'])

        self.monitor.on_tick(code, price)
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
        stop_loss = stop_loss if stop_loss is not None else round(entry_price * (1 + STOP_LOSS_PCT), 2)
        take_profit = take_profit if take_profit is not None else round(entry_price * (1 + TAKE_PROFIT_PCT), 2)
        self.clear_pending_buy(code, qty)
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
        if self.repository is not None and self.run_id is not None:
            pos_info = self.monitor.get_position_info(code) or {}
            self.repository.record_execution(
                run_id=self.run_id,
                code=code,
                side='BUY',
                qty=qty,
                price=entry_price,
                reason=reason,
                position_qty_after=pos_info.get('qty'),
                avg_entry_after=pos_info.get('entry'),
            )
        self.sync_runtime_state()

    def confirm_exit(self, code, qty=None, exit_price=None, reason='均线死叉卖出'):
        """卖出成交确认后移除持仓监控，并清理 pending SELL。"""
        pos_info = self.monitor.get_position_info(code)
        exit_qty = qty if qty is not None else (pos_info['qty'] if pos_info else None)
        self.clear_pending_sell(code, qty)
        if self.repository is not None and self.run_id is not None:
            realized_pnl = None
            if pos_info is not None and exit_price is not None and exit_qty is not None:
                realized_pnl = round((exit_price - pos_info['entry']) * exit_qty, 4)
            self.repository.record_execution(
                run_id=self.run_id,
                code=code,
                side='SELL',
                qty=exit_qty or 0,
                price=exit_price,
                reason=reason,
                position_qty_after=0,
                avg_entry_after=None,
                realized_pnl=realized_pnl,
                metadata={'position_entry': pos_info.get('entry') if pos_info else None},
            )
        self.monitor.remove_position(code)
        self.sync_runtime_state()

    def process_control_commands(self):
        """
        处理外部投递给当前策略进程的控制命令。

        当前主要用于 agent 成交确认后的回调：
        - confirm_buy
        - confirm_sell
        """
        if self.repository is None or self.run_id is None:
            return
        commands = self.repository.fetch_pending_commands(self.run_id)
        if not commands:
            return

        for command in commands:
            action = command.get('action')
            if action == 'confirm_buy':
                self.confirm_position(
                    code=command['code'],
                    qty=command['qty'],
                    entry_price=command['entry_price'],
                    stop_loss=command.get('stop_loss'),
                    take_profit=command.get('take_profit'),
                    reason=command.get('reason', '均线金叉买入'),
                )
                print(f"✅ 已处理成交确认(BUY): {command['code']} qty={command['qty']}", flush=True)
            elif action == 'confirm_sell':
                self.confirm_exit(
                    code=command['code'],
                    qty=command.get('qty'),
                    exit_price=command.get('exit_price'),
                    reason=command.get('reason', '均线死叉卖出'),
                )
                print(f"✅ 已处理成交确认(SELL): {command['code']}", flush=True)
            else:
                print(f"⚠️ 未知控制命令: {command}", flush=True)
            self.repository.mark_command_processed(command['_command_id'])

    def start(self):
        print("=" * 50, flush=True)
        print(f"启动策略: {self.strategy_name}", flush=True)
        print(f"代码: {', '.join(self.codes)}", flush=True)
        print(f"短期均线周期: {self.short_ma_period}", flush=True)
        print(f"长期均线周期: {self.long_ma_period}", flush=True)
        print(f"单次下单数量: {self.order_qty}", flush=True)
        print(f"止损比例: {STOP_LOSS_PCT:.1%}", flush=True)
        print(f"止盈比例: {TAKE_PROFIT_PCT:.1%}", flush=True)
        print("=" * 50, flush=True)
        if self.repository is not None and self.run_id is not None:
            self.repository.update_run_status(self.run_id, 'running')

        ret = self.gateway.set_handler(self.quote_handler)
        if ret != RET_OK:
            print("报价回调处理器设置失败", flush=True)
            return

        print("正在订阅日K线...", flush=True)
        ret, data = self.gateway.subscribe_daily_bars(self.codes)
        if ret != RET_OK:
            print(f"日K订阅失败: {data}", flush=True)
            return
        print("日K订阅成功", flush=True)

        print("正在订阅实时报价...", flush=True)
        ret, data = self.gateway.subscribe_quotes(self.codes)
        if ret != RET_OK:
            print(f"报价订阅失败: {data}", flush=True)
            return
        print(f"订阅成功: {', '.join(self.codes)}", flush=True)

        print("初始化历史K线数据...", flush=True)
        for code in self.codes:
            ret, data = self.gateway.get_daily_bars(code, self.long_ma_period + 5)
            if ret == RET_OK:
                for bar in data.to_dict('records'):
                    self.on_bar(bar)
                short_ma, long_ma = self.signal.refresh_reference_ma(code)
                print(
                    f"  {code}: 获取到 {len(data)} 条K线 | "
                    f"短期MA({self.short_ma_period}): {short_ma:.2f} | "
                    f"长期MA({self.long_ma_period}): {long_ma:.2f}",
                    flush=True,
                )
            else:
                print(f"  {code}: 获取失败 {data}", flush=True)

        print("\n=== 策略初始化完成，等待实时报价... ===", flush=True)
        print(f"当前均线状态: 短期MA({self.short_ma_period}) vs 长期MA({self.long_ma_period})", flush=True)
        for code in self.codes:
            print(
                f"  {code}: "
                f"短期MA({self.short_ma_period})={self.last_short_ma[code]:.2f}, "
                f"长期MA({self.long_ma_period})={self.last_long_ma[code]:.2f}",
                flush=True,
            )
        print("按 Ctrl+C 停止", flush=True)

        try:
            while True:
                self.process_control_commands()
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n停止策略...", flush=True)
            self.stop()

    def stop(self):
        self.gateway.stop()
        if self.repository is not None and self.run_id is not None:
            self.repository.update_run_status(self.run_id, 'stopped', stopped_at=time.time())
        print("策略已停止")
