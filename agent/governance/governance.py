from __future__ import annotations
from typing import Optional, List
from pydantic import BaseModel
import sqlite3
from ..config import DB_PATH
from datetime import datetime
import hashlib
import logging

logger = logging.getLogger(__name__)


class ApprovalRecord(BaseModel):
    approval_id: str
    workflow_id: str
    approver_id: str
    reason: Optional[str]
    timestamp: Optional[datetime]


class ApprovalStatus(BaseModel):
    """Tracks the approval status of a workflow action."""
    workflow_id: str
    action: str  # e.g., "code_generation", "memory_update"
    status: str  # "PENDING", "APPROVED", "DENIED"
    requester_id: Optional[str] = None
    approver_id: Optional[str] = None
    reason: Optional[str] = None
    timestamp: datetime


def ensure_tables():
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS approvals (
                approval_id TEXT PRIMARY KEY,
                workflow_id TEXT,
                approver_id TEXT,
                reason TEXT,
                timestamp TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS pii_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_id TEXT,
                pii_found INTEGER,
                snippet TEXT,
                timestamp TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS approval_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_id TEXT,
                action TEXT,
                status TEXT,
                requester_id TEXT,
                approver_id TEXT,
                reason TEXT,
                timestamp TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def detect_pii(text: str) -> bool:
    # Minimal heuristic PII detector: emails, SSN-like patterns, or long digit sequences
    import re

    if not text:
        return False
    email_re = re.compile(r"[\w.-]+@[\w.-]+\.[a-zA-Z]{2,}")
    ssn_re = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
    long_digits = re.compile(r"\b\d{9,}\b")
    if email_re.search(text) or ssn_re.search(text) or long_digits.search(text):
        return True
    return False


def record_pii(workflow_id: str, snippet: str) -> None:
    ensure_tables()
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO pii_audit (workflow_id, pii_found, snippet, timestamp) VALUES (?, ?, ?, ?)", (workflow_id, 1, snippet, datetime.utcnow().isoformat()))
        conn.commit()
    finally:
        conn.close()


def request_human_approval(workflow_id: str, approver_id: str, reason: Optional[str] = None) -> ApprovalRecord:
    ensure_tables()
    approval_id = hashlib.sha256(f"{workflow_id}:{approver_id}:{datetime.utcnow().isoformat()}".encode()).hexdigest()
    rec = ApprovalRecord(approval_id=approval_id, workflow_id=workflow_id, approver_id=approver_id, reason=reason, timestamp=datetime.utcnow())
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO approvals (approval_id, workflow_id, approver_id, reason, timestamp) VALUES (?, ?, ?, ?, ?)", (rec.approval_id, rec.workflow_id, rec.approver_id, rec.reason, rec.timestamp.isoformat()))
        conn.commit()
    finally:
        conn.close()
    logger.info("Recorded human approval %s for workflow %s by %s", approval_id, workflow_id, approver_id)
    return rec


def record_approval_status(workflow_id: str, action: str, status: str, requester_id: Optional[str] = None, approver_id: Optional[str] = None, reason: Optional[str] = None) -> bool:
    """Record approval status for a workflow action.
    
    Args:
        workflow_id: The workflow identifier
        action: The action being approved (e.g., "code_generation", "memory_update")
        status: Approval status ("PENDING", "APPROVED", "DENIED")
        requester_id: Optional ID of who requested the approval
        approver_id: Optional ID of who granted/denied approval
        reason: Optional reason for the decision
        
    Returns:
        True if recorded successfully
    """
    ensure_tables()
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO approval_status (workflow_id, action, status, requester_id, approver_id, reason, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (workflow_id, action, status, requester_id, approver_id, reason, datetime.utcnow().isoformat())
        )
        conn.commit()
        logger.info("Recorded approval status: workflow=%s action=%s status=%s", workflow_id, action, status)
        return True
    except Exception as e:
        logger.error("Failed to record approval status: %s", e)
        return False
    finally:
        conn.close()


def get_approval_status_for_workflow(workflow_id: str, action: Optional[str] = None) -> List[ApprovalStatus]:
    """Retrieve approval status records for a workflow.
    
    Args:
        workflow_id: The workflow identifier
        action: Optional action filter
        
    Returns:
        List of ApprovalStatus records
    """
    ensure_tables()
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()
        if action:
            cur.execute(
                """
                SELECT workflow_id, action, status, requester_id, approver_id, reason, timestamp
                FROM approval_status
                WHERE workflow_id = ? AND action = ?
                ORDER BY timestamp DESC
                """,
                (workflow_id, action)
            )
        else:
            cur.execute(
                """
                SELECT workflow_id, action, status, requester_id, approver_id, reason, timestamp
                FROM approval_status
                WHERE workflow_id = ?
                ORDER BY timestamp DESC
                """,
                (workflow_id,)
            )
        rows = cur.fetchall()
        return [
            ApprovalStatus(
                workflow_id=row[0],
                action=row[1],
                status=row[2],
                requester_id=row[3],
                approver_id=row[4],
                reason=row[5],
                timestamp=datetime.fromisoformat(row[6])
            )
            for row in rows
        ]
    finally:
        conn.close()
