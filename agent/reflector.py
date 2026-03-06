"""Reflector logic: analyze failures and propose minimal fixes.

This module performs deterministic reasoning over structured inputs and
returns a root cause hypothesis, a minimal fix strategy, and an updated plan.
No tool side-effects are performed here.
"""
from __future__ import annotations
from typing import Dict, Any, List
from .error_signature import signature_from_trace


def summarize_similar_failures(similar: List[Dict[str, Any]]) -> str:
    if not similar:
        return "no similar failures found"
    parts = []
    for s in similar:
        parts.append(f"id={s.get('id')} sig={s.get('signature')[:8]} score={s.get('score', 'n/a')}")
    return "; ".join(parts)


def reflect(state: Dict[str, Any], similar_failures: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    # deterministic heuristic-based reflection
    sim_summary = summarize_similar_failures(similar_failures or [])
    root_cause = "unknown"
    fix = "extend tests and add defensive checks"
    confidence = 0.2

    static = state.get("static_analysis_result") or {}
    exec_res = state.get("execution_result") or {}
    test_res = state.get("test_result") or {}

    if static and not static.get("ok", True):
        root_cause = "unsafe or forbidden constructs detected by static analysis"
        fix = "remove dangerous constructs, avoid eval/exec and network calls"
        confidence = 0.9
    elif exec_res and exec_res.get("returncode", 0) != 0:
        root_cause = "runtime error during execution"
        stderr = exec_res.get("stderr") or ""
        if "ImportError" in stderr:
            fix = "ensure dependencies and imports are correct"
            confidence = 0.8
        else:
            fix = "add exception handling and small repro test"
            confidence = 0.6
    elif test_res and not test_res.get("passed", False):
        root_cause = "test failures"
        fix = "inspect failing assertions and adjust code or tests"
        confidence = 0.7

    # create updated plan: keep it conservative
    updated_plan = state.get("plan", "") + "\n# Reflector suggested: " + fix

    return {
        "root_cause": root_cause,
        "fix_summary": fix,
        "updated_plan": updated_plan,
        "confidence": confidence,
        "similar_summary": sim_summary,
    }
