"""Minimal Groq API client wrapper with retry and latency/token logging."""
from __future__ import annotations
import time
import logging
import os
from typing import Dict, Any, Optional
import requests
from requests import Response
from .config import GROQ_API_KEY, GROQ_BASE_URL, MODEL_CONFIGS

# LangSmith tracing - automatic when env vars set
try:
    from langsmith import traceable
    from langsmith.run_helpers import get_current_run_tree
    LANGSMITH_AVAILABLE = True
except ImportError:
    LANGSMITH_AVAILABLE = False
    traceable = None
    get_current_run_tree = None

try:
    from .observability.langfuse_integration import get_observer
except ImportError:
    get_observer = None

logger = logging.getLogger(__name__)


class GroqError(Exception):
    pass


def _create_langsmith_metadata(model: str, payload: Dict[str, Any], latency: float, usage: Optional[Dict] = None) -> Dict[str, Any]:
    """Create metadata dict for LangSmith tracing."""
    return {
        "model": model,
        "provider": "groq",
        "latency_ms": latency * 1000,
        "input_tokens": usage.get("prompt_tokens", 0) if usage else 0,
        "output_tokens": usage.get("completion_tokens", 0) if usage else 0,
        "total_tokens": usage.get("total_tokens", 0) if usage else 0,
    }


class GroqClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or GROQ_API_KEY
        self.base_url = base_url or GROQ_BASE_URL
        if not self.api_key:
            logger.warning("GROQ_API_KEY not set; client will fail on requests")

    @traceable(name="groq_api_call", run_type="llm") if LANGSMITH_AVAILABLE else lambda f: f
    def _call(self, model: str, payload: Dict[str, Any], timeout: int = 60) -> Dict[str, Any]:
        url = f"{self.base_url}/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        attempts = 0
        max_attempts = 4
        backoff = 1.0
        while attempts < max_attempts:
            attempts += 1
            start = time.time()
            try:
                resp: Response = requests.post(url, json=payload, headers=headers, timeout=timeout)
                latency = time.time() - start
                logger.info("Groq call latency=%.3fs status=%s model=%s", latency, resp.status_code, model)
                if resp.status_code in (429, 500, 502, 503, 504):
                    # retryable
                    if attempts < max_attempts:
                        time.sleep(backoff)
                        backoff *= 2
                        continue
                    raise GroqError(f"Retry exhausted: {resp.status_code} {resp.text}")
                if not resp.ok:
                    # non-retryable
                    raise GroqError(f"Non-retryable error: {resp.status_code} {resp.text}")
                data = resp.json()
                # log token usage if present
                if isinstance(data, dict) and "usage" in data:
                    logger.info("token_usage=%s", data.get("usage"))
                    
                    # Track LLM usage for cost monitoring
                    try:
                        from .observability.metrics import track_llm_usage
                        usage = data.get("usage", {})
                        input_tokens = usage.get("prompt_tokens", 0)
                        output_tokens = usage.get("completion_tokens", 0)
                        # Calculate cost (approximate for Groq)
                        # $0.59/M input, $0.79/M output for llama-3.3-70b
                        cost = (input_tokens / 1_000_000 * 0.59) + (output_tokens / 1_000_000 * 0.79)
                        track_llm_usage(model, input_tokens, output_tokens, cost, latency * 1000)
                    except Exception as e:
                        logger.debug(f"Failed to track LLM usage: {e}")
                    
                    # Track LLM call in Langfuse if available
                    if get_observer:
                        try:
                            observer = get_observer()
                            usage = data.get("usage", {})
                            response_text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                            prompt_text = payload.get("messages", [{}])[0].get("content", "")
                            duration_ms = latency * 1000
                            
                            observer.track_llm_call(
                                model=model,
                                prompt=prompt_text[:500],  # Truncate long prompts
                                response=response_text[:500],  # Truncate long responses
                                tokens_used={
                                    "input": usage.get("prompt_tokens", 0),
                                    "output": usage.get("completion_tokens", 0),
                                    "total": usage.get("total_tokens", 0),
                                },
                                cost_usd=(usage.get("total_tokens", 0) * 0.00002),  # Approximate cost
                                duration_ms=duration_ms,
                            )
                        except Exception as e:
                            logger.warning(f"Failed to track LLM call in Langfuse: {e}")
                
                return data
            except requests.RequestException as e:
                latency = time.time() - start
                logger.warning("Groq request exception after %.3fs: %s", latency, e)
                if attempts < max_attempts:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                raise GroqError(str(e))

    @traceable(name="groq_generate", run_type="llm") if LANGSMITH_AVAILABLE else lambda f: f
    def generate(self, role: str, prompt: str, **kwargs) -> Dict[str, Any]:
        cfg = MODEL_CONFIGS.get(role)
        if not cfg:
            raise GroqError("Unknown model role")
        
        # Use OpenAI-compatible chat format for Groq
        payload = {
            "model": cfg.get("model"),
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "max_tokens": cfg.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.7),
        }
        return self._call(cfg.get("model"), payload)
