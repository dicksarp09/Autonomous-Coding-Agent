"""Human approval gating for live workflows.

This module manages approval requirements and gates execution based on judge evaluation results.
Approval gates prevent unsafe or low-confidence changes from being applied without human review.
"""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
import sqlite3
from ..config import DB_PATH
from ..telemetry.tracing import start_span
from ..evaluation.judge import get_approval_status, is_approval_required
import logging

logger = logging.getLogger(__name__)


class ApprovalGate(BaseModel):
    """Represents a human approval gate in a workflow."""
    gate_id: str = Field(...)
    workflow_id: str = Field(...)
    node_name: str = Field(...)  # e.g., "StaticAnalyzer", "CompletionChecker"
    triggered_at: datetime = Field(...)
    reason: str = Field(...)
    resolved: bool = Field(default=False)
    approved_by: Optional[str] = Field(default=None)
    resolved_at: Optional[datetime] = Field(default=None)
    
    class Config:
        extra = "forbid"


def ensure_approval_gate_table():
    """Create approval_gates table if it doesn't exist."""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS approval_gates (
                gate_id TEXT PRIMARY KEY,
                workflow_id TEXT,
                node_name TEXT,
                triggered_at TEXT,
                reason TEXT,
                resolved INTEGER DEFAULT 0,
                approved_by TEXT,
                resolved_at TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def create_approval_gate(workflow_id: str, node_name: str, reason: str) -> ApprovalGate:
    """Create a new approval gate for a workflow node.
    
    Args:
        workflow_id: The workflow ID requiring approval
        node_name: Name of the orchestration node triggering approval
        reason: Human-readable reason for approval requirement
        
    Returns:
        ApprovalGate object
    """
    with start_span("approval_gate.create", workflow_id=workflow_id, node_name=node_name):
        import uuid
        gate_id = str(uuid.uuid4())
        now = datetime.utcnow()
        
        gate = ApprovalGate(
            gate_id=gate_id,
            workflow_id=workflow_id,
            node_name=node_name,
            triggered_at=now,
            reason=reason,
            resolved=False,
            approved_by=None,
            resolved_at=None
        )
        
        ensure_approval_gate_table()
        conn = sqlite3.connect(str(DB_PATH))
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO approval_gates 
                (gate_id, workflow_id, node_name, triggered_at, reason, resolved, approved_by, resolved_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    gate.gate_id,
                    gate.workflow_id,
                    gate.node_name,
                    gate.triggered_at.isoformat(),
                    gate.reason,
                    1 if gate.resolved else 0,
                    gate.approved_by,
                    gate.resolved_at.isoformat() if gate.resolved_at else None
                )
            )
            conn.commit()
            logger.info("Created approval gate %s for workflow %s at node %s", gate_id, workflow_id, node_name)
        finally:
            conn.close()
        
        return gate


def resolve_approval_gate(gate_id: str, approved: bool = True, approver_id: str = "system") -> bool:
    """Resolve (approve or deny) an approval gate.
    
    Args:
        gate_id: The gate ID to resolve
        approved: Whether approval is granted (True) or denied (False)
        approver_id: ID of the human approver
        
    Returns:
        True if gate was resolved, False if gate not found
    """
    with start_span("approval_gate.resolve", gate_id=gate_id, approved=approved):
        ensure_approval_gate_table()
        conn = sqlite3.connect(str(DB_PATH))
        try:
            cur = conn.cursor()
            cur.execute("SELECT gate_id FROM approval_gates WHERE gate_id = ?", (gate_id,))
            if not cur.fetchone():
                logger.warning("Approval gate not found: %s", gate_id)
                return False
            
            now = datetime.utcnow()
            approved_by = approver_id if approved else None
            cur.execute(
                """
                UPDATE approval_gates
                SET resolved = ?, approved_by = ?, resolved_at = ?
                WHERE gate_id = ?
                """,
                (1 if approved else 0, approved_by, now.isoformat(), gate_id)
            )
            conn.commit()
            logger.info("Resolved approval gate %s: approved=%s by=%s", gate_id, approved, approver_id)
            return True
        finally:
            conn.close()


def get_approval_gate(gate_id: str) -> Optional[ApprovalGate]:
    """Retrieve an approval gate by ID.
    
    Returns:
        ApprovalGate if found, None otherwise
    """
    with start_span("approval_gate.get", gate_id=gate_id):
        ensure_approval_gate_table()
        conn = sqlite3.connect(str(DB_PATH))
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT gate_id, workflow_id, node_name, triggered_at, reason, resolved, approved_by, resolved_at
                FROM approval_gates
                WHERE gate_id = ?
                """,
                (gate_id,)
            )
            row = cur.fetchone()
            if not row:
                return None
            
            return ApprovalGate(
                gate_id=row[0],
                workflow_id=row[1],
                node_name=row[2],
                triggered_at=datetime.fromisoformat(row[3]),
                reason=row[4],
                resolved=bool(row[5]),
                approved_by=row[6],
                resolved_at=datetime.fromisoformat(row[7]) if row[7] else None
            )
        finally:
            conn.close()


def get_pending_gates(workflow_id: str) -> list[ApprovalGate]:
    """Get all unresolved approval gates for a workflow.
    
    Returns:
        List of unresolved ApprovalGate objects
    """
    with start_span("approval_gate.get_pending", workflow_id=workflow_id):
        ensure_approval_gate_table()
        conn = sqlite3.connect(str(DB_PATH))
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT gate_id, workflow_id, node_name, triggered_at, reason, resolved, approved_by, resolved_at
                FROM approval_gates
                WHERE workflow_id = ? AND resolved = 0
                ORDER BY triggered_at DESC
                """,
                (workflow_id,)
            )
            rows = cur.fetchall()
            return [
                ApprovalGate(
                    gate_id=row[0],
                    workflow_id=row[1],
                    node_name=row[2],
                    triggered_at=datetime.fromisoformat(row[3]),
                    reason=row[4],
                    resolved=bool(row[5]),
                    approved_by=row[6],
                    resolved_at=datetime.fromisoformat(row[7]) if row[7] else None
                )
                for row in rows
            ]
        finally:
            conn.close()


def should_gate_execution(workflow_id: str) -> bool:
    """Check if execution should be gated (awaiting approval) for a workflow.
    
    Returns:
        True if there are pending approval gates, False otherwise
    """
    with start_span("approval_gate.should_gate", workflow_id=workflow_id):
        pending = get_pending_gates(workflow_id)
        return len(pending) > 0
