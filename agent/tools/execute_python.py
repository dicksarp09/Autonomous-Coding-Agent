"""Tool: execute_python - runs a python file inside the sandbox with strict inputs."""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Dict, Any
from pathlib import Path
from ..config import WORKSPACE_ROOT
from ..sandbox import execute_in_sandbox, SandboxError


class ExecutePythonInput(BaseModel):
    path: str = Field(...)
    timeout: int = Field(10)
    memory_limit_mb: int | None = None

    model_config = {"extra": "forbid"}


def _error(field: str, code: str, message: str) -> Dict[str, Any]:
    return {"error": code, "field": field, "message": message}


def execute_python(payload: Dict[str, Any], user_roles: list[str] | None = None) -> Dict[str, Any]:
    try:
        inp = ExecutePythonInput.model_validate(payload)
    except Exception as e:
        return _error("payload", "INVALID_INPUT", str(e))

    p = Path(inp.path).resolve()
    if not str(p).startswith(str(WORKSPACE_ROOT.resolve())):
        return _error("path", "INVALID_PATH", "Must be inside workspace directory")

    try:
        # Read the file
        code = p.read_text()
        # Execute in sandbox
        result = execute_in_sandbox(code, timeout=inp.timeout, memory_limit_mb=inp.memory_limit_mb or 256)
        if "error" in result:
            return _error("execution", result.get("error", "UNKNOWN"), result.get("message", "Unknown error"))
        return {"ok": True, "stdout": result.get("stdout", ""), "stderr": result.get("stderr", ""), "returncode": result.get("returncode", 0)}
    except SandboxError as e:
        return _error("execution", "SANDBOX_ERROR", str(e))
