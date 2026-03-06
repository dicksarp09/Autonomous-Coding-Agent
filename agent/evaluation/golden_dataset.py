from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Literal, Optional
import sqlite3
from pathlib import Path
from ..config import DB_PATH
from datetime import datetime


class GoldenTestCase(BaseModel):
    test_id: str
    description: str
    initial_code: str
    expected_code: str
    expected_tests_passed: bool
    complexity: Literal["simple", "medium", "hard", "adversarial"]


def ensure_table():
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS golden_tests (
                id TEXT PRIMARY KEY,
                description TEXT,
                initial_code TEXT,
                expected_code TEXT,
                expected_tests_passed INTEGER,
                complexity TEXT,
                project_ns TEXT,
                created_at TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def insert_case(case: GoldenTestCase, project_ns: str = "default") -> None:
    ensure_table()
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO golden_tests (id, description, initial_code, expected_code, expected_tests_passed, complexity, project_ns, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                case.test_id,
                case.description,
                case.initial_code,
                case.expected_code,
                1 if case.expected_tests_passed else 0,
                case.complexity,
                project_ns,
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def list_cases(project_ns: str = "default"):
    ensure_table()
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, description, initial_code, expected_code, expected_tests_passed, complexity FROM golden_tests WHERE project_ns = ?", (project_ns,))
        rows = cur.fetchall()
        return [
            GoldenTestCase(
                test_id=r[0],
                description=r[1],
                initial_code=r[2],
                expected_code=r[3],
                expected_tests_passed=bool(r[4]),
                complexity=r[5],
            )
            for r in rows
        ]
    finally:
        conn.close()


class GoldenDataset:
    def __init__(self, db_path: Path | None = None):
        self.db = db_path or DB_PATH
        self._init()

    def _init(self):
        conn = sqlite3.connect(str(self.db))
        try:
            cur = conn.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS golden_tasks (id INTEGER PRIMARY KEY, name TEXT, payload TEXT)")
            cur.execute("CREATE TABLE IF NOT EXISTS golden_results (id INTEGER PRIMARY KEY, task_id INTEGER, success INTEGER, output TEXT)")
            conn.commit()
        finally:
            conn.close()

    def add_task(self, name: str, payload: str) -> int:
        conn = sqlite3.connect(str(self.db))
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO golden_tasks (name, payload) VALUES (?, ?)", (name, payload))
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()
