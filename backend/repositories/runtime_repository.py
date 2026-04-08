#!/usr/bin/env python3
"""Runtime state repository backed by SQLite."""

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
        self.lock = threading.Lock()
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

                CREATE TABLE IF NOT EXISTS runtime_commands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at REAL NOT NULL,
                    processed_at REAL,
                    FOREIGN KEY(run_id) REFERENCES strategy_runs(run_id)
                );

                CREATE TABLE IF NOT EXISTS positions (
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

    def upsert_run(self, run_id, strategy_name, config, pid, status, created_at=None, stopped_at=None, log_path=None):
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
            self.conn.commit()

    def update_run_status(self, run_id, status, stopped_at=None, pid=None):
        with self.lock:
            self.conn.execute(
                'UPDATE strategy_runs SET status=?, stopped_at=COALESCE(?, stopped_at), pid=COALESCE(?, pid) WHERE run_id=?',
                (status, stopped_at, pid, run_id),
            )
            self.conn.commit()

    def get_run(self, run_id):
        with self.lock:
            row = self.conn.execute('SELECT * FROM strategy_runs WHERE run_id=?', (run_id,)).fetchone()
        return self._row_to_run(row) if row else None

    def list_runs(self):
        with self.lock:
            rows = self.conn.execute('SELECT * FROM strategy_runs ORDER BY created_at DESC').fetchall()
        return [self._row_to_run(row) for row in rows]

    def enqueue_command(self, run_id, action, payload):
        with self.lock:
            self.conn.execute(
                'INSERT INTO runtime_commands (run_id, action, payload_json, status, created_at) VALUES (?, ?, ?, ?, ?)',
                (run_id, action, json.dumps(payload, ensure_ascii=False), 'pending', time.time()),
            )
            self.conn.commit()

    def fetch_pending_commands(self, run_id):
        with self.lock:
            rows = self.conn.execute(
                'SELECT * FROM runtime_commands WHERE run_id=? AND status=? ORDER BY id ASC',
                (run_id, 'pending'),
            ).fetchall()
        result = []
        for row in rows:
            payload = json.loads(row['payload_json'])
            payload['_command_id'] = row['id']
            result.append(payload)
        return result

    def mark_command_processed(self, command_id):
        with self.lock:
            self.conn.execute(
                'UPDATE runtime_commands SET status=?, processed_at=? WHERE id=?',
                ('processed', time.time(), command_id),
            )
            self.conn.commit()

    def replace_positions(self, run_id, positions):
        now = time.time()
        with self.lock:
            self.conn.execute('DELETE FROM positions WHERE run_id=?', (run_id,))
            for code, pos in positions.items():
                self.conn.execute(
                    '''
                    INSERT INTO positions (run_id, code, qty, entry, stop, profit, stop_pct, profit_pct, reason, entry_time, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        run_id,
                        code,
                        pos['qty'],
                        pos['entry'],
                        pos['stop'],
                        pos['profit'],
                        pos['stop_pct'],
                        pos['profit_pct'],
                        pos.get('reason'),
                        pos.get('entry_time'),
                        now,
                    ),
                )
            self.conn.commit()

    def replace_pending_orders(self, run_id, pending_orders):
        now = time.time()
        with self.lock:
            self.conn.execute('DELETE FROM pending_orders WHERE run_id=?', (run_id,))
            for item in pending_orders:
                self.conn.execute(
                    'INSERT INTO pending_orders (run_id, code, side, qty, updated_at) VALUES (?, ?, ?, ?, ?)',
                    (run_id, item['code'], item['side'], item['qty'], now),
                )
            self.conn.commit()

    def list_positions(self, run_id):
        with self.lock:
            rows = self.conn.execute('SELECT * FROM positions WHERE run_id=? ORDER BY code', (run_id,)).fetchall()
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
