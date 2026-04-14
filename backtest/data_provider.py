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

    @staticmethod
    def _resolve_ktype(ktype):
        if not isinstance(ktype, str):
            return ktype
        if not hasattr(KLType, ktype):
            raise ValueError(f'未知 K 线类型: {ktype}')
        return getattr(KLType, ktype)

    def fetch_bars(self, code, start, end, ktype=KLType.K_DAY, autype=AuType.QFQ, use_cache=True):
        ktype = self._resolve_ktype(ktype)
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
        ktype = self._resolve_ktype(ktype)
        return {
            code: self.fetch_bars(code, start, end, ktype=ktype, autype=autype, use_cache=use_cache)
            for code in codes
        }

    def fetch_tickers(self, code, start, end, use_cache=True):
        """
        基于假设存在的 get_history_ticker() 拉取历史逐笔。

        假设接口返回格式与 get_rt_ticker() 一致，并支持按时间区间分页读取。
        当前真实 FUTU SDK 未提供该公开历史接口时，这里会显式抛错，避免误以为系统支持真实历史 tick。
        """
        cache_path = self.cache_dir / f"{code.replace('.', '_')}_{start}_{end}_TICK.json"
        if use_cache and cache_path.exists():
            return json.loads(cache_path.read_text())

        quote_ctx = OpenQuoteContext(host=self.host, port=self.port)
        ticks = []
        page_req_key = None

        if not hasattr(quote_ctx, 'get_history_ticker'):
            quote_ctx.close()
            raise NotImplementedError('当前 FUTU 环境未提供 get_history_ticker()，无法拉取历史 tick 数据')

        try:
            while True:
                ret, data, page_req_key = quote_ctx.get_history_ticker(
                    code=code,
                    start=start,
                    end=end,
                    page_req_key=page_req_key,
                    max_count=1000,
                )
                if ret != RET_OK:
                    raise RuntimeError(f'获取历史逐笔失败: {data}')
                ticks.extend(data.to_dict('records'))
                if page_req_key is None:
                    break
        finally:
            quote_ctx.close()

        if use_cache:
            cache_path.write_text(json.dumps(ticks, ensure_ascii=False, indent=2))
        return ticks

    def fetch_many_tickers(self, codes, start, end, use_cache=True):
        return {
            code: self.fetch_tickers(code, start, end, use_cache=use_cache)
            for code in codes
        }
