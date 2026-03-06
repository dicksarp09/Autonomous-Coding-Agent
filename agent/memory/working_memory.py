"""Working memory sliding window (session-scoped)."""
from __future__ import annotations
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import math


class IterationRecord(BaseModel):
    iteration_id: int
    plan: str
    code_diff: str
    error: Optional[str] = None
    timestamp: datetime
    token_estimate: int = 0


class WorkingMemory:
    def __init__(self, session_id: str, window: int = 5):
        self.session_id = session_id
        self.window = max(1, min(window, 50))
        self._records: List[IterationRecord] = []

    def _estimate_tokens(self, text: str) -> int:
        # conservative token estimate: 4 chars per token
        return max(1, math.ceil(len(text) / 4))

    def add(self, record: IterationRecord) -> None:
        record.token_estimate = self._estimate_tokens((record.plan or "") + (record.code_diff or "") + (record.error or ""))
        self._records.append(record)
        while len(self._records) > self.window:
            self._records.pop(0)

    def get_recent(self, limit: int = 5) -> List[IterationRecord]:
        limit = min(limit, self.window)
        return list(self._records[-limit:])

    def reset(self) -> None:
        self._records = []

    def total_tokens(self) -> int:
        return sum(r.token_estimate for r in self._records)
