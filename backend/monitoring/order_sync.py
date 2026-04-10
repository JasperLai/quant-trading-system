#!/usr/bin/env python3
"""Background order sync that auto-settles broker fills."""

import threading

from backend.core.config import ORDER_SYNC_INTERVAL_SEC
from backend.core.logging import get_logger

logger = get_logger(__name__)


class OrderSyncWorker:
    def __init__(self, trading_service, refresh_interval=ORDER_SYNC_INTERVAL_SEC):
        self.trading_service = trading_service
        self.refresh_interval = refresh_interval
        self._thread = None
        self._stop_event = threading.Event()
        self._last_error = None

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._last_error = None
        self._thread = threading.Thread(target=self._run, name='order-sync-worker', daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def get_status(self):
        return {
            'running': self._thread is not None and self._thread.is_alive() and not self._stop_event.is_set(),
            'lastError': self._last_error,
            'intervalSec': self.refresh_interval,
        }

    def _run(self):
        logger.info("OrderSyncWorker started")
        while not self._stop_event.is_set():
            try:
                self.trading_service.sync_unsettled_orders()
            except Exception as exc:
                self._last_error = str(exc)
                logger.exception("OrderSyncWorker sync failed: %s", exc)
            self._stop_event.wait(self.refresh_interval)
