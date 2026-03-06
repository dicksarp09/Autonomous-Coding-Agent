"""Relational metadata store for long-term memory using SQLite."""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import sqlite3
from .memory_vector_store import VectorStore
from ..config import DB_PATH
from datetime import datetime
import uuid
from ..rbac import AgentIdentity, check_permission, ForbiddenError
from ..telemetry.memory_hooks import memory_span
import logging

logger = logging.getLogger(__name__)


class MemoryMetadata(BaseModel):
    memory_id: str
    error_signature: str
    fix_strategy: str
    success: bool
    success_rate: float
    usage_count: int
    project_id: str
    timestamp: datetime


class RelationalStore:
    def __init__(self, db_path=None):
        self.db = db_path or DB_PATH
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(str(self.db))
        try:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_meta (
                    id TEXT PRIMARY KEY,
                    error_signature TEXT,
                    fix_strategy TEXT,
                    success INTEGER,
                    success_rate REAL,
                    usage_count INTEGER,
                    project_id TEXT,
                    timestamp TEXT
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def store(self, error_signature: str, fix_strategy: str, success: bool, project_id: str, agent_identity: AgentIdentity | None = None) -> Dict[str, Any]:
        if agent_identity is None:
            return {"error": "MISSING_IDENTITY", "message": "AgentIdentity required"}
        try:
            check_permission(agent_identity, "store_memory")
        except ForbiddenError as e:
            return {"error": "DENIED", "message": str(e)}

        mid = str(uuid.uuid4())
        ts = datetime.utcnow().isoformat()
        with memory_span("memory.store", project_id=project_id, agent_id=agent_identity.agent_id):
            conn = sqlite3.connect(str(self.db))
            try:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO memory_meta (id, error_signature, fix_strategy, success, success_rate, usage_count, project_id, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (mid, error_signature, fix_strategy, 1 if success else 0, 1.0 if success else 0.0, 1, project_id, ts),
                )
                conn.commit()
                logger.info("memory.store persisted id=%s project=%s", mid, project_id)
                return {"ok": True, "id": mid}
            finally:
                conn.close()

    def query_by_signature(self, signature: str, project_id: str, limit: int = 3, agent_identity: AgentIdentity | None = None) -> Dict[str, Any]:
        if agent_identity is None:
            return {"error": "MISSING_IDENTITY", "message": "AgentIdentity required"}
        try:
            check_permission(agent_identity, "retrieve_long")
        except ForbiddenError as e:
            return {"error": "DENIED", "message": str(e)}

        with memory_span("memory.query", project_id=project_id, agent_id=agent_identity.agent_id):
            conn = sqlite3.connect(str(self.db))
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT id, error_signature, fix_strategy, success_rate, usage_count, timestamp FROM memory_meta WHERE project_id=? ORDER BY rowid DESC LIMIT ?",
                    (project_id, limit),
                )
                rows = cur.fetchall()
                return {"ok": True, "items": [
                    {"id": r[0], "signature": r[1], "fix_strategy": r[2], "success_rate": r[3], "usage_count": r[4], "timestamp": r[5]}
                    for r in rows
                ]}
            finally:
                conn.close()

    def increment_usage(self, memory_id: str, success: bool):
        conn = sqlite3.connect(str(self.db))
        try:
            cur = conn.cursor()
            cur.execute("SELECT usage_count, success_rate FROM memory_meta WHERE id=?", (memory_id,))
            row = cur.fetchone()
            if not row:
                return False
            usage_count, success_rate = row
            usage_count = usage_count + 1
            # incremental update of success rate
            success_rate = (success_rate * (usage_count - 1) + (1.0 if success else 0.0)) / usage_count
            cur.execute("UPDATE memory_meta SET usage_count=?, success_rate=? WHERE id=?", (usage_count, success_rate, memory_id))
            conn.commit()
            return True
        finally:
            conn.close()
