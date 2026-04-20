#!/usr/bin/env python3
"""Zipline bundle 适配器。"""

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict

import pandas as pd


def require_zipline():
    try:
        __import__('zipline')
    except ImportError as exc:
        raise RuntimeError(
            '当前环境未安装 zipline-reloaded，无法使用 zipline 回测 backend。'
            ' 本机安装还依赖 HDF5/tables，可先按文档补环境后再启用。'
        ) from exc
    except Exception as exc:
        raise RuntimeError(
            '当前环境存在 Zipline 依赖，但运行时加载失败。'
            ' 常见原因是 trading_calendars / pandas / numpy 版本不兼容。'
            f' 原始错误: {exc}'
        ) from exc


def _market_from_code(code: str) -> str:
    if code.startswith('HK.'):
        return 'HK'
    if code.startswith('US.'):
        return 'US'
    if code.startswith('SH.') or code.startswith('SZ.') or code.startswith('CN.'):
        return 'CN'
    return 'UNKNOWN'


def infer_calendar_name(codes):
    markets = {_market_from_code(code) for code in codes}
    if len(markets) != 1:
        raise ValueError(f'zipline backend 当前只支持同一市场回测，收到 markets={sorted(markets)}')
    market = next(iter(markets))
    if market == 'HK':
        return 'XHKG'
    if market == 'US':
        return 'XNYS'
    if market == 'CN':
        return 'XSHG'
    raise ValueError(f'无法为标的推断 Zipline calendar: {sorted(codes)}')


def to_zipline_symbol(code: str) -> str:
    return code.replace('.', '_').replace('-', '_').upper()


@dataclass
class PreparedZiplineBundle:
    bundle_name: str
    frequency: str
    calendar_name: str
    bundle_root: str
    csv_root: str
    extension_path: str
    metadata_path: str
    symbol_map: Dict[str, str]
    sid_map: Dict[int, str]

    def to_dict(self):
        return asdict(self)


class ZiplineBundleAdapter:
    """把当前项目历史 bars 转换成 Zipline csvdir bundle 所需目录结构。"""

    def __init__(self, cache_root=None):
        default_root = Path(__file__).resolve().parent / 'cache' / 'zipline'
        self.cache_root = Path(cache_root or default_root)
        self.cache_root.mkdir(parents=True, exist_ok=True)

    def _bundle_name(self, strategy_name, frequency, start, end, codes):
        digest = hashlib.sha1('|'.join([strategy_name, frequency, start, end, *sorted(codes)]).encode('utf-8')).hexdigest()[:12]
        return f'qts_{strategy_name}_{frequency}_{digest}'

    @staticmethod
    def _normalize_frame(bars, frequency):
        frame = pd.DataFrame(bars).copy()
        if frame.empty:
            raise ValueError('zipline backend 收到空历史数据，无法构建 bundle')

        frame['date'] = pd.to_datetime(frame['time_key'])
        for column in ['open', 'high', 'low', 'close', 'volume']:
            if column not in frame:
                if column == 'volume':
                    frame[column] = 0
                else:
                    frame[column] = frame['close']
        frame['volume'] = frame['volume'].fillna(0)
        frame['dividend'] = 0.0
        frame['split'] = 1.0
        frame = frame[['date', 'open', 'high', 'low', 'close', 'volume', 'dividend', 'split']].sort_values('date')
        if frequency == 'daily':
            frame['date'] = frame['date'].dt.normalize()
        return frame

    def prepare_bundle(self, strategy_name, bars_by_code, start, end, frequency):
        require_zipline()
        codes = sorted(bars_by_code.keys())
        bundle_name = self._bundle_name(strategy_name, frequency, start, end, codes)
        calendar_name = infer_calendar_name(codes)
        bundle_root = self.cache_root / bundle_name
        csv_root = bundle_root / 'csvdir'
        freq_dir = csv_root / frequency
        freq_dir.mkdir(parents=True, exist_ok=True)

        symbol_map = {}
        sid_map = {}
        assets = []
        for sid, code in enumerate(codes, start=1):
            zipline_symbol = to_zipline_symbol(code)
            symbol_map[code] = zipline_symbol
            sid_map[sid] = code
            frame = self._normalize_frame(bars_by_code[code], frequency)
            frame.to_csv(freq_dir / f'{zipline_symbol}.csv', index=False)
            assets.append(
                {
                    'sid': sid,
                    'code': code,
                    'symbol': zipline_symbol,
                    'start': frame['date'].min().isoformat(),
                    'end': frame['date'].max().isoformat(),
                }
            )

        metadata = {
            'bundle_name': bundle_name,
            'frequency': frequency,
            'calendar_name': calendar_name,
            'symbol_map': symbol_map,
            'sid_map': sid_map,
            'assets': assets,
        }
        metadata_path = bundle_root / 'metadata.json'
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2))

        extension_path = bundle_root / 'extension.py'
        extension_path.write_text(
            '\n'.join(
                [
                    'from zipline.data.bundles import register',
                    'from zipline.data.bundles.csvdir import csvdir_equities',
                    '',
                    f"BUNDLE_NAME = '{bundle_name}'",
                    f"CSV_ROOT = r'{csv_root}'",
                    f"CALENDAR_NAME = '{calendar_name}'",
                    f"register(BUNDLE_NAME, csvdir_equities(['{frequency}'], CSV_ROOT), calendar_name=CALENDAR_NAME)",
                    '',
                ]
            )
        )

        return PreparedZiplineBundle(
            bundle_name=bundle_name,
            frequency=frequency,
            calendar_name=calendar_name,
            bundle_root=str(bundle_root),
            csv_root=str(csv_root),
            extension_path=str(extension_path),
            metadata_path=str(metadata_path),
            symbol_map=symbol_map,
            sid_map=sid_map,
        )
