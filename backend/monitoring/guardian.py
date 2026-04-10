#!/usr/bin/env python3
"""Independent position guardian that survives strategy subprocess exit."""

import threading
import time

from futu import RET_ERROR, RET_OK, StockQuoteHandlerBase

from backend.core.config import DEFAULT_HOST, DEFAULT_PORT, GUARDIAN_REFRESH_INTERVAL_SEC
from backend.core.logging import get_logger
from backend.integrations.agent.signal_sender import send_signal
from backend.integrations.futu.quote_gateway import FutuQuoteGateway
from backend.repositories.runtime_repository import RuntimeRepository

logger = get_logger(__name__)


class GuardianQuoteHandler(StockQuoteHandlerBase):
    def __init__(self, guardian):
        self.guardian = guardian

    def on_recv_rsp(self, rsp_pb):
        ret_code, data = super().on_recv_rsp(rsp_pb)
        if ret_code != RET_OK:
            logger.error("Guardian quote handler error: %s", data)
            return RET_ERROR, data
        for quote in data.to_dict('records'):
            self.guardian.on_quote(quote)
        return RET_OK, data


class PositionGuardian:
    def __init__(self, repository: RuntimeRepository, host=DEFAULT_HOST, port=DEFAULT_PORT, refresh_interval=GUARDIAN_REFRESH_INTERVAL_SEC):
        self.repository = repository
        self.refresh_interval = refresh_interval
        self.gateway = None
        self.quote_handler = GuardianQuoteHandler(self)
        self._thread = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._positions_by_code = {}
        self._pending_sell_codes = set()
        self._subscribed_codes = set()
        self._active_alerts = set()
        self._last_error = None
        self._started_at = None
        self.host = host
        self.port = port

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._started_at = time.time()
        self._last_error = None
        self._thread = threading.Thread(target=self._run, name='position-guardian', daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        if self.gateway is not None:
            self.gateway.stop()
            self.gateway = None

    def _ensure_gateway(self):
        if self.gateway is not None:
            return
        self.gateway = FutuQuoteGateway(host=self.host, port=self.port)
        ret = self.gateway.set_handler(self.quote_handler)
        if ret != RET_OK:
            raise RuntimeError('guardian quote handler setup failed')
        logger.info("PositionGuardian started and connected to OpenD")

    def get_status(self):
        thread_alive = self._thread is not None and self._thread.is_alive()
        status = {
            'running': thread_alive and not self._stop_event.is_set(),
            'threadAlive': thread_alive,
            'host': self.host,
            'port': self.port,
            'startedAt': self._started_at,
            'subscribedCodes': sorted(self._subscribed_codes),
            'positionCount': sum(len(items) for items in self._positions_by_code.values()),
            'lastError': self._last_error,
            'openDConnected': False,
            'quoteLogin': False,
            'detail': 'guardian_not_started',
        }

        if self.gateway is None:
            return status

        try:
            ret, data = self.gateway.get_global_state()
            if ret == RET_OK and data:
                quote_login = bool(data.get('qot_logined'))
                status.update(
                    {
                        'openDConnected': True,
                        'quoteLogin': quote_login,
                        'detail': 'connected' if quote_login else 'connected_but_quote_not_logged_in',
                    }
                )
            else:
                status['detail'] = f'get_global_state_failed:{data}'
        except Exception as exc:
            status['detail'] = f'openD_check_failed:{exc}'
        return status

    def _refresh_positions(self):
        positions = self.repository.list_all_account_positions()
        pending_sell_codes = {
            item['code']
            for item in self.repository.list_all_pending_orders(side='SELL')
        }

        positions_by_code = {}
        for position in positions:
            positions_by_code.setdefault(position['code'], []).append(position)

        active_keys = {
            self._position_alert_key(item)
            for item in positions
        }
        with self._lock:
            self._positions_by_code = positions_by_code
            self._pending_sell_codes = pending_sell_codes
            self._active_alerts.intersection_update(active_keys)

        new_codes = set(positions_by_code.keys()) - self._subscribed_codes
        if new_codes and self.gateway is not None:
            ret, data = self.gateway.subscribe_quotes(sorted(new_codes))
            if ret == RET_OK:
                self._subscribed_codes.update(new_codes)
                logger.info("PositionGuardian subscribed quotes: %s", ', '.join(sorted(new_codes)))
            else:
                logger.error("PositionGuardian subscribe failed: %s", data)

    def on_quote(self, quote):
        code = quote['code']
        price = quote['last_price']
        with self._lock:
            positions = [dict(item) for item in self._positions_by_code.get(code, [])]
            pending_sell_codes = set(self._pending_sell_codes)

        for position in positions:
            alert_key = self._position_alert_key(position)
            if alert_key in self._active_alerts:
                continue
            if code in pending_sell_codes:
                continue

            reason = None
            if price <= position['stop']:
                reason = '固定止损卖出'
            elif price >= position['profit']:
                reason = '固定止盈卖出'

            if reason is None:
                continue

            with self._lock:
                self._active_alerts.add(alert_key)
            send_signal(
                code,
                'SELL',
                price,
                position['qty'],
                reason,
                account_id=position['account_id'],
                source='guardian',
                trade_env='SIMULATE',
            )
            logger.warning(
                "PositionGuardian triggered SELL: account_id=%s code=%s price=%s reason=%s",
                position['account_id'],
                code,
                price,
                reason,
            )

    def _run(self):
        try:
            self._ensure_gateway()
        except Exception as exc:
            self._last_error = str(exc)
            logger.exception("PositionGuardian failed to initialize: %s", exc)
            return

        while not self._stop_event.is_set():
            try:
                self._refresh_positions()
            except Exception as exc:
                self._last_error = str(exc)
                logger.exception("PositionGuardian refresh failed: %s", exc)
            self._stop_event.wait(self.refresh_interval)

    @staticmethod
    def _position_alert_key(position):
        return (
            position['account_id'],
            position['code'],
            position['qty'],
            position['stop'],
            position['profit'],
        )
