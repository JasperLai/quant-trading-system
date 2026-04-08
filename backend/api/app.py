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

from backend.repositories.runtime_repository import RuntimeRepository
from backend.services.strategy_manager import STRATEGY_METADATA, StrategyManager

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / 'backend'
LOG_DIR = BACKEND_DIR / 'logs'
DB_PATH = BACKEND_DIR / 'data' / 'runtime.sqlite3'
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


class ConfirmBuyRequest(BaseModel):
    code: str
    qty: int
    entry_price: float = Field(..., alias='entryPrice')
    stop_loss: Optional[float] = Field(None, alias='stopLoss')
    take_profit: Optional[float] = Field(None, alias='takeProfit')
    reason: Optional[str] = '均线金叉买入'


class ConfirmSellRequest(BaseModel):
    code: str
    qty: Optional[int] = None
    exit_price: Optional[float] = Field(None, alias='exitPrice')
    reason: Optional[str] = '均线死叉卖出'


class StrategyRuntime:
    def __init__(self):
        self.manager = StrategyManager()
        self.repository = RuntimeRepository(db_path=DB_PATH)
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
        if config.get('run_id') is not None:
            cmd.extend(['--run-id', config['run_id']])
        if config.get('db_path') is not None:
            cmd.extend(['--db-path', config['db_path']])
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
        config['run_id'] = run_id
        config['db_path'] = str(DB_PATH)
        log_file = log_path.open('w')
        process = subprocess.Popen(
            self._build_command(config),
            cwd=str(ROOT),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )

        run = StrategyRun(
            run_id=run_id,
            strategy_name=request.strategy_name,
            config=config,
            process=process,
            log_path=log_path,
        )
        with self.lock:
            self.runs[run_id] = run
        self.repository.upsert_run(
            run_id=run_id,
            strategy_name=request.strategy_name,
            config=config,
            pid=process.pid,
            status='running',
            created_at=run.created_at,
            log_path=str(log_path),
        )
        return run.to_dict()

    def list_runs(self):
        runs = self.repository.list_runs()
        for run in runs:
            process = self.runs.get(run['id'])
            if process is not None and process.process.poll() is None:
                run['pid'] = process.process.pid
                run['status'] = 'running'
        return runs

    def get_run_state(self, run_id: str):
        run = self.repository.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail='Run not found')
        return {
            'run': run,
            'positions': self.repository.list_positions(run_id),
            'pendingOrders': self.repository.list_pending_orders(run_id),
            'executions': self.repository.list_executions(run_id),
        }

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
        self.repository.update_run_status(run_id, 'stopped', stopped_at=run.stopped_at)
        return run.to_dict()

    def _append_command(self, run_id: str, action: str, payload: Dict):
        with self.lock:
            run = self.runs.get(run_id)
        if run is None:
            db_run = self.repository.get_run(run_id)
            if db_run is None:
                raise HTTPException(status_code=404, detail='Run not found')
            raise HTTPException(status_code=409, detail='Run is not active')
        if run.process.poll() is not None:
            raise HTTPException(status_code=409, detail='Run is not active')
        self.repository.enqueue_command(run_id, action, payload)
        return {'status': 'queued', 'runId': run_id, 'command': payload}

    def confirm_buy(self, run_id: str, request: ConfirmBuyRequest):
        payload = {
            'action': 'confirm_buy',
            'code': request.code,
            'qty': request.qty,
            'entry_price': request.entry_price,
            'stop_loss': request.stop_loss,
            'take_profit': request.take_profit,
            'reason': request.reason,
        }
        return self._append_command(run_id, 'confirm_buy', payload)

    def confirm_sell(self, run_id: str, request: ConfirmSellRequest):
        payload = {
            'action': 'confirm_sell',
            'code': request.code,
            'qty': request.qty,
            'exit_price': request.exit_price,
            'reason': request.reason,
        }
        return self._append_command(run_id, 'confirm_sell', payload)

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


@app.get('/api/runs/{run_id}/state')
def get_run_state(run_id: str):
    return runtime.get_run_state(run_id)


@app.post('/api/runs')
def start_run(request: StartStrategyRequest):
    return runtime.start_strategy(request)


@app.post('/api/runs/{run_id}/stop')
def stop_run(run_id: str):
    return runtime.stop_run(run_id)


@app.get('/api/runs/{run_id}/logs')
def read_logs(run_id: str, lines: int = 200):
    return {'lines': runtime.read_logs(run_id, lines)}


@app.post('/api/runs/{run_id}/confirm-buy')
def confirm_buy(run_id: str, request: ConfirmBuyRequest):
    return runtime.confirm_buy(run_id, request)


@app.post('/api/runs/{run_id}/confirm-sell')
def confirm_sell(run_id: str, request: ConfirmSellRequest):
    return runtime.confirm_sell(run_id, request)
