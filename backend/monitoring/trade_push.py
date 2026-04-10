#!/usr/bin/env python3
"""Trade push listener that auto-settles orders from OpenD push callbacks."""

from futu import RET_OK, TradeDealHandlerBase, TradeOrderHandlerBase

from backend.core.logging import get_logger
from backend.integrations.futu.trade_gateway import FutuTradeGateway
from backend.services.trading_service import MARKET_MAP

logger = get_logger(__name__)


class _OrderPushHandler(TradeOrderHandlerBase):
    def __init__(self, worker):
        super().__init__()
        self.worker = worker

    def on_recv_rsp(self, rsp_pb):
        ret, data = super().on_recv_rsp(rsp_pb)
        if ret != RET_OK:
            return ret, data

        for row in data.to_dict('records'):
            self.worker.on_order_push(row)
        return ret, data


class _DealPushHandler(TradeDealHandlerBase):
    def __init__(self, worker):
        super().__init__()
        self.worker = worker

    def on_recv_rsp(self, rsp_pb):
        ret, data = super().on_recv_rsp(rsp_pb)
        if ret != RET_OK:
            return ret, data

        for row in data.to_dict('records'):
            self.worker.on_deal_push(row)
        return ret, data


class TradePushWorker:
    def __init__(self, trading_service):
        self.trading_service = trading_service
        self._gateways = {}
        self._last_error = None

    def start(self):
        self._last_error = None
        for market in MARKET_MAP.keys():
            if market in {'SH', 'SZ'}:
                continue
            self._ensure_gateway(market)
        logger.info("TradePushWorker started")

    def stop(self):
        for gateway in self._gateways.values():
            try:
                gateway.close()
            except Exception:
                logger.exception("TradePushWorker close failed")
        self._gateways.clear()

    def get_status(self):
        return {
            'running': bool(self._gateways),
            'markets': sorted(self._gateways.keys()),
            'lastError': self._last_error,
        }

    def on_order_push(self, row):
        try:
            self.trading_service.handle_order_push(row)
        except Exception as exc:
            self._last_error = str(exc)
            logger.exception("Trade order push handling failed: %s", exc)

    def on_deal_push(self, row):
        try:
            self.trading_service.handle_deal_push(row)
        except Exception as exc:
            self._last_error = str(exc)
            logger.exception("Trade deal push handling failed: %s", exc)

    def _ensure_gateway(self, market):
        if market in self._gateways:
            return self._gateways[market]

        gateway = FutuTradeGateway(market=MARKET_MAP[market], host=self.trading_service.host, port=self.trading_service.port)
        gateway.set_handler(_OrderPushHandler(self))
        gateway.set_handler(_DealPushHandler(self))
        ret, data = gateway.get_acc_list()
        if ret != RET_OK:
            gateway.close()
            raise RuntimeError(f"TradePushWorker get_acc_list failed for {market}: {data}")
        self._gateways[market] = gateway
        return gateway
