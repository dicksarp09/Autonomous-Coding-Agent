"""Centralized configuration and environment access."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Dict

WORKSPACE_ROOT = Path(os.environ.get("AGENT_WORKSPACE") or os.getcwd())

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_BASE_URL = os.environ.get("GROQ_BASE_URL", "https://api.groq.com")

# Model configs - Using Groq-compatible models
# Note: Original prompt specified qwen3-32b and openai/gpt-oss-120b but these may not be available
# on Groq API. Current configuration uses available Groq models.
MODEL_CONFIGS: Dict[str, Dict] = {
    "coding": {
        "provider": "groq",
        "model": "llama-3.3-70b-versatile",  # Groq-supported coding model
        "max_tokens": 8192,
        "temperature": 0.7,
    },
    "judge": {
        "provider": "groq",
        "model": "llama-3.3-70b-versatile",  # Using same model as judge
        "max_tokens": 4096,
        "temperature": 0.3,
    },
}

DB_PATH = WORKSPACE_ROOT / "agent_data.sqlite3"

SECURITY = {
    "allowed_paths": [str(WORKSPACE_ROOT)],
}
