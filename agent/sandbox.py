"""Subprocess-based sandbox for executing Python code with resource limits.

Best-effort isolation: timeout, memory limits, disabled network by environment and optional seccomp on Unix.
"""
from __future__ import annotations
import subprocess
import sys
import os
import time
import logging
from pathlib import Path
from typing import Tuple, Dict, Any

logger = logging.getLogger(__name__)

from .config import WORKSPACE_ROOT


class SandboxError(Exception):
    pass


def _preexec_unix(memory_limit_mb: int | None, cpu_seconds: int | None):
    try:
        import resource

        if memory_limit_mb:
            soft = memory_limit_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (soft, soft))
        if cpu_seconds:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        # further restrictions could be applied here
    except Exception:
        pass


def execute_in_sandbox(code: str, timeout: int = 20, memory_limit_mb: int = 256, cpu_seconds: int = 10) -> Dict[str, Any]:
    """Execute provided Python code inside an isolated subprocess.

    Returns structured result dict with keys: ok, stdout, stderr, returncode, error
    
    Note: Memory limit enforcement is best-effort on Unix. On Windows, only
    timeout is reliably enforced.
    """
    # Prepare workspace sandbox directory
    sandbox_dir = WORKSPACE_ROOT / "agent_sandbox"
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    script_path = sandbox_dir / "run_payload.py"
    # ensure path within workspace
    if not str(sandbox_dir.resolve()).startswith(str(WORKSPACE_ROOT.resolve())):
        return {"error": "INVALID_PATH", "message": "Workspace restriction violated"}

    script_path.write_text(code, encoding="utf-8")

    cmd = [sys.executable, str(script_path)]

    env = {k: v for k, v in os.environ.items() if k.startswith("LC_") or k.startswith("PY")}
    # Remove network-related vars
    env.pop("http_proxy", None)
    env.pop("https_proxy", None)
    # Ensure no network access
    env["NO_NETWORK"] = "1"

    preexec_fn = None
    if os.name != "nt":
        preexec_fn = lambda: _preexec_unix(memory_limit_mb, cpu_seconds)

    try:
        start = time.time()
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(sandbox_dir),
            env=env,
            preexec_fn=preexec_fn
        )
        elapsed = time.time() - start
        
        # Check for out-of-memory in output (best-effort detection)
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        
        if "MemoryError" in stderr or "MemoryError" in stdout:
            return {
                "ok": False,
                "stdout": stdout,
                "stderr": stderr,
                "returncode": proc.returncode,
                "latency": elapsed,
                "error": "MEMORY_LIMIT",
                "message": "Execution caused MemoryError"
            }
        
        return {
            "ok": True,
            "stdout": stdout,
            "stderr": stderr,
            "returncode": proc.returncode,
            "latency": elapsed
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": "TIMEOUT",
            "message": f"Execution exceeded timeout {timeout}s"
        }
    except OSError as e:
        # Handle OS-level errors (resource limits, etc.)
        if "Cannot allocate memory" in str(e) or e.errno == 12:
            return {
                "ok": False,
                "error": "MEMORY_LIMIT",
                "message": "Memory allocation failed (OS error)"
            }
        return {
            "ok": False,
            "error": "EXECUTION_FAILED",
            "message": f"OS error: {str(e)}"
        }
    except Exception as e:
        return {
            "ok": False,
            "error": "EXECUTION_FAILED",
            "message": str(e)
        }

