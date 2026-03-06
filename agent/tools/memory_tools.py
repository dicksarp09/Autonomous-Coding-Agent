"""Memory tools (short-term and long-term) with RBAC checks.

Short-term: in-memory sliding window.
Long-term: FAISS index with SQLite metadata (best-effort if faiss not installed).
"""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Dict, Any, List
from ..config import WORKSPACE_ROOT
from pathlib import Path
import sqlite3
import hashlib
from ..rbac import AgentIdentity, check_permission, ForbiddenError
from ..telemetry.memory_hooks import memory_span
from typing import Any

DB = WORKSPACE_ROOT / "agent_data.sqlite3"


class StoreMemoryInput(BaseModel):
    key: str = Field(...)
    value: str = Field(...)
    project_id: str | None = None

    model_config = {"extra": "forbid"}


def _error(field: str, code: str, message: str) -> Dict[str, Any]:
    return {"error": code, "field": field, "message": message}


def _ensure_short_table(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS short_memory (id INTEGER PRIMARY KEY, key TEXT, value TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.commit()


def store_short_term(payload: Dict[str, Any], user_roles: list[str] | None = None, agent_identity: AgentIdentity | None = None) -> Dict[str, Any]:
    try:
        inp = StoreMemoryInput.model_validate(payload)
    except Exception as e:
        return _error("payload", "INVALID_INPUT", str(e))

    if agent_identity is None:
        return _error("identity", "MISSING_IDENTITY", "AgentIdentity required")

    try:
        check_permission(agent_identity, "store_memory")
    except ForbiddenError as e:
        return _error("rbac", "DENIED", str(e))

    conn = sqlite3.connect(str(DB))
    try:
        _ensure_short_table(conn)
        cur = conn.cursor()
        with memory_span("store_short_term", agent_id=agent_identity.agent_id, project_id=inp.project_id or ""):
            cur.execute("INSERT INTO short_memory (key, value) VALUES (?, ?)", (inp.key, inp.value))
            conn.commit()
            # enforce sliding window of 5
            cur.execute("DELETE FROM short_memory WHERE id NOT IN (SELECT id FROM short_memory WHERE key=? ORDER BY id DESC LIMIT 5)", (inp.key,))
            conn.commit()
            return {"ok": True, "id": cur.lastrowid}
    finally:
        conn.close()


def retrieve_short_term(key: str, user_roles: list[str] | None = None, agent_identity: AgentIdentity | None = None) -> Dict[str, Any]:
    if agent_identity is None:
        return _error("identity", "MISSING_IDENTITY", "AgentIdentity required")
    try:
        check_permission(agent_identity, "retrieve_short")
    except ForbiddenError as e:
        return _error("rbac", "DENIED", str(e))

    conn = sqlite3.connect(str(DB))
    try:
        _ensure_short_table(conn)
        cur = conn.cursor()
        with memory_span("retrieve_short_term", agent_id=agent_identity.agent_id):
            cur.execute("SELECT value, created_at FROM short_memory WHERE key=? ORDER BY id DESC LIMIT 5", (key,))
            rows = cur.fetchall()
            return {"ok": True, "key": key, "values": [{"value": r[0], "created_at": r[1]} for r in rows]}
    finally:
        conn.close()


def store_long_term(payload: Dict[str, Any], user_roles: list[str] | None = None, agent_identity: AgentIdentity | None = None) -> Dict[str, Any]:
    try:
        inp = StoreMemoryInput.model_validate(payload)
    except Exception as e:
        return _error("payload", "INVALID_INPUT", str(e))

    if agent_identity is None:
        return _error("identity", "MISSING_IDENTITY", "AgentIdentity required")

    try:
        check_permission(agent_identity, "store_memory")
    except ForbiddenError as e:
        return _error("rbac", "DENIED", str(e))

    if not inp.project_id:
        return _error("project_id", "MISSING", "project_id required for long-term storage")

    h = hashlib.sha256(inp.value.encode("utf-8")).hexdigest()
    conn = sqlite3.connect(str(DB))
    try:
        cur = conn.cursor()
        with memory_span("store_long_term", agent_id=agent_identity.agent_id, project_id=inp.project_id):
            cur.execute(
                "CREATE TABLE IF NOT EXISTS memories (id INTEGER PRIMARY KEY, key TEXT, signature TEXT, value TEXT, project_id TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            )
            cur.execute("INSERT INTO memories (key, signature, value, project_id) VALUES (?, ?, ?, ?)", (inp.key, h, inp.value, inp.project_id))
            conn.commit()
            return {"ok": True, "id": cur.lastrowid}
    finally:
        conn.close()


def retrieve_long_term(key: str, user_roles: list[str] | None = None, agent_identity: AgentIdentity | None = None, project_id: str | None = None) -> Dict[str, Any]:
    if agent_identity is None:
        return _error("identity", "MISSING_IDENTITY", "AgentIdentity required")
    try:
        check_permission(agent_identity, "retrieve_long")
    except ForbiddenError as e:
        return _error("rbac", "DENIED", str(e))

    if not project_id:
        return _error("project_id", "MISSING", "project_id required for retrieval")

    conn = sqlite3.connect(str(DB))
    try:
        cur = conn.cursor()
        with memory_span("retrieve_long_term", agent_id=agent_identity.agent_id, project_id=project_id):
            cur.execute(
                "SELECT id, signature, value, created_at FROM memories WHERE key=? AND project_id=? ORDER BY id DESC LIMIT 10",
                (key, project_id),
            )
            rows = cur.fetchall()
            out = [{"id": r[0], "signature": r[1], "value": r[2], "created_at": r[3]} for r in rows]
            return {"ok": True, "items": out}
    finally:
        conn.close()
