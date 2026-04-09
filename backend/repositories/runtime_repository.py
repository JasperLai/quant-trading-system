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
                '''
            )
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
