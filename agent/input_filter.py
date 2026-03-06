"""Input filtering and prompt-injection detection."""
from __future__ import annotations
from pydantic import BaseModel
from typing import Optional, Dict, Any
import re
from .telemetry.tracing import start_span


DENY_PATTERNS = [
    r"ignore previous instructions",
    r"system prompt",
    r"exfiltrate",
    r"bypass",
    r"reveal secrets",
    r"print /etc",
    r"base64 encode",
    r"open socket",
]


class FilterResult(BaseModel):
    ok: bool
    cleaned: Optional[str] = None
    score: float = 0.0
    error: Optional[Dict[str, Any]] = None


def filter_user_input(text: str) -> FilterResult:
    with start_span("input_filter"):
        lower = text.lower()
        for p in DENY_PATTERNS:
            if re.search(p, lower):
                return FilterResult(ok=False, error={"error": "PROMPT_INJECTION_DETECTED", "reason": "deny_list_match", "pattern": p})

        # lightweight semantic classifier: suspicious token counts
        score = 0.0
        if re.search(r"\b(password|secret|token)\b", lower):
            score += 0.6
        if re.search(r"\b(eval|exec|os\.system|subprocess)\b", lower):
            score += 0.6

        if score >= 0.5:
            return FilterResult(ok=False, score=score, error={"error": "PROMPT_INJECTION_DETECTED", "reason": "semantic_score", "score": score})

        # clean trivial whitespace
        cleaned = text.strip()
        return FilterResult(ok=True, cleaned=cleaned, score=score)
