#!/usr/bin/env python3
"""Trading service for Futu simulated and real order placement."""

from typing import Optional

from futu import OrderType, RET_OK, Session, TimeInForce, TrailType, TrdEnv, TrdMarket, TrdSide

from backend.core.config import DEFAULT_ACCOUNT_ID
from backend.core.config import DEFAULT_HOST, DEFAULT_PORT
from backend.integrations.futu.trade_gateway import FutuTradeGateway


MARKET_MAP = {
    'HK': TrdMarket.HK,
    'US': TrdMarket.US,
    'CN': TrdMarket.CN,
    'SH': TrdMarket.CN,
    'SZ': TrdMarket.CN,
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
    name: getattr(OrderType, name)
    for name in dir(OrderType)
    if name.isupper() and name != 'NONE'
}

TIME_IN_FORCE_MAP = {
    name: getattr(TimeInForce, name)
    for name in dir(TimeInForce)
    if name.isupper()
}

SESSION_MAP = {
    name: getattr(Session, name)
    for name in dir(Session)
    if name.isupper()
}

TRAIL_TYPE_MAP = {
    name: getattr(TrailType, name)
    for name in dir(TrailType)
    if name.isupper()
}


class TradingService:
    def __init__(self, repository=None, position_service=None, host=DEFAULT_HOST, port=DEFAULT_PORT):
        self.repository = repository
        self.position_service = position_service
        self.host = host
        self.port = port

    def _make_gateway(self, market: str):
        market_enum = MARKET_MAP.get(market.upper())
        if market_enum is None:
            raise ValueError(f'Unsupported market: {market}')
        return FutuTradeGateway(market=market_enum, host=self.host, port=self.port)

    @staticmethod
    def normalize_market(market: str, code: Optional[str] = None):
        if market:
            return market.upper()
        if code and '.' in code:
            prefix = code.split('.', 1)[0].upper()
            if prefix in {'HK', 'US', 'SH', 'SZ', 'CN'}:
                return prefix
        return 'HK'

    @staticmethod
    def _rows_to_dicts(data):
        return data.to_dict('records') if hasattr(data, 'to_dict') else data

    def _record_orders(self, rows, market, trd_env, acc_id=None, run_id=None, source=None, note=None):
        if self.repository is None:
            return rows
        for row in rows:
            existing = self.repository.get_trade_order(row.get('order_id'))
            order = dict(row)
            order['broker_order_id'] = order.get('order_id')
            order['account_id'] = acc_id if acc_id is not None else (existing.get('account_id') if existing else None)
            order['market'] = market
            order['trade_env'] = trd_env
            order['run_id'] = run_id if run_id is not None else (existing.get('run_id') if existing else None)
            order['source'] = source if source is not None else (existing.get('source') if existing else None)
            order['note'] = note if note is not None else (existing.get('note') if existing else None)
            order['settled_qty'] = existing.get('settled_qty', 0) if existing else 0
            order['settlement_status'] = existing.get('settlement_status') if existing else None
            order['settled_at'] = existing.get('settled_at') if existing else None
            self.repository.upsert_trade_order(order)
        return rows

    @staticmethod
    def _normalize_push_market(row):
        market = row.get('market') or row.get('trd_market') or row.get('order_market')
        return str(market).upper() if market is not None else 'HK'

    @staticmethod
    def _normalize_push_env(row):
        env = row.get('trade_env') or row.get('trd_env')
        return str(env).upper() if env is not None else 'SIMULATE'

    def _auto_settle_order(self, row):
        if self.repository is None or self.position_service is None:
            return

        broker_order_id = row.get('order_id')
        stored = self.repository.get_trade_order(broker_order_id)
        if stored is None:
            return

        dealt_qty = float(row.get('dealt_qty') or 0)
        settled_qty = float(stored.get('settled_qty') or 0)
        delta_qty = dealt_qty - settled_qty
        if delta_qty <= 0:
            if str(row.get('order_status', '')).upper() in {'CANCELLED_ALL', 'CANCELLED_PART', 'FAILED', 'SUBMIT_FAILED'}:
                self.repository.mark_trade_order_settled(broker_order_id, settled_qty, settlement_status='CLOSED_NO_FILL')
            return

        dealt_avg_price = float(row.get('dealt_avg_price') or row.get('price') or 0)
        source = stored.get('source')
        run_id = stored.get('run_id')
        side = str(row.get('trd_side', '')).upper()
        note = stored.get('note') or f'broker_order_id={broker_order_id}'

        if side == 'BUY' and run_id:
            self.position_service.confirm_position(
                run_id=run_id,
                code=row['code'],
                qty=delta_qty,
                entry_price=dealt_avg_price,
                reason=note,
                account_id=stored.get('account_id') or DEFAULT_ACCOUNT_ID,
            )
            self.repository.mark_trade_order_settled(broker_order_id, dealt_qty, settlement_status='SETTLED')
            return

        if side == 'SELL':
            if source == 'guardian':
                self.position_service.confirm_account_exit(
                    code=row['code'],
                    qty=delta_qty,
                    exit_price=dealt_avg_price,
                    reason=note,
                    account_id=stored.get('account_id') or DEFAULT_ACCOUNT_ID,
                )
                self.repository.mark_trade_order_settled(broker_order_id, dealt_qty, settlement_status='SETTLED')
                return
            if run_id:
                self.position_service.confirm_exit(
                    run_id=run_id,
                    code=row['code'],
                    qty=delta_qty,
                    exit_price=dealt_avg_price,
                    reason=note,
                    account_id=stored.get('account_id') or DEFAULT_ACCOUNT_ID,
                )
                self.repository.mark_trade_order_settled(broker_order_id, dealt_qty, settlement_status='SETTLED')
                return

    def _auto_settle_deal(self, row):
        if self.repository is None or self.position_service is None:
            return

        deal_id = row.get('deal_id')
        if self.repository.get_trade_deal(deal_id) is not None:
            return

        broker_order_id = row.get('order_id')
        stored = self.repository.get_trade_order(broker_order_id)
        if stored is None:
            return

        deal_qty = float(row.get('qty') or 0)
        if deal_qty <= 0:
            return

        deal_price = float(row.get('price') or stored.get('dealt_avg_price') or stored.get('price') or 0)
        side = str(row.get('trd_side', '')).upper()
        note = stored.get('note') or f'broker_order_id={broker_order_id}'
        source = stored.get('source')
        run_id = stored.get('run_id')

        deal_record = dict(row)
        deal_record['market'] = stored.get('market')
        deal_record['trade_env'] = stored.get('trade_env')
        deal_record['account_id'] = stored.get('account_id')
        self.repository.upsert_trade_deal(deal_record)

        if side == 'BUY' and run_id:
            self.position_service.confirm_position(
                run_id=run_id,
                code=row['code'],
                qty=deal_qty,
                entry_price=deal_price,
                reason=note,
                account_id=stored.get('account_id') or DEFAULT_ACCOUNT_ID,
            )
        elif side == 'SELL':
            if source == 'guardian':
                self.position_service.confirm_account_exit(
                    code=row['code'],
                    qty=deal_qty,
                    exit_price=deal_price,
                    reason=note,
                    account_id=stored.get('account_id') or DEFAULT_ACCOUNT_ID,
                )
            elif run_id:
                self.position_service.confirm_exit(
                    run_id=run_id,
                    code=row['code'],
                    qty=deal_qty,
                    exit_price=deal_price,
                    reason=note,
                    account_id=stored.get('account_id') or DEFAULT_ACCOUNT_ID,
                )

        new_settled_qty = float(stored.get('settled_qty') or 0) + deal_qty
        order_status = str(stored.get('order_status') or '').upper()
        settlement_status = 'SETTLED' if order_status == 'FILLED_ALL' else 'PARTIALLY_SETTLED'
        self.repository.mark_trade_order_settled(
            broker_order_id,
            new_settled_qty,
            settlement_status=settlement_status,
        )

    def handle_order_push(self, row):
        market = self._normalize_push_market(row)
        trd_env = self._normalize_push_env(row)
        self._record_orders([row], market, trd_env, acc_id=None)
        self._auto_settle_order(row)

    def handle_deal_push(self, row):
        self._auto_settle_deal(row)

    def sync_unsettled_orders(self, limit=200):
        if self.repository is None:
            return []

        pending = self.repository.list_unsettled_trade_orders(limit=limit)
        refreshed = []
        seen_keys = set()

        for order in pending:
            key = (
                order.get('market'),
                order.get('trade_env'),
                order.get('account_id'),
                order.get('code'),
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            refreshed.extend(
                self.list_orders(
                    market=order.get('market') or 'HK',
                    trd_env=order.get('trade_env') or 'SIMULATE',
                    acc_id=int(order['account_id']) if order.get('account_id') is not None else None,
                    code=order.get('code'),
                    refresh=True,
                    limit=limit,
                )
            )

        return refreshed

    def list_accounts(self, market='HK'):
        market = self.normalize_market(market)
        gateway = self._make_gateway(market)
        try:
            ret, data = gateway.get_acc_list()
            if ret != RET_OK:
                raise RuntimeError(str(data))
            return self._rows_to_dicts(data)
        finally:
            gateway.close()

    def list_orders(self, market='HK', trd_env='SIMULATE', acc_id=None, code=None, refresh=True, limit=200):
        market = self.normalize_market(market, code=code)
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
                for row in rows:
                    self._auto_settle_order(row)

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

    def list_deals(self, market='HK', trd_env='SIMULATE', acc_id=None, code=None, refresh=True, limit=200):
        market = self.normalize_market(market, code=code)
        gateway = self._make_gateway(market)
        rows = []
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
                ret, data = gateway.deal_list_query(
                    trd_env=TRD_ENV_MAP[trd_env.upper()],
                    acc_id=acc_id,
                    code=code,
                )
                if ret != RET_OK:
                    # Futu 模拟环境不支持成交列表查询，前端刷新时回退到本地已审计成交。
                    if trd_env.upper() == 'SIMULATE' and '不支持成交数据' in str(data):
                        data = []
                    else:
                        raise RuntimeError(str(data))
                rows = self._rows_to_dicts(data)
                for row in rows:
                    enriched = dict(row)
                    enriched['market'] = market
                    enriched['trade_env'] = trd_env.upper()
                    enriched['account_id'] = acc_id
                    self.repository.upsert_trade_deal(enriched)

            if self.repository is None:
                return rows
            return self.repository.list_trade_deals(
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
        time_in_force='DAY',
        fill_outside_rth=False,
        session='NONE',
        aux_price=None,
        trail_type='NONE',
        trail_value=None,
        trail_spread=None,
        acc_id=None,
        run_id=None,
        source='manual',
        note=None,
    ):
        market = self.normalize_market(market, code=code)
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
                time_in_force=TIME_IN_FORCE_MAP.get((time_in_force or 'DAY').upper(), TimeInForce.DAY),
                fill_outside_rth=bool(fill_outside_rth),
                session=SESSION_MAP.get((session or 'NONE').upper(), Session.NONE),
                aux_price=aux_price,
                trail_type=TRAIL_TYPE_MAP.get((trail_type or 'NONE').upper(), TrailType.NONE),
                trail_value=trail_value,
                trail_spread=trail_spread,
                remark=note,
            )
            if ret != RET_OK:
                raise RuntimeError(str(data))
            rows = self._rows_to_dicts(data)
            self._record_orders(rows, market, trd_env.upper(), acc_id, run_id=run_id, source=source, note=note)
            for row in rows:
                self._auto_settle_order(row)
            return rows[0] if rows else {}
        finally:
            gateway.close()
