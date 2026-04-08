#!/usr/bin/env python3
"""FastAPI service for strategy management."""

import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from backend.services.strategy_manager import STRATEGY_METADATA, StrategyManager

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / 'backend'
LOG_DIR = BACKEND_DIR / 'logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)


class StartStrategyRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    strategy_name: str = Field(..., alias='strategyName')
    codes: Optional[List[str]] = None
    short_ma: Optional[int] = Field(None, alias='shortMa')
    long_ma: Optional[int] = Field(None, alias='longMa')
    order_qty: Optional[int] = Field(None, alias='orderQty')
    max_position_per_stock: Optional[int] = Field(None, alias='maxPositionPerStock')


class StrategyRun:
    def __init__(self, run_id: str, strategy_name: str, config: Dict, process: subprocess.Popen, log_path: Path):
        self.run_id = run_id
        self.strategy_name = strategy_name
        self.config = config
        self.process = process
        self.log_path = log_path
        self.created_at = time.time()
        self.stopped_at = None

    def poll_status(self):
        code = self.process.poll()
        if code is None:
            return 'running'
        if self.stopped_at is None:
            self.stopped_at = time.time()
        return 'stopped' if code == 0 else 'failed'

    def to_dict(self):
        return {
            'id': self.run_id,
            'strategyName': self.strategy_name,
            'config': self.config,
            'pid': self.process.pid,
            'status': self.poll_status(),
            'createdAt': self.created_at,
            'stoppedAt': self.stopped_at,
            'logPath': str(self.log_path),
        }


class StrategyRuntime:
    def __init__(self):
        self.manager = StrategyManager()
        self.runs: Dict[str, StrategyRun] = {}
        self.lock = threading.Lock()

    def list_strategies(self):
        return self.manager.list_strategy_definitions()

    def _build_command(self, config: Dict) -> List[str]:
        cmd = ['python3', '-m', 'backend.cli.run_strategy', '--strategy', config['strategy']]
        if config.get('codes'):
            cmd.extend(['--codes', *config['codes']])
        if config.get('short_ma') is not None:
            cmd.extend(['--short-ma', str(config['short_ma'])])
        if config.get('long_ma') is not None:
            cmd.extend(['--long-ma', str(config['long_ma'])])
        if config.get('order_qty') is not None:
            cmd.extend(['--order-qty', str(config['order_qty'])])
        if config.get('max_position_per_stock') is not None:
            cmd.extend(['--max-position-per-stock', str(config['max_position_per_stock'])])
        return cmd

    def start_strategy(self, request: StartStrategyRequest):
        if request.strategy_name not in STRATEGY_METADATA:
            raise HTTPException(status_code=404, detail='Strategy not found')

        config = {
            'strategy': request.strategy_name,
            'codes': request.codes or STRATEGY_METADATA[request.strategy_name]['params'].get('codes'),
            'short_ma': request.short_ma if request.short_ma is not None else STRATEGY_METADATA[request.strategy_name]['params'].get('short_ma'),
            'long_ma': request.long_ma if request.long_ma is not None else STRATEGY_METADATA[request.strategy_name]['params'].get('long_ma'),
            'order_qty': request.order_qty if request.order_qty is not None else STRATEGY_METADATA[request.strategy_name]['params'].get('order_qty'),
            'max_position_per_stock': (
                request.max_position_per_stock
                if request.max_position_per_stock is not None
                else STRATEGY_METADATA[request.strategy_name]['params'].get('max_position_per_stock')
            ),
        }

        run_id = uuid.uuid4().hex[:8]
        log_path = LOG_DIR / f'{run_id}.log'
        log_file = log_path.open('w')
        process = subprocess.Popen(
            self._build_command(config),
            cwd=str(ROOT),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )

        run = StrategyRun(run_id=run_id, strategy_name=request.strategy_name, config=config, process=process, log_path=log_path)
        with self.lock:
            self.runs[run_id] = run
        return run.to_dict()

    def list_runs(self):
        with self.lock:
            return [run.to_dict() for run in self.runs.values()]

    def stop_run(self, run_id: str):
        with self.lock:
            run = self.runs.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail='Run not found')
        if run.process.poll() is not None:
            return run.to_dict()

        run.process.send_signal(signal.SIGINT)
        try:
            run.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            run.process.terminate()
            run.process.wait(timeout=5)
        run.stopped_at = time.time()
        return run.to_dict()

    def read_logs(self, run_id: str, lines: int = 200):
        with self.lock:
            run = self.runs.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail='Run not found')
        if not run.log_path.exists():
            return []
        content = run.log_path.read_text().splitlines()
        return content[-lines:]


runtime = StrategyRuntime()
app = FastAPI(title='Quant Trading Strategy Service')
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.get('/api/health')
def health():
    return {'status': 'ok'}


@app.get('/api/strategies')
def list_strategies():
    return runtime.list_strategies()


@app.get('/api/runs')
def list_runs():
    return runtime.list_runs()


@app.post('/api/runs')
def start_run(request: StartStrategyRequest):
    return runtime.start_strategy(request)


@app.post('/api/runs/{run_id}/stop')
def stop_run(run_id: str):
    return runtime.stop_run(run_id)


@app.get('/api/runs/{run_id}/logs')
def read_logs(run_id: str, lines: int = 200):
    return {'lines': runtime.read_logs(run_id, lines)}
