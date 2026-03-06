"""Tool validation middleware enforcing strict Pydantic schemas, path rules, RBAC, identity, and structured errors."""
from __future__ import annotations
import time
from typing import Dict, Any, Optional
from pydantic import ValidationError
from .tools import write_file, read_file, execute_python, run_tests, static_analysis, memory_tools
from .rbac import Role, AgentIdentity, check_permission, ForbiddenError

try:
    from .observability.langfuse_integration import get_observer
except ImportError:
    get_observer = None


TOOL_REGISTRY = {
    "write_file": (write_file.WriteFileInput, write_file.write_file, Role.WRITER),
    "read_file": (read_file.ReadFileInput, read_file.read_file, Role.READER),
    "execute_python": (execute_python.ExecutePythonInput, execute_python.execute_python, Role.EXECUTOR),
    "run_tests": (run_tests.RunTestsInput, run_tests.run_tests, Role.EXECUTOR),
    "static_analysis": (static_analysis.StaticAnalysisInput, static_analysis.static_analysis, Role.READER),
    "store_memory": (memory_tools.StoreMemoryInput, memory_tools.store_long_term, Role.WRITER),
    "retrieve_short": (None, memory_tools.retrieve_short_term, Role.READER),
    "retrieve_long": (None, memory_tools.retrieve_long_term, Role.READER),
}


def _error(field: str, code: str, message: Any) -> Dict[str, Any]:
    return {"error": code, "field": field, "message": message}


def validate_tool_call(name: str, payload: Dict[str, Any], agent_identity: AgentIdentity | None = None, user_roles: list[str] | None = None) -> Dict[str, Any]:
    start_time = time.time()
    observer = get_observer() if get_observer else None
    
    entry = TOOL_REGISTRY.get(name)
    if not entry:
        return _error("tool", "UNKNOWN_TOOL", "Tool not found")

    schema, fn, required_role = entry
    # Identity and Permission check
    if agent_identity is None:
        return _error("identity", "MISSING_IDENTITY", "Agent identity required")

    try:
        check_permission(agent_identity, name)
    except ForbiddenError as e:
        return _error("rbac", "DENIED", str(e))
    except Exception as e:
        return _error("rbac", "DENIED", str(e))

    # Schema validation
    if schema is not None:
        try:
            schema.model_validate(payload)
        except ValidationError as e:
            return _error("payload", "INVALID_INPUT", e.errors())
        except Exception as e:
            return _error("payload", "INVALID_INPUT", str(e))

    # Track tool validation in Langfuse
    duration_ms = (time.time() - start_time) * 1000
    if observer:
        try:
            observer.track_tool_execution(
                tool_name=name,
                tool_input=payload,
                tool_output="Validation passed",
                status="SUCCESS",
                duration_ms=duration_ms,
            )
        except Exception as e:
            pass  # Don't fail if observability fails

    # All good: call tool function
    try:
        # Pass agent identity through to tool implementations for double-checks
        result = fn(payload, user_roles=user_roles, agent_identity=agent_identity)
        return result
    except Exception as e:
        return _error("execution", "TOOL_ERROR", str(e))
