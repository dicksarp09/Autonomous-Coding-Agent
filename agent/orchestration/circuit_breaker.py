"""Circuit breaker implementation tracking repeated errors and cost thresholds.

Includes telemetry spans and persistence helpers.
Implements singleton pattern for state persistence across workflow iterations.
"""
from __future__ import annotations
from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import hashlib
import threading
from ..db import get_conn
from ..telemetry.tracing import start_span
import logging

logger = logging.getLogger(__name__)


class BreakerState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """Thread-safe singleton circuit breaker with persistence."""
    
    _instance: Optional["CircuitBreaker"] = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self, open_threshold: int = 3, cost_threshold: float = 100.0, window_seconds: int = 60, rate_limit: int = 10):
        # Only initialize once
        if getattr(self, '_initialized', False):
            return
        
        self.open_threshold = open_threshold
        self.cost_threshold = cost_threshold
        self.window = timedelta(seconds=window_seconds)
        self.rate_limit = rate_limit
        self.state = BreakerState.CLOSED
        self.error_count = 0
        self.last_error_signature: Optional[str] = None
        self.cooldown_start: Optional[datetime] = None
        self.last_error: Optional[str] = None
        self._initialized = True
        
        # Try to restore state from DB
        self._restore_state()
    
    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (useful for testing)."""
        with cls._lock:
            cls._instance = None

    def _restore_state(self) -> None:
        """Restore circuit breaker state from database."""
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS circuit_state (id INTEGER PRIMARY KEY, state TEXT, error_count INTEGER, last_signature TEXT, cooldown_start TEXT, last_error TEXT)")
            cur.execute("SELECT state, error_count, last_signature, cooldown_start, last_error FROM circuit_state ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            if row:
                self.state = BreakerState(row[0])
                self.error_count = row[1] or 0
                self.last_error_signature = row[2]
                if row[3]:
                    self.cooldown_start = datetime.fromisoformat(row[3])
                self.last_error = row[4]
                logger.info(f"Restored circuit breaker state: {self.state.value}, errors={self.error_count}")
        except Exception as e:
            logger.warning(f"Failed to restore circuit breaker state: {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def signature_of(self, msg: str) -> str:
        return hashlib.sha256(msg.encode("utf-8")).hexdigest()

    def record_error(self, signature: str, cost_delta: float = 0.0, error: Optional[Exception | str] = None) -> None:
        with start_span("circuit_breaker.record_error"):
            now = datetime.utcnow()
            if self.last_error_signature == signature:
                self.error_count += 1
            else:
                self.last_error_signature = signature
                self.error_count = 1

            if error:
                self.last_error = str(error)

            if self.error_count >= self.open_threshold or (cost_delta is not None and cost_delta >= self.cost_threshold):
                self.state = BreakerState.OPEN
                self.cooldown_start = now
                logger.warning("Circuit opened due to repeated errors or cost threshold: %s", self.last_error)

    def record_success(self) -> None:
        with start_span("circuit_breaker.record_success"):
            self.error_count = 0
            self.last_error_signature = None
            self.cooldown_start = None
            self.last_error = None
            self.state = BreakerState.CLOSED

    def allow_request(self) -> bool:
        with start_span("circuit_breaker.allow_request"):
            now = datetime.utcnow()
            if self.state == BreakerState.OPEN:
                # if cooldown passed, move to HALF_OPEN
                if self.cooldown_start and now - self.cooldown_start > self.window:
                    self.state = BreakerState.HALF_OPEN
                    logger.info("Circuit moved to HALF_OPEN")
                    return True
                return False
            return True

    def reset_if_half_open(self, success: bool) -> None:
        with start_span("circuit_breaker.reset_if_half_open"):
            if self.state == BreakerState.HALF_OPEN:
                if success:
                    self.record_success()
                    logger.info("Circuit closed after successful HALF_OPEN test")
                else:
                    self.state = BreakerState.OPEN
                    self.cooldown_start = datetime.utcnow()
                    logger.warning("Circuit re-opened after HALF_OPEN failure")

    def persist_state(self, workflow_id: int | None = None) -> None:
        # persist breaker state to audit DB
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS circuit_state (id INTEGER PRIMARY KEY, state TEXT, error_count INTEGER, last_signature TEXT, cooldown_start TEXT, last_error TEXT)")
            cur.execute(
                "INSERT INTO circuit_state (state, error_count, last_signature, cooldown_start, last_error) VALUES (?, ?, ?, ?, ?)",
                (self.state.value, self.error_count, self.last_error_signature, self.cooldown_start.isoformat() if self.cooldown_start else None, self.last_error),
            )
            conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def as_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "error_count": self.error_count,
            "last_signature": self.last_error_signature,
            "cooldown_start": self.cooldown_start.isoformat() if self.cooldown_start else None,
            "last_error": self.last_error,
        }
