#!/usr/bin/env python3
"""FastAPI service for strategy management."""

import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from backend.core.config import LOG_DIR, RUNTIME_DB_PATH
from backend.core.logging import get_logger
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from backend.monitoring.guardian import PositionGuardian
from backend.repositories.runtime_repository import RuntimeRepository
from backend.services.position_service import PositionService
from backend.services.strategy_manager import STRATEGY_METADATA, StrategyManager

ROOT = Path(__file__).resolve().parents[2]
LOG_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = RUNTIME_DB_PATH
logger = get_logger(__name__)


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
        self.position_service = PositionService(self.repository)
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
        logger.info("启动策略实例: run_id=%s strategy=%s pid=%s", run_id, request.strategy_name, process.pid)
        return run.to_dict()

    def list_runs(self):
        runs = self.repository.list_runs()
        with self.lock:
            active_runs = dict(self.runs)
        for run in runs:
            process = active_runs.get(run['id'])
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
            'positions': self.repository.list_strategy_positions(run_id),
            'strategyPositions': self.repository.list_strategy_positions(run_id),
            'accountPositions': self.repository.list_account_positions(self.position_service.account_id),
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
        logger.info("停止策略实例: run_id=%s", run_id)
        return run.to_dict()

    def confirm_buy(self, run_id: str, request: ConfirmBuyRequest):
        db_run = self.repository.get_run(run_id)
        if db_run is None:
            raise HTTPException(status_code=404, detail='Run not found')
        position = self.position_service.confirm_position(
            run_id=run_id,
            code=request.code,
            qty=request.qty,
            entry_price=request.entry_price,
            stop_loss=request.stop_loss,
            take_profit=request.take_profit,
            reason=request.reason,
        )
        logger.info("确认买入并落库: run_id=%s code=%s qty=%s", run_id, request.code, request.qty)
        return {'status': 'applied', 'runId': run_id, 'position': position}

    def confirm_sell(self, run_id: str, request: ConfirmSellRequest):
        db_run = self.repository.get_run(run_id)
        if db_run is None:
            raise HTTPException(status_code=404, detail='Run not found')
        remaining = self.position_service.confirm_exit(
            run_id=run_id,
            code=request.code,
            qty=request.qty,
            exit_price=request.exit_price,
            reason=request.reason,
        )
        logger.info("确认卖出并落库: run_id=%s code=%s qty=%s", run_id, request.code, request.qty)
        return {'status': 'applied', 'runId': run_id, 'remainingQty': remaining}

    def confirm_account_sell(self, account_id: str, request: ConfirmSellRequest):
        result = self.position_service.confirm_account_exit(
            account_id=account_id,
            code=request.code,
            qty=request.qty,
            exit_price=request.exit_price,
            reason=request.reason,
        )
        logger.info("确认账户级卖出并落库: account_id=%s code=%s qty=%s", account_id, request.code, request.qty)
        return {'status': 'applied', 'accountId': account_id, **result}

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


@app.on_event('startup')
def startup_guardian():
    app.state.guardian = PositionGuardian(runtime.repository)
    app.state.guardian.start()


@app.on_event('shutdown')
def shutdown_guardian():
    guardian_instance = getattr(app.state, 'guardian', None)
    if guardian_instance is not None:
        guardian_instance.stop()


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


@app.post('/api/accounts/{account_id}/confirm-sell')
def confirm_account_sell(account_id: str, request: ConfirmSellRequest):
    return runtime.confirm_account_sell(account_id, request)
