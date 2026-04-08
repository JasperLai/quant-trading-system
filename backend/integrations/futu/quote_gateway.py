#!/usr/bin/env python3
"""Futu OpenD 行情接入层。"""

from futu import KLType, OpenQuoteContext, RET_OK, SubType


class FutuQuoteGateway:
    """封装实时策略当前用到的 OpenD 行情接口。"""

    def __init__(self, host='127.0.0.1', port=11111):
        self.host = host
        self.port = port
        self.quote_ctx = OpenQuoteContext(host=host, port=port)

    def get_global_state(self):
        return self.quote_ctx.get_global_state()

    def set_handler(self, handler):
        return self.quote_ctx.set_handler(handler)

    def subscribe_daily_bars(self, codes):
        return self.quote_ctx.subscribe(codes, [SubType.K_DAY], subscribe_push=False)

    def subscribe_quotes(self, codes):
        return self.quote_ctx.subscribe(codes, [SubType.QUOTE])

    def get_daily_bars(self, code, count):
        return self.quote_ctx.get_cur_kline(code, count, KLType.K_DAY)

    def stop(self):
        self.quote_ctx.stop()
        self.quote_ctx.close()

    @property
    def context(self):
        return self.quote_ctx
