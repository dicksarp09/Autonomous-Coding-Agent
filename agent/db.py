"""SQLite DB initialization and helper functions for schema required by the agent."""
from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Iterator
from .config import DB_PATH


SCHEMA = '''
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS workflows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    model_used TEXT,
    cost REAL DEFAULT 0,
    latency REAL DEFAULT 0,
    iteration_count INTEGER DEFAULT 0,
    success INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS iterations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id INTEGER REFERENCES workflows(id) ON DELETE CASCADE,
    iteration_index INTEGER,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP,
    latency REAL DEFAULT 0,
    cost REAL DEFAULT 0,
    result TEXT
);

CREATE TABLE IF NOT EXISTS golden_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    payload TEXT
);

CREATE TABLE IF NOT EXISTS golden_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER REFERENCES golden_tasks(id) ON DELETE CASCADE,
    success INTEGER,
    output TEXT,
    evaluated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    component TEXT,
    level TEXT,
    message TEXT
);
'''


def init_db(path: Path | None = None) -> None:
    p = path or DB_PATH
    pparent = Path(p).parent
    pparent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    try:
        cur = conn.cursor()
        cur.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def get_conn(path: Path | None = None) -> sqlite3.Connection:
    p = path or DB_PATH
    return sqlite3.connect(str(p))
