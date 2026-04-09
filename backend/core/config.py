#!/usr/bin/env python3
"""Shared runtime configuration."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / 'backend'
DATA_DIR = BACKEND_DIR / 'data'
LOG_DIR = BACKEND_DIR / 'logs'

DEFAULT_HOST = os.getenv('QTS_OPEND_HOST', '127.0.0.1')
DEFAULT_PORT = int(os.getenv('QTS_OPEND_PORT', '11111'))

STOP_LOSS_PCT = float(os.getenv('QTS_STOP_LOSS_PCT', '-0.20'))
TAKE_PROFIT_PCT = float(os.getenv('QTS_TAKE_PROFIT_PCT', '0.30'))

RUNTIME_DB_PATH = Path(os.getenv('QTS_RUNTIME_DB_PATH', str(DATA_DIR / 'runtime.sqlite3')))
AGENT_TEST_MODE = os.getenv('QTS_AGENT_TEST_MODE', 'true').strip().lower() in {'1', 'true', 'yes', 'on'}
DEFAULT_ACCOUNT_ID = os.getenv('QTS_ACCOUNT_ID', 'default')
RUNTIME_STATE_REFRESH_INTERVAL_SEC = float(os.getenv('QTS_RUNTIME_STATE_REFRESH_INTERVAL_SEC', '1.0'))
GUARDIAN_REFRESH_INTERVAL_SEC = float(os.getenv('QTS_GUARDIAN_REFRESH_INTERVAL_SEC', '5.0'))

LOG_LEVEL = os.getenv('QTS_LOG_LEVEL', 'INFO').upper()
