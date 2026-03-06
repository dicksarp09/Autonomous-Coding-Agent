from __future__ import annotations
from typing import Optional, Dict, Any
import time
import uuid
from .golden_dataset import list_cases
from .judge import mock_judge_evaluate, evaluate_with_human_approval, get_approval_status
from .metrics import WorkflowMetrics, persist_metrics
from ..checkpoint import save_state
from ..telemetry.tracing import start_span
from ..governance.governance import detect_pii, record_pii, request_human_approval
import logging

logger = logging.getLogger(__name__)


def run_on_golden(project_ns: str = "default", max_iterations: int = 5, use_human_approval: bool = True, approver_id: str = "evaluator"):
    """Run evaluation pipeline on golden dataset with optional human approval gating.
    
    Args:
        project_ns: Project namespace for golden dataset retrieval
        max_iterations: Maximum iterations for agent to attempt fixes
        use_human_approval: Whether to require human approval for risky changes (default True)
        approver_id: ID of the human approver for approval requests
    
    Returns:
        List of results including workflow_id, case_id, success, judge evaluation, and approval status
    """
    cases = list_cases(project_ns=project_ns)
    results = []
    for case in cases:
        workflow_id = str(uuid.uuid4())
        start = time.time()
        # simplistic workflow: pretend the agent tries to fix code up to max_iterations
        iterations = 1
        success = False
        code_before = case.initial_code
        code_after = case.expected_code if iterations <= max_iterations else case.initial_code

        # PII detection
        if detect_pii(code_before) or detect_pii(code_after):
            record_pii(workflow_id, code_before)

        # persist checkpoint
        save_state({"workflow_id": workflow_id, "case_id": case.test_id, "iteration": iterations})

        # run judge with optional human approval gating
        judge_eval = None
        approval = None
        
        if use_human_approval:
            with start_span("evaluate_with_approval", workflow_id=workflow_id, case_id=case.test_id):
                judge_eval, approval = evaluate_with_human_approval(
                    workflow_id, 
                    code_before, 
                    code_after, 
                    approver_id=approver_id,
                    safety_threshold=True,
                    correctness_threshold=0.75
                )
        else:
            judge_eval = mock_judge_evaluate(workflow_id, code_before, code_after)

        # determine success heuristically
        success = judge_eval.correctness_score >= 0.75 and judge_eval.safety_passed
        
        # if approval is required and not present, mark as requiring approval
        approval_required = approval is not None
        approval_status = "PENDING_APPROVAL" if approval_required else "APPROVED"

        latency = time.time() - start
        metrics = WorkflowMetrics(
            workflow_id=workflow_id,
            iterations=iterations,
            success=success,
            cost=0.0,
            latency=latency,
            repeated_error=False,
            injection_detected=False,
        )
        persist_metrics(metrics)
        
        result = {
            "workflow_id": workflow_id, 
            "case_id": case.test_id, 
            "success": success, 
            "judge": judge_eval.model_dump(),
            "approval_required": approval_required,
            "approval_status": approval_status,
        }
        
        if approval:
            result["approval"] = approval.model_dump()
        
        results.append(result)
        logger.info("Finished golden test %s -> success=%s approval_required=%s", case.test_id, success, approval_required)

    return results
