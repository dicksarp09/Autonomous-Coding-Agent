"""Retrieval governance scaffold for memory retrieval and ingestion policies."""
from __future__ import annotations
from pydantic import BaseModel
from typing import List


class RetrievalPolicy(BaseModel):
    tenant_id: str
    allowed_sources: List[str]
    namespace: str


def validate_ingest(source: str, policy: RetrievalPolicy) -> bool:
    return source in policy.allowed_sources
