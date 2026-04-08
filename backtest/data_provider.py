#!/usr/bin/env python3
"""
历史 K 线数据提供器。
"""

import json
from pathlib import Path

from futu import AuType, KLType, OpenQuoteContext, RET_OK


class FutuHistoryDataProvider:
    def __init__(self, host='127.0.0.1', port=11111, cache_dir=None):
        self.host = host
        self.port = port
        self.cache_dir = Path(cache_dir or Path(__file__).resolve().parent / 'cache')
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, code, start, end, ktype, autype):
        safe_code = code.replace('.', '_')
        return self.cache_dir / f'{safe_code}_{start}_{end}_{ktype}_{autype}.json'

    def fetch_bars(self, code, start, end, ktype=KLType.K_DAY, autype=AuType.QFQ, use_cache=True):
        cache_path = self._cache_path(code, start, end, ktype, autype)
        if use_cache and cache_path.exists():
            return json.loads(cache_path.read_text())

        quote_ctx = OpenQuoteContext(host=self.host, port=self.port)
        bars = []
        page_req_key = None

        try:
            while True:
                ret, data, page_req_key = quote_ctx.request_history_kline(
                    code=code,
                    start=start,
                    end=end,
                    ktype=ktype,
                    autype=autype,
                    page_req_key=page_req_key,
                    max_count=1000,
                )
                if ret != RET_OK:
                    raise RuntimeError(f'获取历史K线失败: {data}')
                bars.extend(data.to_dict('records'))
                if page_req_key is None:
                    break
        finally:
            quote_ctx.close()

        if use_cache:
            cache_path.write_text(json.dumps(bars, ensure_ascii=False, indent=2))
        return bars

    def fetch_many(self, codes, start, end, ktype=KLType.K_DAY, autype=AuType.QFQ, use_cache=True):
        return {
            code: self.fetch_bars(code, start, end, ktype=ktype, autype=autype, use_cache=use_cache)
            for code in codes
        }
