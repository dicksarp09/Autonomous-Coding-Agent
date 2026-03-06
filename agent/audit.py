"""Audit module: append-only audit entries persisted to SQLite."""
from __future__ import annotations
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
import hashlib
from .db import get_conn


class AuditEntry(BaseModel):
    action: str
    agent_id: str
    approved_by: Optional[str] = None
    timestamp: datetime
    immutable_hash: str


def create_audit_entry(action: str, agent_id: str, approved_by: Optional[str] = None) -> AuditEntry:
    ts = datetime.utcnow()
    payload = f"{action}|{agent_id}|{approved_by}|{ts.isoformat()}"
    immutable_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    entry = AuditEntry(action=action, agent_id=agent_id, approved_by=approved_by, timestamp=ts, immutable_hash=immutable_hash)

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS security_audits (id INTEGER PRIMARY KEY, action TEXT, agent_id TEXT, approved_by TEXT, timestamp TEXT, immutable_hash TEXT)")
        cur.execute("INSERT INTO security_audits (action, agent_id, approved_by, timestamp, immutable_hash) VALUES (?, ?, ?, ?, ?)", (action, agent_id, approved_by, ts.isoformat(), immutable_hash))
        conn.commit()
    finally:
        conn.close()

    return entry
