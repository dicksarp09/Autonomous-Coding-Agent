"""
Langfuse Integration for Autonomous Agent Observability

Provides comprehensive observability for:
- LLM calls (token counts, latency, cost)
- Workflow execution (phase transitions, state changes)
- Tool calls (validation, execution, results)
- Memory operations (read/write, retrieval)
- Evaluation cycles (judge scores, approval gates)
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

from langfuse import Langfuse


class LangfuseObserver:
    """Central observability orchestrator using Langfuse."""

    def __init__(self):
        """Initialize Langfuse client from environment variables."""
        self.client = Langfuse(
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            base_url=os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com"),
        )
        self.current_trace = None

    def start_workflow_trace(self, workflow_id: str, user_query: str) -> None:
        """Start a trace for the entire workflow execution."""
        self.current_trace = self.client.start_span(
            name="autonomous_agent_workflow",
            input={
                "workflow_id": workflow_id,
                "user_query": user_query,
                "timestamp": datetime.now().isoformat(),
            },
            metadata={
                "workflow_type": "code_generation_and_refactoring",
                "version": "1.0",
            },
        )

    def end_workflow_trace(self, output: Dict[str, Any], metrics: Dict[str, Any]) -> None:
        """Complete the workflow trace with final output."""
        if self.current_trace:
            self.current_trace.update(
                output={
                    "final_code": output.get("code", ""),
                    "test_results": output.get("test_results", {}),
                    "approval_status": output.get("approval_status", ""),
                },
                metadata={
                    "total_iterations": metrics.get("iterations", 0),
                    "total_cost": metrics.get("cost_usd", 0.0),
                    "success": metrics.get("success", False),
                    "total_tokens": metrics.get("total_tokens", 0),
                },
            )
            self.current_trace.end()

    def track_phase_transition(
        self,
        phase_name: str,
        input_data: Dict[str, Any],
        output_data: Dict[str, Any],
        duration_ms: float,
    ) -> None:
        """Track a single phase transition in the workflow."""
        if not self.current_trace:
            return

        span = self.current_trace.start_span(
            name=f"phase_{phase_name}",
            input=input_data,
            metadata={
                "phase_type": phase_name,
                "duration_ms": duration_ms,
                "timestamp": datetime.now().isoformat(),
            },
        )
        span.update(output=output_data)
        span.end()

    def track_llm_call(
        self,
        model: str,
        prompt: str,
        response: str,
        tokens_used: Dict[str, int],
        cost_usd: float,
        duration_ms: float,
    ) -> None:
        """Track LLM API call with tokens and cost."""
        if not self.current_trace:
            return

        span = self.current_trace.start_span(
            name="llm_call",
            input={"model": model, "prompt": prompt[:200]},
            metadata={
                "model": model,
                "duration_ms": duration_ms,
                "input_tokens": tokens_used.get("input", 0),
                "output_tokens": tokens_used.get("output", 0),
                "total_tokens": tokens_used.get("total", 0),
                "cost_usd": cost_usd,
            },
        )
        span.update(output={"response": response[:500]})
        span.end()

    def track_tool_execution(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        tool_output: str,
        status: str,
        duration_ms: float,
    ) -> None:
        """Track tool execution (write_file, execute_python, etc.)."""
        if not self.current_trace:
            return

        span = self.current_trace.start_span(
            name=f"tool_{tool_name}",
            input=tool_input,
            metadata={
                "tool": tool_name,
                "status": status,
                "duration_ms": duration_ms,
                "timestamp": datetime.now().isoformat(),
            },
        )
        span.update(output={"result": tool_output[:500]})
        span.end()

    def track_evaluation(
        self,
        test_case_id: str,
        correctness_score: float,
        safety_passed: bool,
        pii_detected: bool,
        hallucination_detected: bool,
        judge_reasoning: str,
    ) -> None:
        """Track evaluation results from judge system."""
        if not self.current_trace:
            return

        span = self.current_trace.start_span(
            name="evaluation",
            input={"test_case_id": test_case_id},
            metadata={
                "correctness_score": correctness_score,
                "safety_passed": safety_passed,
                "pii_detected": pii_detected,
                "hallucination_detected": hallucination_detected,
            },
        )
        span.update(output={"judge_reasoning": judge_reasoning[:500]})
        span.end()

    def track_approval_gate(
        self,
        gate_id: str,
        reason: str,
        triggered_metrics: Dict[str, Any],
        resolution_status: Optional[str] = None,
        approved_by: Optional[str] = None,
    ) -> None:
        """Track approval gate creation and resolution."""
        if not self.current_trace:
            return

        span = self.current_trace.start_span(
            name="approval_gate",
            input={"gate_id": gate_id, "reason": reason},
            metadata={
                "triggered_at": datetime.now().isoformat(),
                "correctness_score": triggered_metrics.get("correctness_score", 0),
                "quality_score": triggered_metrics.get("quality_score", 0),
                "resolution_status": resolution_status or "PENDING",
                "approved_by": approved_by or "PENDING",
            },
        )
        span.end()

    def track_memory_operation(
        self,
        operation: str,
        memory_type: str,
        operation_details: Dict[str, Any],
        duration_ms: float,
    ) -> None:
        """Track memory read/write operations."""
        if not self.current_trace:
            return

        span = self.current_trace.start_span(
            name=f"memory_{operation}",
            input=operation_details,
            metadata={
                "operation": operation,
                "memory_type": memory_type,
                "duration_ms": duration_ms,
            },
        )
        span.end()

    def track_retry_attempt(
        self,
        attempt_number: int,
        error_message: str,
        backoff_seconds: float,
        will_retry: bool,
    ) -> None:
        """Track retry logic execution."""
        if not self.current_trace:
            return

        span = self.current_trace.start_span(
            name="retry_attempt",
            input={"attempt": attempt_number, "error": error_message},
            metadata={
                "attempt_number": attempt_number,
                "backoff_seconds": backoff_seconds,
                "will_retry": will_retry,
                "timestamp": datetime.now().isoformat(),
            },
        )
        span.end()

    def track_checkpoint(
        self,
        workflow_id: str,
        iteration: int,
        phase: str,
        state_snapshot: Dict[str, Any],
    ) -> None:
        """Track checkpoint creation."""
        if not self.current_trace:
            return

        span = self.current_trace.start_span(
            name="checkpoint",
            input={"workflow_id": workflow_id, "iteration": iteration, "phase": phase},
            metadata={
                "checkpoint_type": "full_state",
                "iteration": iteration,
                "phase": phase,
                "state_keys": list(state_snapshot.keys()),
            },
        )
        span.end()


# Global instance
observer = LangfuseObserver()


def get_observer() -> LangfuseObserver:
    """Get the global Langfuse observer instance."""
    return observer
