"""Telemetry helpers for memory operations (OpenTelemetry spans)."""
from __future__ import annotations
from contextlib import contextmanager
from ..telemetry.tracing import start_span


@contextmanager
def memory_span(name: str, **attrs):
    with start_span(name, **attrs) as span:
        yield span
