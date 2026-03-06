"""Role-based access control enforcement and identity checks.

This module provides:
- `AgentIdentity` model for per-execution identity
- RBAC registry mapping tools to allowed roles
- `check_permission` to validate an AgentIdentity can call a tool
"""
from __future__ import annotations
from functools import wraps
from typing import Callable, Dict, Any, Literal
import enum
import logging
from datetime import datetime
from pydantic import BaseModel
from .telemetry.tracing import start_span

logger = logging.getLogger(__name__)


class Role(enum.Enum):
    READER = "reader"
    WRITER = "writer"
    EXECUTOR = "executor"
    ADMIN = "admin"


class RBACError(Exception):
    pass


class ForbiddenError(Exception):
    pass


class AgentIdentity(BaseModel):
    agent_id: str
    role: Literal["coder_agent"]
    session_id: str
    timestamp: datetime


# simple registry mapping tool -> allowed roles
TOOL_ROLE_MAP: Dict[str, list[Role]] = {
    "write_file": [Role.WRITER],
    "read_file": [Role.READER, Role.WRITER],
    "execute_python": [Role.EXECUTOR],
    "run_tests": [Role.EXECUTOR],
    "static_analysis": [Role.READER],
    "store_memory": [Role.WRITER],
    "retrieve_short": [Role.READER],
    "retrieve_long": [Role.READER],
}


def is_allowed(role: Role, tool_name: str) -> bool:
    allowed = TOOL_ROLE_MAP.get(tool_name, [])
    return role in allowed or Role.ADMIN in allowed


def check_permission(agent_identity: AgentIdentity, tool_name: str) -> None:
    # Enforce RBAC and log via telemetry
    with start_span("permission_check", agent_id=agent_identity.agent_id, tool=tool_name):
        try:
            role = Role.ADMIN if agent_identity.role != "coder_agent" else Role.WRITER if tool_name.endswith("write_file") else Role.READER
        except Exception:
            role = Role.READER
        allowed = is_allowed(Role.WRITER if agent_identity.role == "coder_agent" else Role.READER, tool_name)
        logger.info("Permission check agent=%s tool=%s allowed=%s", agent_identity.agent_id, tool_name, allowed)
        if not allowed:
            raise ForbiddenError(f"Agent {agent_identity.agent_id} not allowed to call {tool_name}")


def require_identity(fn: Callable):
    @wraps(fn)
    def wrapper(*args, agent_identity: AgentIdentity | None = None, **kwargs):
        if agent_identity is None:
            raise RBACError("Missing agent identity")
        check_permission(agent_identity, fn.__name__)
        return fn(*args, **kwargs)

    return wrapper
