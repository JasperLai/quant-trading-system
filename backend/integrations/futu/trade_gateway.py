#!/usr/bin/env python3
"""Futu OpenD 交易接入层。"""

from futu import OpenSecTradeContext, TrdMarket


class FutuTradeGateway:
    """封装当前项目用到的 OpenD 交易接口。"""

    def __init__(self, market=TrdMarket.HK, host='127.0.0.1', port=11111):
        self.market = market
        self.host = host
        self.port = port
        self.trade_ctx = OpenSecTradeContext(filter_trdmarket=market, host=host, port=port)

    def get_acc_list(self):
        return self.trade_ctx.get_acc_list()

    def set_handler(self, handler):
        return self.trade_ctx.set_handler(handler)

    def accinfo_query(self, **kwargs):
        return self.trade_ctx.accinfo_query(**kwargs)

    def position_list_query(self, **kwargs):
        return self.trade_ctx.position_list_query(**kwargs)

    def order_list_query(self, **kwargs):
        return self.trade_ctx.order_list_query(**kwargs)

    def deal_list_query(self, **kwargs):
        return self.trade_ctx.deal_list_query(**kwargs)

    def place_order(self, **kwargs):
        return self.trade_ctx.place_order(**kwargs)

    def close(self):
        self.trade_ctx.close()
