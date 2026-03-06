"""OpenTelemetry instrumentation helper (best-effort).

If OpenTelemetry packages are not installed, this module provides no-op fallbacks.
"""
from __future__ import annotations
import time
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)

try:
    from opentelemetry import trace
    from opentelemetry.trace import Tracer

    tracer = trace.get_tracer(__name__)

    @contextmanager
    def start_span(name: str, **attrs):
        with tracer.start_as_current_span(name) as span:
            for k, v in attrs.items():
                span.set_attribute(k, v)
            yield span

except Exception:
    @contextmanager
    def start_span(name: str, **attrs):
        start = time.time()
        logger.debug("span start: %s %s", name, attrs)
        try:
            yield None
        finally:
            logger.debug("span end: %s elapsed=%.3fs", name, time.time() - start)
