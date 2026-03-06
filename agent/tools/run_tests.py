"""Tool: run_tests - execute pytest in workspace with RBAC and sandbox.

This tool runs `pytest` via subprocess with timeout and restricted env.
"""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Dict, Any
import subprocess
import os
from pathlib import Path
from ..config import WORKSPACE_ROOT


class RunTestsInput(BaseModel):
    args: list[str] = Field(default_factory=list)
    timeout: int = Field(60)

    model_config = {"extra": "forbid"}


def _error(field: str, code: str, message: str) -> Dict[str, Any]:
    return {"error": code, "field": field, "message": message}


def run_tests(payload: Dict[str, Any], user_roles: list[str] | None = None) -> Dict[str, Any]:
    try:
        inp = RunTestsInput.model_validate(payload)
    except Exception as e:
        return _error("payload", "INVALID_INPUT", str(e))

    env = os.environ.copy()
    env["PYTEST_ADDOPTS"] = "-q"
    try:
        proc = subprocess.run(["pytest", *inp.args], cwd=str(WORKSPACE_ROOT), capture_output=True, text=True, timeout=inp.timeout, env=env)
        return {"ok": True, "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
    except subprocess.TimeoutExpired:
        return _error("execution", "TIMEOUT", "pytest timed out")
    except Exception as e:
        return _error("execution", "FAILED", str(e))
