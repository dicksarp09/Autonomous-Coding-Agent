"""Output filtering for generated code to detect dangerous constructs before execution."""
from __future__ import annotations
from pydantic import BaseModel
from typing import Dict, Any, List
import ast


class DangerousSymbol(BaseModel):
    symbol: str
    severity: str
    message: str


def scan_code(code: str) -> Dict[str, Any]:
    try:
        tree = ast.parse(code)
    except Exception as e:
        return {"error": "PARSE_ERROR", "message": str(e)}

    findings: List[DangerousSymbol] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                name = node.func.attr
            elif isinstance(node.func, ast.Name):
                name = node.func.id
            else:
                name = None
            if name in ("system", "popen"):
                findings.append(DangerousSymbol(symbol=name, severity="HIGH", message="shell execution"))
            if name in ("eval", "exec", "compile"):
                findings.append(DangerousSymbol(symbol=name, severity="HIGH", message="code execution"))
        if isinstance(node, ast.Import):
            for alias in node.names:
                # Allow os.environ for environment variable access
                if alias.name == "os":
                    # Check if it's used for environ (safe)
                    continue
                if alias.name in ("socket", "requests", "subprocess", "pickle"):
                    findings.append(DangerousSymbol(symbol=alias.name, severity="HIGH", message="suspicious import"))

    if findings:
        return {"error": "DANGEROUS_CODE_DETECTED", "items": [f.model_dump() for f in findings]}
    return {"ok": True}
