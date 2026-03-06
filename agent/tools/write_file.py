"""Tool: write_file with strict Pydantic v2 contract and path validation."""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Dict, Any
from pathlib import Path
from ..config import WORKSPACE_ROOT
import json


class WriteFileInput(BaseModel):
    path: str = Field(...)
    content: str = Field(...)

    model_config = {"extra": "forbid"}


def _error(field: str, code: str, message: str) -> Dict[str, Any]:
    return {"error": code, "field": field, "message": message}


def write_file(payload: Dict[str, Any], user_roles: list[str] | None = None) -> Dict[str, Any]:
    try:
        inp = WriteFileInput.model_validate(payload)
    except Exception as e:
        return _error("payload", "INVALID_INPUT", str(e))

    p = Path(inp.path).resolve()
    if not str(p).startswith(str(WORKSPACE_ROOT.resolve())):
        return _error("path", "INVALID_PATH", "Must be inside workspace directory")

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(inp.content, encoding="utf-8")
        return {"ok": True, "path": str(p)}
    except Exception as e:
        return _error("io", "WRITE_FAILED", str(e))
