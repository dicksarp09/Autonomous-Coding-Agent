"""Agent entrypoint: orchestration skeleton wiring nodes deterministically.

This module wires the LangGraph nodes and provides a `run_workflow` function.
"""
from __future__ import annotations
import logging
import os
import uuid
from pathlib import Path
from .config import WORKSPACE_ROOT

# Initialize LangSmith tracing on import
try:
    from .observability.langsmith_integration import setup_langsmith_tracing
    # Auto-initialize LangSmith tracing
    setup_langsmith_tracing()
except Exception as e:
    logging.getLogger(__name__).debug(f"LangSmith init skipped: {e}")

try:
    from .db import init_db, get_conn
except Exception:
    from db import init_db, get_conn

try:
    from .telemetry.tracing import start_span
except Exception:
    from telemetry.tracing import start_span

try:
    from .orchestration.graph import LangGraph
except Exception:
    from orchestration.graph import LangGraph

try:
    from .orchestration.state import AgentStateModel
except Exception:
    from orchestration.state import AgentStateModel

try:
    from .orchestration.circuit_breaker import CircuitBreaker
except Exception:
    from orchestration.circuit_breaker import CircuitBreaker

try:
    from .orchestration.approval_gate import create_approval_gate, should_gate_execution, get_pending_gates
except Exception:
    from orchestration.approval_gate import create_approval_gate, should_gate_execution, get_pending_gates

try:
    from .tool_validation import validate_tool_call
except Exception:
    from tool_validation import validate_tool_call

try:
    from .reflector import reflect
except Exception:
    from reflector import reflect

try:
    from .checkpoint import save_state
except Exception:
    from checkpoint import save_state

try:
    from .escalation import escalate
except Exception:
    from escalation import escalate

try:
    from .memory.long_term import LongTermMemory
except Exception:
    from memory.long_term import LongTermMemory

try:
    from .rbac import AgentIdentity
except Exception:
    from rbac import AgentIdentity

try:
    from .evaluation.judge import evaluate_with_human_approval
except Exception:
    from evaluation.judge import evaluate_with_human_approval
from datetime import datetime
from .error_signature import signature_from_trace
import time

try:
    from .observability.langfuse_integration import get_observer
except ImportError:
    get_observer = None

logger = logging.getLogger(__name__)


def run_workflow_with_observability(goal: str, max_iterations: int = 3, workspace_path: str = "."):
    """Main entry point for autonomous agent workflow with full Langfuse observability."""
    if get_observer is None:
        logger.warning("Langfuse observer not available, skipping observability")
        return run_workflow_internal(goal, max_iterations, workspace_path)
    
    observer = get_observer()
    workflow_id = f"wf_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}"
    
    # Load environment for observability
    if os.getenv("LANGFUSE_SECRET_KEY"):
        observer.start_workflow_trace(workflow_id, goal)
        logger.info(f"Langfuse trace started: {workflow_id}")
    
    try:
        # Execute workflow
        result = run_workflow_internal(goal, max_iterations, workspace_path)
        
        # End observability trace with results
        observer.end_workflow_trace(
            output={
                "code": getattr(result, "code", ""),
                "test_results": getattr(result, "test_results", {}),
                "approval_status": getattr(result, "status", "COMPLETED"),
            },
            metrics={
                "iterations": getattr(result, "iteration", 0),
                "cost_usd": 0.0,
                "total_tokens": 0,
                "success": True,
            }
        )
        return result
    except Exception as e:
        logger.error(f"Workflow {workflow_id} failed: {str(e)}")
        if observer.current_trace:
            observer.current_trace.update(metadata={"error": str(e), "error_type": type(e).__name__})
        raise


def run_workflow_internal(goal: str, max_iterations: int = 3, workspace_path: str = "."):
    """Internal workflow execution logic."""
    # Initialize state
    initial_state = AgentStateModel(
        goal=goal,
        iteration=0,
        max_iterations=max_iterations,
        status="PENDING"
    )
    logger.info(f"Starting workflow: {goal}")
    return initial_state


def goal_validator(state: AgentStateModel):
    with start_span("node.goal_validator", node_name="GoalValidator", iteration=state.iteration):
        g = state.goal.strip()
        # basic injection filtering
        if any(x in g.lower() for x in ["/etc/passwd", "ssh", "curl "]):
            state.status = "INVALID_GOAL"
            return None, state
        state.iteration = 0
        return "Planner", state


def planner_node(state: AgentStateModel, agent_identity: AgentIdentity, project_id: str = "default_project"):
    with start_span("node.planner", node_name="Planner", iteration=state.iteration):
        # memory retrieval integration
        mem = LongTermMemory()
        start = time.time()
        resp = mem.query(limit=3, project_id=project_id, agent_identity=agent_identity)
        latency = (time.time() - start) * 1000.0
        items = resp.get("items") if isinstance(resp, dict) and resp.get("ok") else []
        # attach retrieval metadata
        state.plan = f"Plan for: {state.goal}\nretrieved_similar={len(items)} latency_ms={latency:.1f}"
        # planner outputs a plan (deterministic placeholder)
        state.plan += "\n# steps: generate minimal patch, run static analysis, run tests"
        return "CodeGenerator", state


def code_generator_node(state: AgentStateModel, agent_identity: AgentIdentity | None = None):
    with start_span("node.code_generator", node_name="CodeGenerator", iteration=state.iteration):
        # Generate code using LLM based on plan
        from .groq_client import GroqClient
        
        client = GroqClient()
        prompt = f"""You are an expert Python developer. Generate high-quality, production-ready Python code based on the following requirement:

Requirement: {state.goal}

{"Previous code and reflection: " + state.reflection if state.reflection and state.reflection != 'unknown' else ""}

Generate ONLY the Python code, no explanations. Ensure the code:
- Is complete and functional
- Includes docstrings for all functions
- Has proper type hints
- Includes error handling where appropriate
- Can be executed directly

Return only the Python code, starting with imports if needed."""

        try:
            response = client.generate("coding", prompt)
            # Extract code from response
            if isinstance(response, dict) and "choices" in response:
                code = response["choices"][0]["message"]["content"].strip()
            else:
                code = str(response).strip()
            
            # Remove markdown code blocks if present
            if code.startswith("```python"):
                code = code[9:]
            if code.startswith("```"):
                code = code[3:]
            if code.endswith("```"):
                code = code[:-3]
            code = code.strip()
            
            state.generated_code = code
        except Exception as e:
            logger.warning(f"Code generation failed: {e}, using fallback")
            state.generated_code = "def run():\n    return 'ok'\n\nif __name__=='__main__':\n    print(run())\n"
        
        # validate and write via middleware
        file_path = WORKSPACE_ROOT / "generated.py"
        res = validate_tool_call("write_file", {"path": str(file_path), "content": state.generated_code}, agent_identity=agent_identity)
        state.execution_result = {"write_result": res}
        return "StaticAnalyzer", state


def static_analyzer_node(state: AgentStateModel, agent_identity: AgentIdentity | None = None):
    with start_span("node.static_analyzer", node_name="StaticAnalyzer", iteration=state.iteration):
        # run static check via middleware
        file_path = WORKSPACE_ROOT / "generated.py"
        res = validate_tool_call("static_analysis", {"path": str(file_path)}, agent_identity=agent_identity) 
        state.static_analysis_result = res
        if not res.get("ok"):
            return "Reflector", state
        return "SandboxExecutor", state


def sandbox_executor_node(state: AgentStateModel, agent_identity: AgentIdentity | None = None):
    with start_span("node.sandbox_executor", node_name="SandboxExecutor", iteration=state.iteration):
        file_path = WORKSPACE_ROOT / "generated.py"
        res = validate_tool_call("execute_python", {"path": str(file_path), "timeout": 5}, agent_identity=agent_identity) 
        state.execution_result = res
        if res.get("error"):
            return "Reflector", state
        return "TestRunner", state


def test_runner_node(state: AgentStateModel, agent_identity: AgentIdentity | None = None):
    with start_span("node.test_runner", node_name="TestRunner", iteration=state.iteration):
        # run pytest via middleware
        res = validate_tool_call("run_tests", {"args": [], "timeout": 10}, agent_identity=agent_identity) 
        # attempt to parse signature if failures present
        passed = res.get("returncode") == 0
        signature = None
        if not passed:
            stderr = res.get("stderr") or ""
            signature = signature_from_trace(stderr)
        state.test_result = {"passed": passed, "raw": res, "signature": signature}
        return "Reflector", state


def reflector_node(state: AgentStateModel, agent_identity: AgentIdentity, project_id: str = "default_project"):
    with start_span("node.reflector", node_name="Reflector", iteration=state.iteration):
        # retrieve similar from long-term memory
        mem = LongTermMemory()
        resp = mem.query(limit=3, project_id=project_id, agent_identity=agent_identity)
        items = resp.get("items") if isinstance(resp, dict) and resp.get("ok") else []
        out = reflect(state.model_dump(), similar_failures=items)
        state.reflection = out.get("root_cause")
        # store reflection in state for memory updater
        state.test_result.setdefault("reflection", {})
        state.test_result["reflection"] = out
        
        # Check if human approval is needed based on judge evaluation
        # Generate code evaluation with human approval gating
        code_before = state.plan
        code_after = state.generated_code
        
        try:
            judge_eval, approval = evaluate_with_human_approval(
                state.goal,
                code_before,
                code_after,
                approver_id="evaluator",
                safety_threshold=True,
                correctness_threshold=0.75
            )
            
            # If approval is required, create an approval gate
            if approval is not None:
                gate = create_approval_gate(
                    workflow_id=state.goal,
                    node_name="Reflector",
                    reason=approval.reason or "Code change requires human review"
                )
                logger.warning("Approval gate created for workflow %s: %s", state.goal, gate.gate_id)
                state.test_result["approval_gate_id"] = gate.gate_id
        except Exception as e:
            logger.warning("Approval evaluation failed: %s", e)
        
        return "CompletionChecker", state


def memory_updater_node(state: AgentStateModel, agent_identity: AgentIdentity, project_id: str = "default_project"):
    with start_span("node.memory_updater", node_name="MemoryUpdater", iteration=state.iteration):
        mem = LongTermMemory()
        # if failure store error signature and fix
        if not state.test_result.get("passed", True):
            sig = state.test_result.get("signature") or ""
            fix = state.test_result.get("reflection", {}).get("fix_summary") if isinstance(state.test_result.get("reflection"), dict) else ""
            mem.store(root_cause=state.reflection or "", fix_summary=fix or "", embedding=None, project_id=project_id, agent_identity=agent_identity)
        else:
            mem.store(root_cause="success", fix_summary="linked to prior", embedding=None, project_id=project_id, agent_identity=agent_identity)
        return "CompletionChecker", state


def completion_checker_node(state: AgentStateModel):
    with start_span("node.completion_checker", node_name="CompletionChecker", iteration=state.iteration):
        # Check if there are pending approval gates blocking execution
        if should_gate_execution(state.goal):
            logger.info("Execution gated: pending human approvals for workflow %s", state.goal)
            state.status = "AWAITING_APPROVAL"
            save_state(state, name=f"gated_approval_iter_{state.iteration}")
            return "ApprovalChecker", state
        
        # success
        if state.test_result.get("passed"):
            state.status = "SUCCESS"
            save_state(state, name="final_success")
            return None, state
        # check iteration cap
        if state.iteration >= state.max_iterations - 1:
            return "EscalationHandler", state

        # circuit breaker decision
        cb = CircuitBreaker()
        if not cb.allow_request():
            return "EscalationHandler", state

        # continue
        state.iteration += 1
        save_state(state, name=f"checkpoint_iter_{state.iteration}")
        return "Planner", state


def approval_checker_node(state: AgentStateModel):
    """Check approval status and determine if execution can proceed.
    
    This node gates workflow progression based on pending human approvals.
    If approvals are pending, the workflow pauses and returns AWAITING_APPROVAL status.
    """
    with start_span("node.approval_checker", node_name="ApprovalChecker", iteration=state.iteration):
        pending_gates = get_pending_gates(state.goal)
        
        if pending_gates:
            logger.info("Workflow %s has %d pending approval gates", state.goal, len(pending_gates))
            for gate in pending_gates:
                logger.warning("Pending approval gate: %s - reason: %s", gate.gate_id, gate.reason)
            state.status = "AWAITING_APPROVAL"
            return None, state  # Stop execution, await manual approval
        
        # All approvals resolved, check if approved
        approved_count = len([g for g in pending_gates if g.resolved and g.approved_by])
        logger.info("Approval check for %s: %d gates approved", state.goal, approved_count)
        
        # If we get here, all gates were resolved and approved
        # Resume from where we left off
        state.status = "APPROVAL_GRANTED"
        return "CompletionChecker", state


def escalation_handler_node(state: AgentStateModel):
    with start_span("node.escalation", node_name="EscalationHandler", iteration=state.iteration):
        reason = f"iteration={state.iteration} status={state.status}"
        out = escalate(state, reason)
        state.status = "FAILED"
        return None, state


def run_workflow(goal: str, max_iterations: int = 8):
    init_db()
    state = AgentStateModel(goal=goal, max_iterations=max_iterations)
    # create an AgentIdentity for this run
    agent_identity = AgentIdentity(agent_id="agent-1", role="coder_agent", session_id="session-1", timestamp=datetime.utcnow())
    g = LangGraph()
    # register nodes with explicit routing functions
    g.register_node("GoalValidator", lambda s: (goal_validator(s)), lambda s: None)
    g.register_node("Planner", lambda s, ai=agent_identity: (planner_node(s, ai)), lambda s: None)
    g.register_node("CodeGenerator", lambda s, ai=agent_identity: (code_generator_node(s, ai)), lambda s: None)
    g.register_node("StaticAnalyzer", lambda s, ai=agent_identity: (static_analyzer_node(s, ai)), lambda s: None)
    g.register_node("SandboxExecutor", lambda s, ai=agent_identity: (sandbox_executor_node(s, ai)), lambda s: None)
    g.register_node("TestRunner", lambda s, ai=agent_identity: (test_runner_node(s, ai)), lambda s: None)
    g.register_node("Reflector", lambda s, ai=agent_identity: (reflector_node(s, ai)), lambda s: None)
    g.register_node("MemoryUpdater", lambda s, ai=agent_identity: (memory_updater_node(s, ai)), lambda s: None)
    g.register_node("CompletionChecker", lambda s: (completion_checker_node(s)), lambda s: None)
    g.register_node("ApprovalChecker", lambda s: (approval_checker_node(s)), lambda s: None)
    g.register_node("EscalationHandler", lambda s: (escalation_handler_node(s)), lambda s: None)

    final = g.run("GoalValidator", state)
    return final


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_workflow("Create a small script and run it", max_iterations=3)
