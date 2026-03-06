"""Short-term memory: in-memory sliding window per session."""
from __future__ import annotations
from typing import Dict, List


class ShortTermMemory:
    def __init__(self, window: int = 5):
        self._store: Dict[str, List[str]] = {}
        self.window = window

    def add(self, key: str, value: str) -> None:
        lst = self._store.setdefault(key, [])
        lst.append(value)
        if len(lst) > self.window:
            lst.pop(0)

    def get(self, key: str) -> List[str]:
        return list(self._store.get(key, []))
