"""Static analysis tool: AST checks and wrappers for bandit/ruff.

Rejects dangerous constructs and returns structured errors.
"""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Dict, Any, List
import ast
import subprocess
import shutil
from pathlib import Path
from ..config import WORKSPACE_ROOT


class StaticAnalysisInput(BaseModel):
    path: str = Field(...)

    model_config = {"extra": "forbid"}


def _error(field: str, code: str, message: str) -> Dict[str, Any]:
    return {"error": code, "field": field, "message": message}


def _ast_check(source: str) -> List[Dict[str, str]]:
    issues: List[Dict[str, str]] = []
    try:
        tree = ast.parse(source)
    except Exception as e:
        return [{"type": "PARSE_ERROR", "message": str(e)}]

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            try:
                if isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec", "compile", "execfile"):
                    issues.append({"type": "DANGEROUS_CALL", "message": f"use of {node.func.id}"})
                if isinstance(node.func, ast.Attribute) and getattr(node.func, "attr", "") in ("system", "popen"):
                    issues.append({"type": "SHELL_CALL", "message": f"use of shell via {ast.unparse(node.func)}"})
            except Exception:
                pass
        if isinstance(node, ast.Import):
            for alias in node.names:
                # Allow os.environ for safe environment variable access
                if alias.name == "os":
                    continue
                if alias.name in ("socket", "requests", "subprocess", "pickle"):
                    issues.append({"type": "SENSITIVE_IMPORT", "message": f"import {alias.name}"})

    return issues


def static_analysis(payload: Dict[str, Any], user_roles: list[str] | None = None) -> Dict[str, Any]:
    try:
        inp = StaticAnalysisInput.model_validate(payload)
    except Exception as e:
        return _error("payload", "INVALID_INPUT", str(e))

    p = Path(inp.path).resolve()
    if not str(p).startswith(str(WORKSPACE_ROOT.resolve())):
        return _error("path", "INVALID_PATH", "Must be inside workspace directory")

    if not p.exists():
        return _error("path", "NOT_FOUND", "File does not exist")

    src = p.read_text(encoding="utf-8")
    issues = _ast_check(src)
    if issues:
        return {"ok": False, "issues": issues}

    # Run external tools if present
    results = {"ast_issues": [], "bandit": None, "ruff": None}

    if shutil.which("bandit"):
        try:
            proc = subprocess.run(["bandit", "-r", str(p)], capture_output=True, text=True, timeout=30)
            results["bandit"] = {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
            if proc.returncode != 0:
                return {"ok": False, "issues": [{"type": "BANDIT", "message": proc.stdout or proc.stderr}]}
        except Exception as e:
            results["bandit"] = {"error": str(e)}
    else:
        results["bandit"] = {"warning": "bandit not installed"}

    if shutil.which("ruff"):
        try:
            proc = subprocess.run(["ruff", str(p)], capture_output=True, text=True, timeout=30)
            results["ruff"] = {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
            if proc.returncode != 0:
                return {"ok": False, "issues": [{"type": "RUFF", "message": proc.stdout or proc.stderr}]}
        except Exception as e:
            results["ruff"] = {"error": str(e)}
    else:
        results["ruff"] = {"warning": "ruff not installed"}

    return {"ok": True, "results": results}
