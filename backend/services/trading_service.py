#!/usr/bin/env python3
"""Trading service for Futu simulated and real order placement."""

from futu import OrderType, RET_OK, TrdEnv, TrdMarket, TrdSide

from backend.core.config import DEFAULT_HOST, DEFAULT_PORT
from backend.integrations.futu.trade_gateway import FutuTradeGateway


MARKET_MAP = {
    'HK': TrdMarket.HK,
}

TRD_ENV_MAP = {
    'SIMULATE': TrdEnv.SIMULATE,
    'REAL': TrdEnv.REAL,
}

TRD_SIDE_MAP = {
    'BUY': TrdSide.BUY,
    'SELL': TrdSide.SELL,
}

ORDER_TYPE_MAP = {
    'NORMAL': OrderType.NORMAL,
}


class TradingService:
    def __init__(self, repository=None, host=DEFAULT_HOST, port=DEFAULT_PORT):
        self.repository = repository
        self.host = host
        self.port = port

    def _make_gateway(self, market: str):
        market_enum = MARKET_MAP.get(market.upper())
        if market_enum is None:
            raise ValueError(f'Unsupported market: {market}')
        return FutuTradeGateway(market=market_enum, host=self.host, port=self.port)

    @staticmethod
    def _rows_to_dicts(data):
        return data.to_dict('records') if hasattr(data, 'to_dict') else data

    def _record_orders(self, rows, market, trd_env, acc_id, run_id=None, source=None, note=None):
        if self.repository is None:
            return rows
        for row in rows:
            order = dict(row)
            order['broker_order_id'] = order.get('order_id')
            order['account_id'] = acc_id
            order['market'] = market
            order['trade_env'] = trd_env
            order['run_id'] = run_id
            order['source'] = source
            order['note'] = note
            self.repository.upsert_trade_order(order)
        return rows

    def list_accounts(self, market='HK'):
        gateway = self._make_gateway(market)
        try:
            ret, data = gateway.get_acc_list()
            if ret != RET_OK:
                raise RuntimeError(str(data))
            return self._rows_to_dicts(data)
        finally:
            gateway.close()

    def list_orders(self, market='HK', trd_env='SIMULATE', acc_id=None, code=None, refresh=True, limit=200):
        gateway = self._make_gateway(market)
        try:
            if acc_id is None:
                ret, acc_list = gateway.get_acc_list()
                if ret != RET_OK:
                    raise RuntimeError(str(acc_list))
                rows = self._rows_to_dicts(acc_list)
                target = next(
                    (item for item in rows if str(item.get('trd_env', '')).upper() == trd_env.upper()),
                    None,
                )
                if target is None:
                    raise RuntimeError(f'No account found for env={trd_env}')
                acc_id = target['acc_id']

            if refresh:
                ret, data = gateway.order_list_query(
                    trd_env=TRD_ENV_MAP[trd_env.upper()],
                    acc_id=acc_id,
                    code=code,
                )
                if ret != RET_OK:
                    raise RuntimeError(str(data))
                rows = self._rows_to_dicts(data)
                self._record_orders(rows, market, trd_env.upper(), acc_id)

            if self.repository is None:
                return rows
            return self.repository.list_trade_orders(
                account_id=acc_id,
                code=code,
                trade_env=trd_env.upper(),
                limit=limit,
            )
        finally:
            gateway.close()

    def place_order(
        self,
        code: str,
        qty: int,
        price: float,
        side='BUY',
        market='HK',
        trd_env='SIMULATE',
        order_type='NORMAL',
        acc_id=None,
        run_id=None,
        source='manual',
        note=None,
    ):
        side_enum = TRD_SIDE_MAP.get(side.upper())
        if side_enum is None:
            raise ValueError(f'Unsupported side: {side}')

        env_enum = TRD_ENV_MAP.get(trd_env.upper())
        if env_enum is None:
            raise ValueError(f'Unsupported trade env: {trd_env}')

        order_type_enum = ORDER_TYPE_MAP.get(order_type.upper())
        if order_type_enum is None:
            raise ValueError(f'Unsupported order type: {order_type}')

        gateway = self._make_gateway(market)
        try:
            if acc_id is None:
                ret, acc_list = gateway.get_acc_list()
                if ret != RET_OK:
                    raise RuntimeError(str(acc_list))
                rows = self._rows_to_dicts(acc_list)
                target = next(
                    (
                        item for item in rows
                        if str(item.get('trd_env', '')).upper() == trd_env.upper()
                        and str(item.get('trdmarket_auth', market)).upper().find(market.upper()) >= 0
                    ),
                    None,
                )
                if target is None:
                    # Fall back to the first account with matching trade env.
                    target = next(
                        (item for item in rows if str(item.get('trd_env', '')).upper() == trd_env.upper()),
                        None,
                    )
                if target is None:
                    raise RuntimeError(f'No account found for env={trd_env} market={market}')
                acc_id = target['acc_id']

            ret, data = gateway.place_order(
                price=price,
                qty=qty,
                code=code,
                trd_side=side_enum,
                order_type=order_type_enum,
                trd_env=env_enum,
                acc_id=acc_id,
            )
            if ret != RET_OK:
                raise RuntimeError(str(data))
            rows = self._rows_to_dicts(data)
            self._record_orders(rows, market, trd_env.upper(), acc_id, run_id=run_id, source=source, note=note)
            return rows[0] if rows else {}
        finally:
            gateway.close()
