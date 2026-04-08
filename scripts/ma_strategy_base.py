#!/usr/bin/env python3
"""
兼容层。

历史上这里承载了完整的实时策略逻辑。
现在保留为兼容导出，真实实现已拆分为：
1. ma_signal.py: 纯策略信号层
2. realtime_strategy_runner.py: OpenD 实时运行适配层
"""

from ma_signal import BaseMaSignal, PyramidingMaSignal, SinglePositionMaSignal
from realtime_strategy_runner import QuoteHandler, RealtimeMaStrategyRunner

__all__ = [
    'BaseMaSignal',
    'SinglePositionMaSignal',
    'PyramidingMaSignal',
    'QuoteHandler',
    'RealtimeMaStrategyRunner',
]
