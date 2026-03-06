"""Retry utilities with exponential backoff, jitter, and telemetry logging."""
from __future__ import annotations
import time
import random
import logging
from typing import Callable, TypeVar, Any
from .telemetry.tracing import start_span

T = TypeVar("T")
logger = logging.getLogger(__name__)


class TransientError(Exception):
    pass


class NonRetryableError(Exception):
    pass


def retry_request(func: Callable[[], T], max_retries: int = 5, base_backoff: float = 1.0, max_backoff: float = 32.0) -> T:
    attempt = 0
    backoff = base_backoff
    last_exc: Exception | None = None
    while attempt <= max_retries:
        with start_span("retry.attempt", attempt=attempt):
            try:
                return func()
            except NonRetryableError:
                logger.exception("Non-retryable error encountered; aborting")
                raise
            except TransientError as e:
                last_exc = e
                jitter = random.uniform(0, 0.5)
                sleep_time = min(backoff, max_backoff) + jitter
                logger.warning("Transient error, attempt=%d sleeping=%.2f error=%s", attempt, sleep_time, e)
                time.sleep(sleep_time)
                backoff = min(backoff * 2, max_backoff)
                attempt += 1
                continue
            except Exception as e:
                # unknown exceptions treated as non-retryable
                logger.exception("Unexpected non-retryable error")
                raise

    logger.error("Retry exhausted after %d attempts", max_retries)
    if last_exc:
        raise last_exc
    raise RuntimeError("Retry exhausted")
