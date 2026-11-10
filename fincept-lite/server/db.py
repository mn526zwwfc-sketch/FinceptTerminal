"""Persistencia SQLite (equivalente a storage/sqlite/Database + CacheDatabase).

El terminal real usa dos bases SQLite locales (datos y caché). Aquí el
servidor guarda en una sola base: usuarios y sesiones (lo que en Fincept vive
en el backend remoto), watchlists, paper trading, historial de chat y una
caché TTL (CacheManager).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any, Iterable

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    phone TEXT DEFAULT '',
    country_code TEXT DEFAULT '',
    country TEXT DEFAULT '',
    is_verified INTEGER DEFAULT 0,
    is_admin INTEGER DEFAULT 0,
    account_type TEXT DEFAULT 'free',
    credit_balance REAL DEFAULT 0,
    api_key TEXT UNIQUE,
    mfa_enabled INTEGER DEFAULT 0,
    created_at REAL,
    last_login_at REAL,
    failed_attempts INTEGER DEFAULT 0,
    locked_until REAL DEFAULT 0,
    otp TEXT,
    otp_expires REAL DEFAULT 0,
    otp_attempts INTEGER DEFAULT 0,
    mcp_token TEXT UNIQUE,
    mcp_allow_actions INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at REAL,
    last_seen REAL,
    active INTEGER DEFAULT 1,
    user_agent TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS login_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER, at REAL, ip TEXT, user_agent TEXT, success INTEGER
);
CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER, at REAL, endpoint TEXT, credits REAL
);
CREATE TABLE IF NOT EXISTS watchlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL, name TEXT NOT NULL, symbols TEXT NOT NULL, updated_at REAL
);
CREATE TABLE IF NOT EXISTS paper_accounts (
    user_id INTEGER PRIMARY KEY, cash REAL, initial_cash REAL, realized_pnl REAL DEFAULT 0, created_at REAL
);
CREATE TABLE IF NOT EXISTS paper_positions (
    user_id INTEGER, symbol TEXT, qty REAL, avg_price REAL, PRIMARY KEY (user_id, symbol)
);
CREATE TABLE IF NOT EXISTS paper_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER, symbol TEXT, side TEXT, qty REAL, type TEXT,
    limit_price REAL, stop_price REAL, status TEXT, filled_price REAL,
    created_at REAL, filled_at REAL, source TEXT DEFAULT 'ui', note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY, value TEXT, expires_at REAL
);
CREATE TABLE IF NOT EXISTS fund_state (
    user_id INTEGER PRIMARY KEY, autopilot INTEGER DEFAULT 0, interval_min INTEGER DEFAULT 60,
    halted INTEGER DEFAULT 0, halt_reason TEXT, peak_equity REAL DEFAULT 0, consecutive_losses INTEGER DEFAULT 0,
    desk_trust TEXT DEFAULT '{}', last_cycle_at REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS fund_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, started REAL, finished REAL, trigger TEXT,
    status TEXT, equity REAL, report TEXT
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER, session_id TEXT, role TEXT, text TEXT, at REAL
);
"""


class Database:
    def __init__(self, path: str) -> None:
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.conn.execute(sql, tuple(params))

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        with self._lock:
            row = self.conn.execute(sql, tuple(params)).fetchone()
            return dict(row) if row else None

    def all(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

    def transaction(self):
        return _Tx(self)

    # ── CacheManager (TTL key/value) ────────────────────────────────────────
    def cache_get(self, key: str) -> Any | None:
        row = self.one("SELECT value, expires_at FROM cache WHERE key=?", (key,))
        if not row or row["expires_at"] < time.time():
            return None
        return json.loads(row["value"])

    def cache_put(self, key: str, value: Any, ttl_s: float) -> None:
        self.execute(
            "INSERT OR REPLACE INTO cache(key, value, expires_at) VALUES (?,?,?)",
            (key, json.dumps(value), time.time() + ttl_s),
        )


class _Tx:
    def __init__(self, db: Database) -> None:
        self.db = db

    def __enter__(self) -> sqlite3.Connection:
        self.db._lock.acquire()
        self.db.conn.execute("BEGIN IMMEDIATE")
        return self.db.conn

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self.db.conn.execute("ROLLBACK" if exc_type else "COMMIT")
        finally:
            self.db._lock.release()


_db: Database | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        if str(settings.db_path) != ":memory:":
            settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        _db = Database(str(settings.db_path))
    return _db


def reset_db_for_tests(path: str = ":memory:") -> Database:
    global _db
    _db = Database(path)
    return _db
