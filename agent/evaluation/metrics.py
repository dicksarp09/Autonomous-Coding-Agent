from __future__ import annotations
from pydantic import BaseModel
from typing import Optional
import sqlite3
from ..config import DB_PATH
from datetime import datetime


class WorkflowMetrics(BaseModel):
    workflow_id: str
    iterations: int
    success: bool
    cost: float
    latency: float
    repeated_error: bool
    injection_detected: bool
    timestamp: Optional[datetime] = None


def ensure_table():
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_metrics (
                workflow_id TEXT PRIMARY KEY,
                iterations INTEGER,
                success INTEGER,
                cost REAL,
                latency REAL,
                repeated_error INTEGER,
                injection_detected INTEGER,
                timestamp TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def persist_metrics(m: WorkflowMetrics) -> None:
    ensure_table()
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO workflow_metrics (workflow_id, iterations, success, cost, latency, repeated_error, injection_detected, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                m.workflow_id,
                m.iterations,
                1 if m.success else 0,
                m.cost,
                m.latency,
                1 if m.repeated_error else 0,
                1 if m.injection_detected else 0,
                (m.timestamp.isoformat() if m.timestamp else datetime.utcnow().isoformat()),
            ),
        )
        conn.commit()
    finally:
        conn.close()
