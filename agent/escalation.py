"""Escalation handler: mark workflow failed, write audit entry, persist final state."""
from __future__ import annotations
from .db import get_conn
from .checkpoint import save_state
from typing import Any
import logging

logger = logging.getLogger(__name__)


def escalate(state: Any, reason: str) -> dict:
    # Persist audit
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO audit_logs (component, level, message) VALUES (?, ?, ?)", ("escalation", "ERROR", reason))
        conn.commit()
    finally:
        conn.close()

    path = save_state(state, name="escalation_final")
    logger.error("Escalation: %s; state saved to %s", reason, path)
    return {"ok": False, "reason": reason, "checkpoint": str(path)}
