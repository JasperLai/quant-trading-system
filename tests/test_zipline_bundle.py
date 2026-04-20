#!/usr/bin/env python3

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backtest.zipline_bundle import ZiplineBundleAdapter
from backtest.zipline_runner import ZiplineBacktestRunner


SAMPLE_BARS = {
    'HK.03690': [
        {
            'time_key': '2026-04-10 09:31:00',
            'open': 88.1,
            'high': 88.6,
            'low': 87.9,
            'close': 88.4,
            'volume': 1000,
        },
        {
            'time_key': '2026-04-10 09:32:00',
            'open': 88.4,
            'high': 88.7,
            'low': 88.2,
            'close': 88.5,
            'volume': 1200,
        },
    ]
}


class ZiplineBundleTests(unittest.TestCase):
    def test_prepare_bundle_writes_csvdir_structure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = ZiplineBundleAdapter(cache_root=temp_dir)
            with patch('backtest.zipline_bundle.require_zipline', return_value=None):
                prepared = adapter.prepare_bundle(
                    strategy_name='intraday_breakout_test',
                    bars_by_code=SAMPLE_BARS,
                    start='2026-04-10',
                    end='2026-04-10',
                    frequency='minute',
                )

            bundle_root = Path(prepared.bundle_root)
            csv_path = bundle_root / 'csvdir' / 'minute' / 'HK_03690.csv'
            self.assertTrue(csv_path.exists())
            self.assertTrue(Path(prepared.extension_path).exists())
            metadata = json.loads(Path(prepared.metadata_path).read_text())
            self.assertEqual(metadata['calendar_name'], 'XHKG')
            self.assertEqual(metadata['symbol_map']['HK.03690'], 'HK_03690')

    def test_zipline_runner_rejects_tick_backend(self):
        runner = ZiplineBacktestRunner(
            signal=object(),
            strategy_name='intraday_breakout_test',
        )
        with self.assertRaises(ValueError):
            runner._resolve_frequency('tick')


if __name__ == '__main__':
    unittest.main()
