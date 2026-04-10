#!/usr/bin/env python3
"""Runtime state repository backed by SQLite."""

from contextlib import contextmanager
import json
import threading
import time
from pathlib import Path

from backend.repositories.sqlite import connect

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = ROOT / 'backend' / 'data' / 'runtime.sqlite3'


class RuntimeRepository:
    def __init__(self, db_path=None):
        self.db_path = str(db_path or DEFAULT_DB_PATH)
        self.conn = connect(self.db_path)
        self.lock = threading.RLock()
        self._init_schema()

    def _init_schema(self):
        with self.lock:
            self.conn.executescript(
                '''
                CREATE TABLE IF NOT EXISTS strategy_runs (
                    run_id TEXT PRIMARY KEY,
                    strategy_name TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    pid INTEGER,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    stopped_at REAL,
                    log_path TEXT
                );

                CREATE TABLE IF NOT EXISTS strategy_positions (
                    run_id TEXT NOT NULL,
                    code TEXT NOT NULL,
                    qty INTEGER NOT NULL,
                    entry REAL NOT NULL,
                    stop REAL NOT NULL,
                    profit REAL NOT NULL,
                    stop_pct REAL NOT NULL,
                    profit_pct REAL NOT NULL,
                    reason TEXT,
                    entry_time TEXT,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (run_id, code),
                    FOREIGN KEY(run_id) REFERENCES strategy_runs(run_id)
                );

                CREATE TABLE IF NOT EXISTS account_positions (
                    account_id TEXT NOT NULL,
                    code TEXT NOT NULL,
                    qty INTEGER NOT NULL,
                    entry REAL NOT NULL,
                    stop REAL NOT NULL,
                    profit REAL NOT NULL,
                    stop_pct REAL NOT NULL,
                    profit_pct REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (account_id, code)
                );

                CREATE TABLE IF NOT EXISTS pending_orders (
                    run_id TEXT NOT NULL,
                    code TEXT NOT NULL,
                    side TEXT NOT NULL,
                    qty INTEGER NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (run_id, code, side),
                    FOREIGN KEY(run_id) REFERENCES strategy_runs(run_id)
                );

                CREATE TABLE IF NOT EXISTS executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    code TEXT NOT NULL,
                    side TEXT NOT NULL,
                    qty INTEGER NOT NULL,
                    price REAL,
                    reason TEXT,
                    position_qty_after INTEGER,
                    avg_entry_after REAL,
                    realized_pnl REAL,
                    metadata_json TEXT,
                    executed_at REAL NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES strategy_runs(run_id)
                );

                CREATE TABLE IF NOT EXISTS trade_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    broker_order_id TEXT NOT NULL UNIQUE,
                    run_id TEXT,
                    account_id TEXT,
                    market TEXT NOT NULL,
                    trade_env TEXT NOT NULL,
                    code TEXT NOT NULL,
                    stock_name TEXT,
                    trd_side TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    order_status TEXT NOT NULL,
                    price REAL,
                    qty REAL NOT NULL,
                    dealt_qty REAL,
                    dealt_avg_price REAL,
                    create_time TEXT,
                    updated_time TEXT,
                    currency TEXT,
                    last_err_msg TEXT,
                    remark TEXT,
                    time_in_force TEXT,
                    fill_outside_rth TEXT,
                    session TEXT,
                    aux_price TEXT,
                    trail_type TEXT,
                    trail_value TEXT,
                    trail_spread TEXT,
                    source TEXT,
                    note TEXT,
                    settled_qty REAL NOT NULL DEFAULT 0,
                    settlement_status TEXT,
                    settled_at REAL,
                    raw_json TEXT,
                    recorded_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trade_deals (
                    deal_id TEXT PRIMARY KEY,
                    broker_order_id TEXT,
                    account_id TEXT,
                    market TEXT,
                    trade_env TEXT,
                    code TEXT NOT NULL,
                    stock_name TEXT,
                    trd_side TEXT,
                    qty REAL,
                    price REAL,
                    create_time TEXT,
                    status TEXT,
                    recorded_at REAL NOT NULL,
                    raw_json TEXT
                );
                '''
            )
            existing_columns = {
                row['name'] for row in self.conn.execute("PRAGMA table_info(trade_orders)").fetchall()
            }
            if 'settled_qty' not in existing_columns:
                self.conn.execute('ALTER TABLE trade_orders ADD COLUMN settled_qty REAL NOT NULL DEFAULT 0')
            if 'settlement_status' not in existing_columns:
                self.conn.execute('ALTER TABLE trade_orders ADD COLUMN settlement_status TEXT')
            if 'settled_at' not in existing_columns:
                self.conn.execute('ALTER TABLE trade_orders ADD COLUMN settled_at REAL')
            self.conn.commit()

    @contextmanager
    def transaction(self):
        with self.lock:
            self.conn.execute('BEGIN')
            try:
                yield
            except Exception:
                self.conn.rollback()
                raise
            else:
                self.conn.commit()

    def upsert_run(self, run_id, strategy_name, config, pid, status, created_at=None, stopped_at=None, log_path=None, commit=True):
        created_at = created_at or time.time()
        with self.lock:
            self.conn.execute(
                '''
                INSERT INTO strategy_runs (run_id, strategy_name, config_json, pid, status, created_at, stopped_at, log_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    strategy_name=excluded.strategy_name,
                    config_json=excluded.config_json,
                    pid=excluded.pid,
                    status=excluded.status,
                    stopped_at=excluded.stopped_at,
                    log_path=excluded.log_path
                ''',
                (run_id, strategy_name, json.dumps(config, ensure_ascii=False), pid, status, created_at, stopped_at, log_path),
            )
            if commit:
                self.conn.commit()

    def update_run_status(self, run_id, status, stopped_at=None, pid=None, commit=True):
        with self.lock:
            self.conn.execute(
                'UPDATE strategy_runs SET status=?, stopped_at=COALESCE(?, stopped_at), pid=COALESCE(?, pid) WHERE run_id=?',
                (status, stopped_at, pid, run_id),
            )
            if commit:
                self.conn.commit()

    def get_run(self, run_id):
        with self.lock:
            row = self.conn.execute('SELECT * FROM strategy_runs WHERE run_id=?', (run_id,)).fetchone()
        return self._row_to_run(row) if row else None

    def list_runs(self):
        with self.lock:
            rows = self.conn.execute('SELECT * FROM strategy_runs ORDER BY created_at DESC').fetchall()
        return [self._row_to_run(row) for row in rows]

    def delete_run(self, run_id, commit=True):
        with self.lock:
            self.conn.execute('DELETE FROM pending_orders WHERE run_id=?', (run_id,))
            self.conn.execute('DELETE FROM strategy_positions WHERE run_id=?', (run_id,))
            self.conn.execute('DELETE FROM executions WHERE run_id=?', (run_id,))
            self.conn.execute('DELETE FROM strategy_runs WHERE run_id=?', (run_id,))
            if commit:
                self.conn.commit()

    def replace_pending_orders(self, run_id, pending_orders, commit=True):
        now = time.time()
        with self.lock:
            self.conn.execute('DELETE FROM pending_orders WHERE run_id=?', (run_id,))
            for item in pending_orders:
                self.conn.execute(
                    'INSERT INTO pending_orders (run_id, code, side, qty, updated_at) VALUES (?, ?, ?, ?, ?)',
                    (run_id, item['code'], item['side'], item['qty'], now),
                )
            if commit:
                self.conn.commit()

    def upsert_strategy_position(self, run_id, code, position, commit=True):
        now = time.time()
        with self.lock:
            values = (
                run_id,
                code,
                position['qty'],
                position['entry'],
                position['stop'],
                position['profit'],
                position['stop_pct'],
                position['profit_pct'],
                position.get('reason'),
                position.get('entry_time'),
                now,
            )
            self.conn.execute(
                '''
                INSERT INTO strategy_positions (run_id, code, qty, entry, stop, profit, stop_pct, profit_pct, reason, entry_time, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, code) DO UPDATE SET
                    qty=excluded.qty,
                    entry=excluded.entry,
                    stop=excluded.stop,
                    profit=excluded.profit,
                    stop_pct=excluded.stop_pct,
                    profit_pct=excluded.profit_pct,
                    reason=excluded.reason,
                    entry_time=excluded.entry_time,
                    updated_at=excluded.updated_at
                ''',
                values,
            )
            if commit:
                self.conn.commit()

    def delete_strategy_position(self, run_id, code, commit=True):
        with self.lock:
            self.conn.execute('DELETE FROM strategy_positions WHERE run_id=? AND code=?', (run_id, code))
            if commit:
                self.conn.commit()

    def get_strategy_position(self, run_id, code):
        with self.lock:
            row = self.conn.execute(
                'SELECT * FROM strategy_positions WHERE run_id=? AND code=?',
                (run_id, code),
            ).fetchone()
        return dict(row) if row else None

    def upsert_pending_order(self, run_id, code, side, qty, commit=True):
        now = time.time()
        with self.lock:
            self.conn.execute(
                '''
                INSERT INTO pending_orders (run_id, code, side, qty, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_id, code, side) DO UPDATE SET
                    qty=excluded.qty,
                    updated_at=excluded.updated_at
                ''',
                (run_id, code, side, qty, now),
            )
            if commit:
                self.conn.commit()

    def get_pending_order(self, run_id, code, side):
        with self.lock:
            row = self.conn.execute(
                'SELECT * FROM pending_orders WHERE run_id=? AND code=? AND side=?',
                (run_id, code, side),
            ).fetchone()
        return dict(row) if row else None

    def remove_pending_order(self, run_id, code, side, commit=True):
        with self.lock:
            self.conn.execute(
                'DELETE FROM pending_orders WHERE run_id=? AND code=? AND side=?',
                (run_id, code, side),
            )
            if commit:
                self.conn.commit()

    def list_all_pending_orders(self, side=None):
        with self.lock:
            if side is None:
                rows = self.conn.execute(
                    'SELECT * FROM pending_orders ORDER BY run_id, code, side'
                ).fetchall()
            else:
                rows = self.conn.execute(
                    'SELECT * FROM pending_orders WHERE side=? ORDER BY run_id, code',
                    (side,),
                ).fetchall()
        return [dict(row) for row in rows]

    def list_strategy_positions(self, run_id):
        with self.lock:
            rows = self.conn.execute('SELECT * FROM strategy_positions WHERE run_id=? ORDER BY code', (run_id,)).fetchall()
        return [dict(row) for row in rows]

    def list_strategy_positions_by_code(self, code):
        with self.lock:
            rows = self.conn.execute(
                '''
                SELECT * FROM strategy_positions
                WHERE code=?
                ORDER BY COALESCE(entry_time, ''), updated_at, run_id
                ''',
                (code,),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_account_position(self, account_id, code, position, commit=True):
        now = time.time()
        with self.lock:
            self.conn.execute(
                '''
                INSERT INTO account_positions (account_id, code, qty, entry, stop, profit, stop_pct, profit_pct, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id, code) DO UPDATE SET
                    qty=excluded.qty,
                    entry=excluded.entry,
                    stop=excluded.stop,
                    profit=excluded.profit,
                    stop_pct=excluded.stop_pct,
                    profit_pct=excluded.profit_pct,
                    updated_at=excluded.updated_at
                ''',
                (
                    account_id,
                    code,
                    position['qty'],
                    position['entry'],
                    position['stop'],
                    position['profit'],
                    position['stop_pct'],
                    position['profit_pct'],
                    now,
                ),
            )
            if commit:
                self.conn.commit()

    def get_account_position(self, account_id, code):
        with self.lock:
            row = self.conn.execute(
                'SELECT * FROM account_positions WHERE account_id=? AND code=?',
                (account_id, code),
            ).fetchone()
        return dict(row) if row else None

    def delete_account_position(self, account_id, code, commit=True):
        with self.lock:
            self.conn.execute(
                'DELETE FROM account_positions WHERE account_id=? AND code=?',
                (account_id, code),
            )
            if commit:
                self.conn.commit()

    def list_account_positions(self, account_id):
        with self.lock:
            rows = self.conn.execute(
                'SELECT * FROM account_positions WHERE account_id=? ORDER BY code',
                (account_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_all_account_positions(self):
        with self.lock:
            rows = self.conn.execute(
                'SELECT * FROM account_positions ORDER BY account_id, code'
            ).fetchall()
        return [dict(row) for row in rows]

    def list_pending_orders(self, run_id):
        with self.lock:
            rows = self.conn.execute('SELECT * FROM pending_orders WHERE run_id=? ORDER BY code, side', (run_id,)).fetchall()
        return [dict(row) for row in rows]

    def record_execution(
        self,
        run_id,
        code,
        side,
        qty,
        price=None,
        reason=None,
        position_qty_after=None,
        avg_entry_after=None,
        realized_pnl=None,
        metadata=None,
        executed_at=None,
        commit=True,
    ):
        executed_at = executed_at or time.time()
        metadata_json = json.dumps(metadata, ensure_ascii=False) if metadata is not None else None
        with self.lock:
            self.conn.execute(
                '''
                INSERT INTO executions (
                    run_id, code, side, qty, price, reason,
                    position_qty_after, avg_entry_after, realized_pnl,
                    metadata_json, executed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    run_id,
                    code,
                    side,
                    qty,
                    price,
                    reason,
                    position_qty_after,
                    avg_entry_after,
                    realized_pnl,
                    metadata_json,
                    executed_at,
                ),
            )
            if commit:
                self.conn.commit()

    def list_executions(self, run_id):
        with self.lock:
            rows = self.conn.execute(
                'SELECT * FROM executions WHERE run_id=? ORDER BY executed_at ASC, id ASC',
                (run_id,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            if item.get('metadata_json'):
                item['metadata'] = json.loads(item['metadata_json'])
            else:
                item['metadata'] = None
            item.pop('metadata_json', None)
            result.append(item)
        return result

    def get_trade_order(self, broker_order_id):
        with self.lock:
            row = self.conn.execute(
                'SELECT * FROM trade_orders WHERE broker_order_id=?',
                (str(broker_order_id),),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item['raw'] = json.loads(item['raw_json']) if item.get('raw_json') else None
        item.pop('raw_json', None)
        return item

    def get_trade_deal(self, deal_id):
        with self.lock:
            row = self.conn.execute(
                'SELECT * FROM trade_deals WHERE deal_id=?',
                (str(deal_id),),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item['raw'] = json.loads(item['raw_json']) if item.get('raw_json') else None
        item.pop('raw_json', None)
        return item

    def upsert_trade_order(self, order, commit=True):
        recorded_at = time.time()
        raw_json = json.dumps(order, ensure_ascii=False)
        with self.lock:
            self.conn.execute(
                '''
                INSERT INTO trade_orders (
                    broker_order_id, run_id, account_id, market, trade_env, code, stock_name,
                    trd_side, order_type, order_status, price, qty, dealt_qty, dealt_avg_price,
                    create_time, updated_time, currency, last_err_msg, remark, time_in_force,
                    fill_outside_rth, session, aux_price, trail_type, trail_value, trail_spread,
                    source, note, settled_qty, settlement_status, settled_at, raw_json, recorded_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(broker_order_id) DO UPDATE SET
                    run_id=excluded.run_id,
                    account_id=excluded.account_id,
                    market=excluded.market,
                    trade_env=excluded.trade_env,
                    code=excluded.code,
                    stock_name=excluded.stock_name,
                    trd_side=excluded.trd_side,
                    order_type=excluded.order_type,
                    order_status=excluded.order_status,
                    price=excluded.price,
                    qty=excluded.qty,
                    dealt_qty=excluded.dealt_qty,
                    dealt_avg_price=excluded.dealt_avg_price,
                    create_time=excluded.create_time,
                    updated_time=excluded.updated_time,
                    currency=excluded.currency,
                    last_err_msg=excluded.last_err_msg,
                    remark=excluded.remark,
                    time_in_force=excluded.time_in_force,
                    fill_outside_rth=excluded.fill_outside_rth,
                    session=excluded.session,
                    aux_price=excluded.aux_price,
                    trail_type=excluded.trail_type,
                    trail_value=excluded.trail_value,
                    trail_spread=excluded.trail_spread,
                    source=excluded.source,
                    note=excluded.note,
                    settled_qty=COALESCE(trade_orders.settled_qty, 0),
                    settlement_status=COALESCE(trade_orders.settlement_status, excluded.settlement_status),
                    settled_at=COALESCE(trade_orders.settled_at, excluded.settled_at),
                    raw_json=excluded.raw_json,
                    recorded_at=excluded.recorded_at
                ''',
                (
                    str(order.get('broker_order_id')),
                    order.get('run_id'),
                    str(order.get('account_id')) if order.get('account_id') is not None else None,
                    order.get('market'),
                    order.get('trade_env'),
                    order.get('code'),
                    order.get('stock_name'),
                    order.get('trd_side'),
                    order.get('order_type'),
                    order.get('order_status'),
                    order.get('price'),
                    order.get('qty'),
                    order.get('dealt_qty'),
                    order.get('dealt_avg_price'),
                    order.get('create_time'),
                    order.get('updated_time'),
                    order.get('currency'),
                    order.get('last_err_msg'),
                    order.get('remark'),
                    order.get('time_in_force'),
                    order.get('fill_outside_rth'),
                    order.get('session'),
                    str(order.get('aux_price')) if order.get('aux_price') is not None else None,
                    str(order.get('trail_type')) if order.get('trail_type') is not None else None,
                    str(order.get('trail_value')) if order.get('trail_value') is not None else None,
                    str(order.get('trail_spread')) if order.get('trail_spread') is not None else None,
                    order.get('source'),
                    order.get('note'),
                    order.get('settled_qty', 0),
                    order.get('settlement_status'),
                    order.get('settled_at'),
                    raw_json,
                    recorded_at,
                ),
            )
            if commit:
                self.conn.commit()

    def upsert_trade_deal(self, deal, commit=True):
        recorded_at = time.time()
        raw_json = json.dumps(deal, ensure_ascii=False)
        with self.lock:
            self.conn.execute(
                '''
                INSERT INTO trade_deals (
                    deal_id, broker_order_id, account_id, market, trade_env, code, stock_name,
                    trd_side, qty, price, create_time, status, recorded_at, raw_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(deal_id) DO UPDATE SET
                    broker_order_id=excluded.broker_order_id,
                    account_id=excluded.account_id,
                    market=excluded.market,
                    trade_env=excluded.trade_env,
                    code=excluded.code,
                    stock_name=excluded.stock_name,
                    trd_side=excluded.trd_side,
                    qty=excluded.qty,
                    price=excluded.price,
                    create_time=excluded.create_time,
                    status=excluded.status,
                    recorded_at=excluded.recorded_at,
                    raw_json=excluded.raw_json
                ''',
                (
                    str(deal.get('deal_id')),
                    str(deal.get('order_id')) if deal.get('order_id') is not None else None,
                    str(deal.get('account_id')) if deal.get('account_id') is not None else None,
                    deal.get('market'),
                    deal.get('trade_env'),
                    deal.get('code'),
                    deal.get('stock_name'),
                    deal.get('trd_side'),
                    deal.get('qty'),
                    deal.get('price'),
                    deal.get('create_time'),
                    deal.get('status'),
                    recorded_at,
                    raw_json,
                ),
            )
            if commit:
                self.conn.commit()

    def mark_trade_order_settled(self, broker_order_id, settled_qty, settlement_status='SETTLED', commit=True):
        settled_at = time.time()
        with self.lock:
            self.conn.execute(
                '''
                UPDATE trade_orders
                SET settled_qty=?, settlement_status=?, settled_at=?
                WHERE broker_order_id=?
                ''',
                (settled_qty, settlement_status, settled_at, str(broker_order_id)),
            )
            if commit:
                self.conn.commit()

    def list_trade_orders(self, account_id=None, code=None, trade_env=None, limit=200):
        query = 'SELECT * FROM trade_orders WHERE 1=1'
        params = []
        if account_id is not None:
            query += ' AND account_id=?'
            params.append(str(account_id))
        if code is not None:
            query += ' AND code=?'
            params.append(code)
        if trade_env is not None:
            query += ' AND trade_env=?'
            params.append(trade_env)
        query += ' ORDER BY COALESCE(updated_time, create_time) DESC, id DESC LIMIT ?'
        params.append(limit)
        with self.lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item['raw'] = json.loads(item['raw_json']) if item.get('raw_json') else None
            item.pop('raw_json', None)
            result.append(item)
        return result

    def list_unsettled_trade_orders(self, limit=200):
        active_statuses = (
            'SUBMITTING',
            'SUBMITTED',
            'WAITING_SUBMIT',
            'FILLED_PART',
            'FILLED_PARTIAL',
        )
        placeholders = ','.join('?' for _ in active_statuses)
        query = f'''
            SELECT * FROM trade_orders
            WHERE (
                COALESCE(dealt_qty, 0) > COALESCE(settled_qty, 0)
                OR (
                    COALESCE(settlement_status, '') != 'CLOSED_NO_FILL'
                    AND order_status IN ({placeholders})
                )
            )
            ORDER BY recorded_at DESC
            LIMIT ?
        '''
        with self.lock:
            rows = self.conn.execute(query, (*active_statuses, limit)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item['raw'] = json.loads(item['raw_json']) if item.get('raw_json') else None
            item.pop('raw_json', None)
            result.append(item)
        return result

    def _row_to_run(self, row):
        return {
            'id': row['run_id'],
            'strategyName': row['strategy_name'],
            'config': json.loads(row['config_json']),
            'pid': row['pid'],
            'status': row['status'],
            'createdAt': row['created_at'],
            'stoppedAt': row['stopped_at'],
            'logPath': row['log_path'],
        }
