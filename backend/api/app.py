#!/usr/bin/env python3
"""FastAPI service for strategy management."""

import os
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from backtest.replay_validation import run_replay_validation
from backend.core.config import LOG_DIR, RUNTIME_DB_PATH
from backend.core.logging import get_logger
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from backend.monitoring.guardian import PositionGuardian
from backend.monitoring.order_sync import OrderSyncWorker
from backend.monitoring.trade_push import TradePushWorker
from backend.repositories.runtime_repository import RuntimeRepository
from backend.services.position_service import PositionService
from backend.services.strategy_manager import STRATEGY_METADATA, StrategyManager
from backend.services.trading_service import TradingService

ROOT = Path(__file__).resolve().parents[2]
LOG_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = RUNTIME_DB_PATH
logger = get_logger(__name__)


class StartStrategyRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    strategy_name: str = Field(..., alias='strategyName')
    strategy_params: Dict[str, Any] = Field(default_factory=dict, alias='strategyParams')
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


class PlaceOrderRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    code: str
    qty: int
    price: float
    side: str = 'BUY'
    market: str = 'HK'
    trade_env: str = Field('SIMULATE', alias='tradeEnv')
    order_type: str = Field('NORMAL', alias='orderType')
    time_in_force: str = Field('DAY', alias='timeInForce')
    fill_outside_rth: bool = Field(False, alias='fillOutsideRth')
    session: str = 'NONE'
    aux_price: Optional[float] = Field(None, alias='auxPrice')
    trail_type: Optional[str] = Field('NONE', alias='trailType')
    trail_value: Optional[float] = Field(None, alias='trailValue')
    trail_spread: Optional[float] = Field(None, alias='trailSpread')
    acc_id: Optional[int] = Field(None, alias='accId')
    run_id: Optional[str] = Field(None, alias='runId')
    source: str = 'manual'
    note: Optional[str] = None


class BacktestValidationRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    strategy_name: str = Field('pyramiding_ma', alias='strategyName')
    strategy_params: Dict[str, Any] = Field(default_factory=dict, alias='strategyParams')
    codes: List[str] = Field(default_factory=lambda: ['HK.03690'])
    start: str
    end: str
    short_ma: int = Field(5, alias='shortMa')
    long_ma: int = Field(10, alias='longMa')
    order_qty: int = Field(100, alias='orderQty')
    max_position_per_stock: int = Field(300, alias='maxPositionPerStock')
    initial_cash: float = Field(100000.0, alias='initialCash')
    commission_rate: float = Field(0.001, alias='commissionRate')
    slippage: float = 0.0
    no_cache: bool = Field(False, alias='noCache')


class StrategyRuntime:
    def __init__(self):
        self.manager = StrategyManager()
        self.repository = RuntimeRepository(db_path=DB_PATH)
        self.position_service = PositionService(self.repository)
        self.trading_service = TradingService(repository=self.repository, position_service=self.position_service)
        self.runs: Dict[str, StrategyRun] = {}
        self.lock = threading.Lock()

    def list_strategies(self):
        return self.manager.list_strategy_definitions()

    def _resolve_strategy_params(self, strategy_name: str, overrides: Optional[Dict[str, Any]] = None):
        params = dict(STRATEGY_METADATA[strategy_name].get('params', {}))
        for key, value in (overrides or {}).items():
            if value is None:
                continue
            if key == 'codes' and isinstance(value, str):
                params[key] = [item.strip() for item in value.split(',') if item.strip()]
            else:
                params[key] = value
        return params

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

    def _pid_is_alive(self, pid: Optional[int]) -> bool:
        if not pid or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        else:
            return True

    def reconcile_running_runs(self):
        with self.lock:
            active_runs = dict(self.runs)

        for run in self.repository.list_runs():
            if run['status'] != 'running':
                continue

            in_memory_run = active_runs.get(run['id'])
            if in_memory_run is not None:
                if in_memory_run.process.poll() is None:
                    continue
                stopped_at = in_memory_run.stopped_at or time.time()
                self.repository.update_run_status(run['id'], 'stopped', stopped_at=stopped_at)
                continue

            if not self._pid_is_alive(run.get('pid')):
                self.repository.update_run_status(run['id'], 'stopped', stopped_at=time.time())
                logger.info("启动对账修正实例状态: run_id=%s pid=%s -> stopped", run['id'], run.get('pid'))

    def start_strategy(self, request: StartStrategyRequest):
        if request.strategy_name not in STRATEGY_METADATA:
            raise HTTPException(status_code=404, detail='Strategy not found')

        config = self._resolve_strategy_params(
            request.strategy_name,
            {
                **request.strategy_params,
                'codes': request.codes,
                'short_ma': request.short_ma,
                'long_ma': request.long_ma,
                'order_qty': request.order_qty,
                'max_position_per_stock': request.max_position_per_stock,
            },
        )
        config['strategy'] = request.strategy_name

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
        self.reconcile_running_runs()
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
        if run is not None:
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

        db_run = self.repository.get_run(run_id)
        if db_run is None:
            raise HTTPException(status_code=404, detail='Run not found')

        pid = db_run.get('pid')
        if not pid:
            raise HTTPException(status_code=409, detail='Run has no active pid')

        try:
            os.kill(pid, signal.SIGINT)
        except ProcessLookupError:
            stopped_at = time.time()
            self.repository.update_run_status(run_id, 'stopped', stopped_at=stopped_at)
            logger.warning("停止策略时发现进程已不存在: run_id=%s pid=%s", run_id, pid)
            updated = self.repository.get_run(run_id)
            return updated or db_run
        except PermissionError as exc:
            raise HTTPException(status_code=500, detail=f'Unable to stop process: {exc}') from exc

        stopped_at = time.time()
        self.repository.update_run_status(run_id, 'stopped', stopped_at=stopped_at)
        logger.info("按数据库 PID 停止策略实例: run_id=%s pid=%s", run_id, pid)
        updated = self.repository.get_run(run_id)
        return updated or db_run

    def delete_run(self, run_id: str):
        db_run = self.repository.get_run(run_id)
        if db_run is None:
            raise HTTPException(status_code=404, detail='Run not found')
        if db_run.get('status') == 'running':
            raise HTTPException(status_code=409, detail='Please stop the run before deleting it')

        raw_log_path = db_run.get('logPath')
        self.repository.delete_run(run_id)
        with self.lock:
            self.runs.pop(run_id, None)
        if raw_log_path:
            log_path = Path(raw_log_path)
            if log_path.exists():
                try:
                    log_path.unlink()
                except OSError:
                    logger.warning("删除实例日志文件失败: run_id=%s path=%s", run_id, raw_log_path)
        logger.info("删除策略实例: run_id=%s", run_id)
        return {'status': 'deleted', 'runId': run_id}

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

    def run_backtest_validation(self, request: BacktestValidationRequest):
        if request.strategy_name not in STRATEGY_METADATA:
            raise HTTPException(status_code=404, detail='Strategy not found')

        strategy_params = self._resolve_strategy_params(
            request.strategy_name,
            {
                **request.strategy_params,
                'codes': request.codes,
                'short_ma': request.short_ma,
                'long_ma': request.long_ma,
                'order_qty': request.order_qty,
                'max_position_per_stock': request.max_position_per_stock,
            },
        )

        class Args:
            pass

        args = Args()
        args.strategy = request.strategy_name
        args.codes = strategy_params.get('codes', request.codes)
        args.start = request.start
        args.end = request.end
        args.short_ma = strategy_params.get('short_ma', request.short_ma)
        args.long_ma = strategy_params.get('long_ma', request.long_ma)
        args.order_qty = strategy_params.get('order_qty', request.order_qty)
        args.max_position_per_stock = strategy_params.get('max_position_per_stock', request.max_position_per_stock)
        args.initial_cash = request.initial_cash
        args.commission_rate = request.commission_rate
        args.slippage = request.slippage
        args.no_cache = request.no_cache
        args.report_file = None
        logger.info(
            "执行回测验证: strategy=%s code=%s start=%s end=%s",
            args.strategy,
            ','.join(args.codes),
            args.start,
            args.end,
        )
        return run_replay_validation(args)

    def list_trade_accounts(self, market: str = 'HK'):
        try:
            return self.trading_service.list_accounts(market=market)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def place_trade_order(self, request: PlaceOrderRequest):
        try:
            return self.trading_service.place_order(
                code=request.code,
                qty=request.qty,
                price=request.price,
                side=request.side,
                market=request.market,
                trd_env=request.trade_env,
                order_type=request.order_type,
                time_in_force=request.time_in_force,
                fill_outside_rth=request.fill_outside_rth,
                session=request.session,
                aux_price=request.aux_price,
                trail_type=request.trail_type,
                trail_value=request.trail_value,
                trail_spread=request.trail_spread,
                acc_id=request.acc_id,
                run_id=request.run_id,
                source=request.source,
                note=request.note,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def list_trade_orders(self, market='HK', trade_env='SIMULATE', acc_id=None, code=None, refresh=True, limit=200):
        try:
            return self.trading_service.list_orders(
                market=market,
                trd_env=trade_env,
                acc_id=acc_id,
                code=code,
                refresh=refresh,
                limit=limit,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def list_trade_deals(self, market='HK', trade_env='SIMULATE', acc_id=None, code=None, refresh=True, limit=200):
        try:
            return self.trading_service.list_deals(
                market=market,
                trd_env=trade_env,
                acc_id=acc_id,
                code=code,
                refresh=refresh,
                limit=limit,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def read_logs(self, run_id: str, lines: int = 200):
        with self.lock:
            run = self.runs.get(run_id)
        if run is not None:
            log_path = run.log_path
        else:
            db_run = self.repository.get_run(run_id)
            if db_run is None:
                raise HTTPException(status_code=404, detail='Run not found')
            raw_log_path = db_run.get('logPath')
            if not raw_log_path:
                return []
            log_path = Path(raw_log_path)

        if not log_path.exists():
            return []
        content = log_path.read_text().splitlines()
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
    runtime.reconcile_running_runs()
    app.state.guardian = PositionGuardian(runtime.repository)
    app.state.guardian.start()
    app.state.trade_push = TradePushWorker(runtime.trading_service)
    app.state.trade_push.start()
    app.state.order_sync = OrderSyncWorker(runtime.trading_service)
    app.state.order_sync.start()


@app.on_event('shutdown')
def shutdown_guardian():
    guardian_instance = getattr(app.state, 'guardian', None)
    if guardian_instance is not None:
        guardian_instance.stop()
    trade_push = getattr(app.state, 'trade_push', None)
    if trade_push is not None:
        trade_push.stop()
    order_sync = getattr(app.state, 'order_sync', None)
    if order_sync is not None:
        order_sync.stop()


@app.get('/api/health')
def health():
    return {'status': 'ok'}


@app.get('/api/system/status')
def system_status():
    guardian = getattr(app.state, 'guardian', None)
    trade_push = getattr(app.state, 'trade_push', None)
    order_sync = getattr(app.state, 'order_sync', None)
    guardian_status = guardian.get_status() if guardian is not None else {
        'running': False,
        'threadAlive': False,
        'openDConnected': False,
        'quoteLogin': False,
        'detail': 'guardian_unavailable',
        'subscribedCodes': [],
        'positionCount': 0,
        'lastError': 'guardian_unavailable',
        'startedAt': None,
        'host': None,
        'port': None,
    }
    order_sync_status = order_sync.get_status() if order_sync is not None else {
        'running': False,
        'lastError': 'order_sync_unavailable',
        'intervalSec': None,
    }
    trade_push_status = trade_push.get_status() if trade_push is not None else {
        'running': False,
        'markets': [],
        'lastError': 'trade_push_unavailable',
    }
    return {
        'status': 'ok',
        'openD': {
            'connected': guardian_status['openDConnected'],
            'quoteLogin': guardian_status['quoteLogin'],
            'detail': guardian_status['detail'],
            'host': guardian_status['host'],
            'port': guardian_status['port'],
        },
        'guardian': guardian_status,
        'tradePush': trade_push_status,
        'orderSync': order_sync_status,
    }


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


@app.delete('/api/runs/{run_id}')
def delete_run(run_id: str):
    return runtime.delete_run(run_id)


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


@app.post('/api/backtests/replay-validation')
def run_backtest_validation(request: BacktestValidationRequest):
    return runtime.run_backtest_validation(request)


@app.get('/api/trading/accounts')
def list_trade_accounts(market: str = 'HK'):
    return runtime.list_trade_accounts(market=market)


@app.post('/api/trading/orders')
def place_trade_order(request: PlaceOrderRequest):
    return runtime.place_trade_order(request)


@app.get('/api/trading/orders')
def list_trade_orders(
    market: str = 'HK',
    trade_env: str = 'SIMULATE',
    acc_id: Optional[int] = None,
    code: Optional[str] = None,
    refresh: bool = True,
    limit: int = 200,
):
    return runtime.list_trade_orders(
        market=market,
        trade_env=trade_env,
        acc_id=acc_id,
        code=code,
        refresh=refresh,
        limit=limit,
    )


@app.get('/api/trading/deals')
def list_trade_deals(
    market: str = 'HK',
    trade_env: str = 'SIMULATE',
    acc_id: Optional[int] = None,
    code: Optional[str] = None,
    refresh: bool = True,
    limit: int = 200,
):
    return runtime.list_trade_deals(
        market=market,
        trade_env=trade_env,
        acc_id=acc_id,
        code=code,
        refresh=refresh,
        limit=limit,
    )
