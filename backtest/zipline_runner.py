#!/usr/bin/env python3
"""Zipline backend 运行器。"""

import runpy
from pathlib import Path

import pandas as pd

from backtest.zipline_bundle import ZiplineBundleAdapter, require_zipline
from backtest.zipline_result_adapter import adapt_zipline_result
from backtest.zipline_strategy_adapter import ZiplineStrategyAdapter


class ZiplineBacktestRunner:
    def __init__(
        self,
        signal,
        strategy_name,
        initial_cash=100000.0,
        commission_rate=0.001,
        slippage=0.0,
        cache_root=None,
    ):
        self.signal = signal
        self.strategy_name = strategy_name
        self.initial_cash = initial_cash
        self.commission_rate = commission_rate
        self.slippage = slippage
        self.bundle_adapter = ZiplineBundleAdapter(cache_root=cache_root)

    @staticmethod
    def _resolve_frequency(engine_name):
        if engine_name == 'minute':
            return 'minute'
        if engine_name == 'daily':
            return 'daily'
        raise ValueError(f'zipline backend 当前只支持 daily/minute，引擎收到: {engine_name}')

    @staticmethod
    def _build_timestamps(start, end):
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        if start_ts.tzinfo is None:
            start_ts = start_ts.tz_localize('UTC')
        if end_ts.tzinfo is None:
            end_ts = end_ts.tz_localize('UTC')
        return start_ts, end_ts

    def run(self, bars_by_code, start, end, engine_name):
        require_zipline()
        from zipline import run_algorithm

        frequency = self._resolve_frequency(engine_name)
        prepared_bundle = self.bundle_adapter.prepare_bundle(
            strategy_name=self.strategy_name,
            bars_by_code=bars_by_code,
            start=start,
            end=end,
            frequency=frequency,
        )
        runpy.run_path(prepared_bundle.extension_path)

        adapter = ZiplineStrategyAdapter(
            signal=self.signal,
            prepared_bundle=prepared_bundle,
            data_frequency=frequency,
            commission_rate=self.commission_rate,
            slippage=self.slippage,
        )
        start_ts, end_ts = self._build_timestamps(start, end)
        perf = run_algorithm(
            start=start_ts,
            end=end_ts,
            initialize=adapter.initialize,
            handle_data=adapter.handle_data,
            capital_base=self.initial_cash,
            data_frequency=frequency,
            bundle=prepared_bundle.bundle_name,
        )
        return adapt_zipline_result(
            perf=perf,
            prepared_bundle=prepared_bundle,
            strategy_name=self.strategy_name,
            initial_cash=self.initial_cash,
        )
