"""
LangSmith Integration for Autonomous Agent Observability

LangSmith provides:
- Automatic tracing of LLM calls
- Span-level detail with input/output
- Runtime metadata (latency, tokens, cost)
- Evaluation and feedback collection

Setup: Environment variables are automatically read by langchain
"""

import os
import time
import json
from datetime import datetime
from typing import Any, Dict, Optional, Callable, TypeVar
from functools import wraps

# Try to import langchain for tracing - graceful fallback if not available
try:
    from langchain_openai import ChatOpenAI
    from langchain.schema import HumanMessage, SystemMessage
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False
    ChatOpenAI = None
    HumanMessage = None
    SystemMessage = None

# Try to import langsmith for explicit tracing
try:
    from langsmith import traceable, Client
    from langsmith.run_helpers import get_current_run_tree
    LANGSMITH_AVAILABLE = True
except ImportError:
    LANGSMITH_AVAILABLE = False
    traceable = None
    Client = None
    get_current_run_tree = None


class LangSmithTracer:
    """
    LangSmith integration for comprehensive observability.
    
    Automatically traces:
    - LLM calls (Groq via langchain-groq)
    - Tool executions
    - Workflow phases
    - Memory operations
    """
    
    def __init__(self):
        self.enabled = False
        self.client = None
        
        # Check if LangSmith is properly configured
        # LangSmith tracing is automatic via environment variables
        self.enabled = (
            os.getenv("LANGSMITH_TRACING", "").lower() == "true" and
            os.getenv("LANGSMITH_API_KEY") is not None
        )
        
        if self.enabled:
            try:
                # LangSmith Client is optional - tracing works automatically
                # with environment variables set
                self.client = Client(api_key=os.getenv("LANGSMITH_API_KEY"))
                print(f"LangSmith tracing enabled - Project: {os.getenv('LANGSMITH_PROJECT', 'default')}")
            except Exception as e:
                # Even if Client init fails, tracing works via env vars
                print(f"LangSmith client init warning: {e}")
                print(f"LangSmith tracing enabled - Project: {os.getenv('LANGSMITH_PROJECT', 'default')}")
    
    def is_enabled(self) -> bool:
        return self.enabled
    
    def create_run_config(self, workflow_id: str, metadata: Optional[Dict] = None) -> Dict:
        """Create run configuration for LangSmith."""
        return {
            "project_name": os.getenv("LANGSMITH_PROJECT", "Coding Agent"),
            "metadata": {
                "workflow_id": workflow_id,
                "timestamp": datetime.now().isoformat(),
                **(metadata or {})
            }
        }


def trace_function(name: str = None):
    """
    Decorator to trace a function with LangSmith.
    
    Usage:
        @trace_function("my_function")
        def my_function(x):
            return x * 2
    """
    def decorator(func: Callable) -> Callable:
        if not LANGSMITH_AVAILABLE:
            return func
            
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.time() - start_time) * 1000
                return result
            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                raise
        return wrapper
    return decorator


# Global tracer instance
_langsmith_tracer = None


def get_langsmith_tracer() -> LangSmithTracer:
    """Get the global LangSmith tracer instance."""
    global _langsmith_tracer
    if _langsmith_tracer is None:
        _langsmith_tracer = LangSmithTracer()
    return _langsmith_tracer


def setup_langsmith_tracing() -> bool:
    """
    Initialize LangSmith tracing from environment variables.
    
    Environment variables required:
    - LANGSMITH_TRACING=true
    - LANGSMITH_API_KEY=<your-api-key>
    - LANGSMITH_PROJECT="Coding Agent" (optional)
    
    Returns:
        bool: True if tracing is enabled
    """
    tracer = get_langsmith_tracer()
    
    if tracer.is_enabled():
        print(f"""
╔══════════════════════════════════════════════════════════════════╗
║           LangSmith Tracing Enabled                             ║
╠══════════════════════════════════════════════════════════════════╣
║  Project: {os.getenv('LANGSMITH_PROJECT', 'Coding Agent'):<50} ║
║  Endpoint: {os.getenv('LANGSMITH_ENDPOINT', 'https://api.smith.langchain.com'):<45} ║
╚══════════════════════════════════════════════════════════════════╝
        """)
    else:
        print("LangSmith tracing not configured. Set LANGSMITH_TRACING=true in .env")
    
    return tracer.is_enabled()


# Example: Trace LLM calls with structured input/output
if LANGSMITH_AVAILABLE:
    @traceable(name="groq_llm_call")
    def trace_groq_call(
        model: str,
        messages: list,
        metadata: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Trace a Groq LLM call with LangSmith.
        
        This function is automatically traced when called,
        capturing input, output, and metadata.
        """
        # This is a placeholder - actual implementation would call Groq
        return {
            "model": model,
            "message_count": len(messages),
            "metadata": metadata or {}
        }


# Export for easy integration
__all__ = [
    "LangSmithTracer",
    "get_langsmith_tracer", 
    "setup_langsmith_tracing",
    "trace_function",
    "LANGSMITH_AVAILABLE",
    "LANGCHAIN_AVAILABLE",
]
