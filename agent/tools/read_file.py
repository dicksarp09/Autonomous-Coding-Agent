"""Tool: read_file with strict contract and safe path validation."""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Dict, Any
from pathlib import Path
from ..config import WORKSPACE_ROOT


class ReadFileInput(BaseModel):
    path: str = Field(...)

    model_config = {"extra": "forbid"}


def _error(field: str, code: str, message: str) -> Dict[str, Any]:
    return {"error": code, "field": field, "message": message}


def read_file(payload: Dict[str, Any], user_roles: list[str] | None = None) -> Dict[str, Any]:
    try:
        inp = ReadFileInput.model_validate(payload)
    except Exception as e:
        return _error("payload", "INVALID_INPUT", str(e))

    p = Path(inp.path).resolve()
    if not str(p).startswith(str(WORKSPACE_ROOT.resolve())):
        return _error("path", "INVALID_PATH", "Must be inside workspace directory")

    if not p.exists():
        return _error("path", "NOT_FOUND", "File does not exist")

    try:
        content = p.read_text(encoding="utf-8")
        return {"ok": True, "path": str(p), "content": content}
    except Exception as e:
        return _error("io", "READ_FAILED", str(e))
