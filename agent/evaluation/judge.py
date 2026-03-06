from __future__ import annotations
from pydantic import BaseModel
from typing import Optional, Tuple
from datetime import datetime
import sqlite3
from ..config import DB_PATH, MODEL_CONFIGS
from ..telemetry.tracing import start_span
from ..groq_client import GroqClient, GroqError
from ..governance.governance import detect_pii, request_human_approval, ApprovalRecord, record_approval_status
import logging
import os

logger = logging.getLogger(__name__)
AUTO_APPROVE = os.getenv("AUTO_APPROVE", "0").lower() in ("1", "true", "yes")


class JudgeEvaluation(BaseModel):
    workflow_id: str
    correctness_score: float
    style_score: float
    hallucination_detected: bool
    safety_passed: bool
    aligned_with_human: bool
    timestamp: Optional[datetime] = None


def ensure_table():
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS judge_evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_id TEXT,
                correctness_score REAL,
                style_score REAL,
                hallucination_detected INTEGER,
                safety_passed INTEGER,
                aligned_with_human INTEGER,
                timestamp TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def persist_judge(eval: JudgeEvaluation) -> None:
    ensure_table()
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO judge_evaluations (workflow_id, correctness_score, style_score, hallucination_detected, safety_passed, aligned_with_human, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                eval.workflow_id,
                eval.correctness_score,
                eval.style_score,
                1 if eval.hallucination_detected else 0,
                1 if eval.safety_passed else 0,
                1 if eval.aligned_with_human else 0,
                (eval.timestamp.isoformat() if eval.timestamp else datetime.utcnow().isoformat()),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def mock_judge_evaluate(workflow_id: str, code_before: str, code_after: str) -> JudgeEvaluation:
    # Minimal heuristic judge for offline evaluation.
    with start_span("judge.mock_evaluate"):
        correctness = 0.0
        style = 0.5
        hallucination = False
        safety = True
        aligned = False

        code_before_stripped = code_before.strip() if code_before else ""
        code_after_stripped = code_after.strip() if code_after else ""
        
        # Detect code generation vs. modification
        is_generation = len(code_before_stripped) < 100  # Empty or small = generation task
        
        logger.warning(f"DEBUG: code_before length={len(code_before_stripped)}, code_after length={len(code_after_stripped)}, is_generation={is_generation}")
        
        if is_generation:
            # For code generation tasks, score based on code quality metrics
            # Check for type hints, docstrings, error handling, imports
            has_type_hints = ":" in code_after and "->" in code_after
            has_docstrings = '"""' in code_after or "'''" in code_after
            has_error_handling = "try:" in code_after or "except" in code_after or "ValueError" in code_after
            has_logging = "logging" in code_after or "logger" in code_after
            has_imports = code_after.count("import") >= 2
            
            quality_score = sum([
                has_type_hints,
                has_docstrings,
                has_error_handling,
                has_logging,
                has_imports,
            ]) / 5.0
            
            # For generation, correctness is based on code quality + length
            code_length = len(code_after_stripped.split('\n'))
            length_bonus = min(0.2, code_length / 500.0)  # Bonus for substantial code (up to 500 lines)
            
            correctness = min(0.95, quality_score * 0.75 + length_bonus)
            style = quality_score
            aligned = correctness >= 0.7
            
            logger.info(
                "Code generation detected: type_hints=%s, docstrings=%s, error_handling=%s, logging=%s, imports=%s, quality=%.2f, correctness=%.2f",
                has_type_hints, has_docstrings, has_error_handling, has_logging, has_imports, quality_score, correctness
            )
        else:
            # For code modification, compare before/after
            if code_before_stripped == code_after_stripped:
                correctness = 0.0
                aligned = False
            else:
                correctness = 0.8
                style = 0.7
                aligned = True

        ev = JudgeEvaluation(
            workflow_id=workflow_id,
            correctness_score=correctness,
            style_score=style,
            hallucination_detected=hallucination,
            safety_passed=safety,
            aligned_with_human=aligned,
            timestamp=datetime.utcnow(),
        )
        persist_judge(eval=ev)
        logger.info("Mock judge evaluated workflow %s: correctness=%.2f", workflow_id, correctness)
        return ev


def remote_judge_evaluate(workflow_id: str, code_before: str, code_after: str) -> JudgeEvaluation:
    """Attempt to call configured judge model via GroqClient or environment QWEN endpoints.

    Falls back to `mock_judge_evaluate` on any error.
    """
    with start_span("judge.remote_evaluate"):
        cfg = MODEL_CONFIGS.get("judge", {})
        prompt = f"Evaluate the following code change for correctness, style, hallucination, and safety.\n--- BEFORE:\n{code_before}\n--- AFTER:\n{code_after}\nRespond with ONLY a JSON object (no other text) containing: correctness_score (0-1), style_score (0-1), hallucination_detected (bool), safety_passed (bool), aligned_with_human (bool)."
        try:
            client = GroqClient()
            resp = client.generate("judge", prompt, max_tokens=cfg.get("max_tokens", 200))
            
            # Extract content from Groq response structure
            import json
            content = resp
            if isinstance(resp, dict) and 'choices' in resp:
                content = resp['choices'][0]['message']['content']
            
            # Parse JSON from content
            try:
                if isinstance(content, str):
                    parsed = json.loads(content)
                else:
                    parsed = content
            except (json.JSONDecodeError, ValueError):
                logger.warning("Could not parse JSON from judge response: %s", str(content)[:100])
                return mock_judge_evaluate(workflow_id, code_before, code_after)
            
            # Extract evaluation scores
            if isinstance(parsed, dict):
                correctness = float(parsed.get("correctness_score") or 0.0)
                style = float(parsed.get("style_score") or 0.5)
                hallucination = bool(parsed.get("hallucination_detected", False))
                safety = bool(parsed.get("safety_passed", True))
                aligned = bool(parsed.get("aligned_with_human", False))
                
                logger.info("Remote judge response parsed successfully: correctness=%.2f", correctness)
            else:
                logger.warning("Judge response is not a dict: %s", type(parsed))
                return mock_judge_evaluate(workflow_id, code_before, code_after)

            ev = JudgeEvaluation(
                workflow_id=workflow_id,
                correctness_score=correctness,
                style_score=style,
                hallucination_detected=hallucination,
                safety_passed=safety,
                aligned_with_human=aligned,
                timestamp=datetime.utcnow(),
            )
            persist_judge(eval=ev)
            return ev
        except (GroqError, Exception) as e:
            logger.warning("Remote judge failed, falling back to mock: %s", e)
            return mock_judge_evaluate(workflow_id, code_before, code_after)


def evaluate_with_human_approval(workflow_id: str, code_before: str, code_after: str, approver_id: str = "human-operator", safety_threshold: bool = True, correctness_threshold: float = 0.75) -> Tuple[JudgeEvaluation, Optional[ApprovalRecord]]:
    """Evaluate change and request human approval when judge flags safety failures or low confidence.

    Args:
        workflow_id: Unique workflow identifier
        code_before: Original code
        code_after: Generated/modified code
        approver_id: ID of the approver (human operator identifier)
        safety_threshold: Whether to require safety_passed=True (default True)
        correctness_threshold: Minimum correctness score required (default 0.75)

    Returns:
        (JudgeEvaluation, ApprovalRecord or None) where ApprovalRecord is present if human approval is required.
    """
    with start_span("evaluate_with_human_approval", workflow_id=workflow_id, correctness_threshold=correctness_threshold):
        # Try remote judge first
        ev = remote_judge_evaluate(workflow_id, code_before, code_after)

        approval = None
        approval_required = False
        approval_reasons = []

        # Heuristic: require approval if safety fails or correctness below threshold or PII detected
        if safety_threshold and not ev.safety_passed:
            approval_required = True
            approval_reasons.append("Judge flagged safety issues")

        if ev.correctness_score < correctness_threshold:
            approval_required = True
            approval_reasons.append(f"Correctness score {ev.correctness_score:.2f} below threshold {correctness_threshold}")

        if detect_pii(code_after):
            approval_required = True
            approval_reasons.append("PII detected in generated code")

        if ev.hallucination_detected:
            approval_required = True
            approval_reasons.append("Hallucination detected in generated code")

        if approval_required:
            reason = "; ".join(approval_reasons)
            logger.warning("Human approval required for workflow %s: %s", workflow_id, reason)
            # If AUTO_APPROVE is enabled, record an approved status and skip creating a pending approval
            if AUTO_APPROVE:
                try:
                    record_approval_status(workflow_id, action="code_generation", status="APPROVED", requester_id="system", approver_id=approver_id, reason="Auto-approved via AUTO_APPROVE")
                    logger.info("AUTO_APPROVE enabled - auto-approved workflow %s", workflow_id)
                    approval = None
                except Exception as e:
                    logger.warning("AUTO_APPROVE failed to record approval status: %s", e)
                    # Fallback to creating a pending approval
                    approval = request_human_approval(workflow_id, approver_id, reason=reason)
                    logger.info("Approval record created: %s", approval.approval_id)
            else:
                approval = request_human_approval(workflow_id, approver_id, reason=reason)
                logger.info("Approval record created: %s", approval.approval_id)

        logger.info("Evaluate with human approval: workflow=%s approval_required=%s", workflow_id, approval_required)
        return ev, approval


def is_approval_required(workflow_id: str) -> bool:
    """Check if a workflow has pending approval requests.
    
    Returns True if approval is required and not yet granted.
    """
    with start_span("is_approval_required", workflow_id=workflow_id):
        conn = sqlite3.connect(str(DB_PATH))
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM approvals WHERE workflow_id = ?", (workflow_id,))
            count = cur.fetchone()[0]
            return count > 0
        finally:
            conn.close()


def get_approval_status(workflow_id: str) -> Optional[ApprovalRecord]:
    """Retrieve the most recent approval record for a workflow.
    
    Returns ApprovalRecord if one exists, None otherwise.
    """
    with start_span("get_approval_status", workflow_id=workflow_id):
        conn = sqlite3.connect(str(DB_PATH))
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT approval_id, workflow_id, approver_id, reason, timestamp FROM approvals WHERE workflow_id = ? ORDER BY timestamp DESC LIMIT 1",
                (workflow_id,)
            )
            row = cur.fetchone()
            if not row:
                return None
            return ApprovalRecord(
                approval_id=row[0],
                workflow_id=row[1],
                approver_id=row[2],
                reason=row[3],
                timestamp=datetime.fromisoformat(row[4]) if row[4] else None
            )
        finally:
            conn.close()

