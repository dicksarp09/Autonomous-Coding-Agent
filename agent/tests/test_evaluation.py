from __future__ import annotations
import pytest
from agent.evaluation.golden_dataset import GoldenTestCase, insert_case, list_cases
from agent.evaluation.metrics import WorkflowMetrics, persist_metrics, ensure_table
from agent.evaluation.judge import mock_judge_evaluate, ensure_table as ensure_judge, evaluate_with_human_approval, is_approval_required, get_approval_status
from agent.evaluation.pipeline import run_on_golden
from agent.governance.governance import detect_pii, request_human_approval, record_approval_status, get_approval_status_for_workflow
from agent.orchestration.approval_gate import create_approval_gate, resolve_approval_gate, get_approval_gate, get_pending_gates, should_gate_execution
from datetime import datetime


def test_golden_dataset_roundtrip(tmp_path, monkeypatch):
    # Insert and list a case
    case = GoldenTestCase(
        test_id="g1",
        description="simple fix",
        initial_code="print('hello')",
        expected_code="print('hello')",
        expected_tests_passed=True,
        complexity="simple",
    )
    insert_case(case, project_ns="test")
    cases = list_cases(project_ns="test")
    assert any(c.test_id == "g1" for c in cases)


def test_metrics_persist():
    ensure_table()
    m = WorkflowMetrics(workflow_id="w1", iterations=1, success=True, cost=0.0, latency=0.1, repeated_error=False, injection_detected=False)
    persist_metrics(m)


def test_mock_judge_and_pii():
    ensure_judge()
    ev = mock_judge_evaluate("wf1", "a", "b")
    assert ev.correctness_score >= 0.0
    assert detect_pii("no pii here") is False
    assert detect_pii("email@example.com") is True


def test_human_approval_registry():
    rec = request_human_approval("wf-x", "approver-1", reason="needed for delete")
    assert rec.approval_id is not None


def test_evaluate_triggers_human_approval(monkeypatch):
    # Force remote_judge_evaluate to return an unsafe/low-confidence evaluation
    from agent.evaluation.judge import JudgeEvaluation

    unsafe = JudgeEvaluation(
        workflow_id="wf-unsafe",
        correctness_score=0.2,
        style_score=0.3,
        hallucination_detected=True,
        safety_passed=False,
        aligned_with_human=False,
    )

    monkeypatch.setattr("agent.evaluation.judge.remote_judge_evaluate", lambda wid, a, b: unsafe)

    ev, approval = evaluate_with_human_approval("wf-unsafe", "a", "b", approver_id="approver-1")
    assert ev.workflow_id == "wf-unsafe"
    assert ev.safety_passed is False
    assert approval is not None


def test_approval_gating():
    """Test approval gate creation and resolution."""
    workflow_id = "wf-test-gate"
    gate = create_approval_gate(workflow_id, "TestNode", "Safety check required")
    assert gate.gate_id is not None
    assert gate.workflow_id == workflow_id
    assert not gate.resolved
    
    # Retrieve the gate
    retrieved = get_approval_gate(gate.gate_id)
    assert retrieved is not None
    assert retrieved.workflow_id == workflow_id
    
    # Get pending gates
    pending = get_pending_gates(workflow_id)
    assert len(pending) > 0
    assert any(g.gate_id == gate.gate_id for g in pending)
    
    # Check if execution should be gated
    assert should_gate_execution(workflow_id)
    
    # Resolve the gate
    resolved = resolve_approval_gate(gate.gate_id, approved=True, approver_id="human-reviewer")
    assert resolved
    
    # Verify gate is no longer pending
    pending_after = get_pending_gates(workflow_id)
    assert not any(g.gate_id == gate.gate_id for g in pending_after)


def test_approval_status_tracking():
    """Test approval status recording and retrieval."""
    workflow_id = "wf-test-status"
    
    # Record pending approval
    success = record_approval_status(
        workflow_id,
        "code_generation",
        "PENDING",
        requester_id="agent-1",
        reason="Low confidence"
    )
    assert success
    
    # Retrieve status
    statuses = get_approval_status_for_workflow(workflow_id)
    assert len(statuses) > 0
    assert any(s.action == "code_generation" and s.status == "PENDING" for s in statuses)
    
    # Record approval
    success = record_approval_status(
        workflow_id,
        "code_generation",
        "APPROVED",
        requester_id="agent-1",
        approver_id="human-reviewer",
        reason="Approved after review"
    )
    assert success
    
    # Retrieve updated status
    statuses = get_approval_status_for_workflow(workflow_id, action="code_generation")
    assert len(statuses) >= 2
    assert any(s.status == "APPROVED" for s in statuses)


def test_evaluate_with_approval_conditions():
    """Test evaluate_with_human_approval with different thresholds."""
    from agent.evaluation.judge import JudgeEvaluation
    import uuid
    
    wid = str(uuid.uuid4())
    
    # Case 1: Low correctness score should trigger approval
    ev = JudgeEvaluation(
        workflow_id=wid,
        correctness_score=0.5,  # Below default threshold of 0.75
        style_score=0.6,
        hallucination_detected=False,
        safety_passed=True,
        aligned_with_human=False
    )
    
    # Manually insert this to mock remote_judge_evaluate
    from agent.evaluation.judge import persist_judge
    persist_judge(ev)
    
    # Now evaluate with human approval
    result_ev, approval = evaluate_with_human_approval(
        wid,
        "old_code",
        "new_code",
        approver_id="test-approver",
        correctness_threshold=0.75
    )
    
    assert approval is not None
    assert "Correctness score" in approval.reason


def test_pipeline_with_approval(monkeypatch):
    """Test golden dataset pipeline with human approval."""
    # Insert a test case
    case = GoldenTestCase(
        test_id="approval-test",
        description="approval test case",
        initial_code="def foo(): pass",
        expected_code="def foo(): return 42",
        expected_tests_passed=True,
        complexity="simple",
    )
    insert_case(case, project_ns="approval_test")
    
    # Run pipeline with approval enabled
    results = run_on_golden(project_ns="approval_test", use_human_approval=True)
    
    assert len(results) > 0
    result = results[0]
    assert "approval_status" in result
    assert result["approval_status"] in ["APPROVED", "PENDING_APPROVAL"]


def test_approval_required_check():
    """Test is_approval_required function."""
    import uuid
    wid = str(uuid.uuid4())
    
    # Initially no approval should be required
    assert not is_approval_required(wid)
    
    # Request approval
    request_human_approval(wid, "test-approver", reason="Test approval")
    
    # Now approval should be required
    assert is_approval_required(wid)
    
    # Get approval status
    status = get_approval_status(wid)
    assert status is not None
    assert status.workflow_id == wid

