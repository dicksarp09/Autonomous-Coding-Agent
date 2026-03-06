"""Retrieval trigger model deciding when to query long-term memory.

Implements conditional retrieval based on:
- Error signature similarity threshold
- Repeated failure detection
- Similar problem cluster detection
"""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List
from datetime import datetime
import hashlib


class RetrievalTrigger(BaseModel):
    """Trigger for long-term memory retrieval."""
    error_signature: str
    similarity_score: float = Field(0.0, ge=0.0, le=1.0)
    threshold: float = Field(0.7, ge=0.0, le=1.0)
    repeated_failure_count: int = Field(0, ge=0)
    repeated_failure_threshold: int = Field(3, ge=1)
    
    def should_retrieve(self) -> bool:
        """Determine if retrieval should be triggered.
        
        Retrieval is triggered if:
        - Similarity score exceeds threshold, OR
        - Same error has repeated multiple times
        """
        if self.similarity_score >= self.threshold:
            return True
        if self.repeated_failure_count >= self.repeated_failure_threshold:
            return True
        return False
    
    def get_reason(self) -> str:
        """Get the reason for triggering retrieval."""
        if self.similarity_score >= self.threshold:
            return f"similarity_score={self.similarity_score:.2f} >= threshold={self.threshold}"
        if self.repeated_failure_count >= self.repeated_failure_threshold:
            return f"repeated_failure_count={self.repeated_failure_count} >= threshold={self.repeated_failure_threshold}"
        return "no_trigger"


class RetrievalDecision(BaseModel):
    """Decision result from retrieval trigger evaluation."""
    should_retrieve: bool
    reason: str
    trigger: RetrievalTrigger
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class RetrievalTriggerManager:
    """Manages retrieval triggers across workflow iterations."""
    
    def __init__(self, default_threshold: float = 0.7, repeated_threshold: int = 3):
        self.default_threshold = default_threshold
        self.repeated_threshold = repeated_threshold
        self._error_signatures: List[str] = []
        self._last_signature: Optional[str] = None
    
    def evaluate(
        self,
        error_signature: Optional[str] = None,
        similarity_score: float = 0.0,
        current_iteration: int = 0
    ) -> RetrievalDecision:
        """Evaluate if retrieval should be triggered.
        
        Args:
            error_signature: Hash of the current error
            similarity_score: Similarity to previous errors (from vector search)
            current_iteration: Current iteration number
            
        Returns:
            RetrievalDecision with should_retrieve flag and reason
        """
        # Track error signatures for repetition detection
        repeated_count = 0
        if error_signature:
            if self._last_signature == error_signature:
                repeated_count = self._error_signatures.count(error_signature) + 1
            self._error_signatures.append(error_signature)
            self._last_signature = error_signature
        
        trigger = RetrievalTrigger(
            error_signature=error_signature or "",
            similarity_score=similarity_score,
            threshold=self.default_threshold,
            repeated_failure_count=repeated_count,
            repeated_failure_threshold=self.repeated_threshold
        )
        
        return RetrievalDecision(
            should_retrieve=trigger.should_retrieve(),
            reason=trigger.get_reason(),
            trigger=trigger
        )
    
    def reset(self) -> None:
        """Reset the trigger state for a new workflow."""
        self._error_signatures = []
        self._last_signature = None


def compute_similarity(text1: str, text2: str) -> float:
    """Compute simple similarity score between two texts.
    
    Uses Jaccard similarity on word tokens.
    In production, this should use proper embedding vectors.
    """
    if not text1 or not text2:
        return 0.0
    
    words1 = set(text1.lower().split())
    words2 = set(text2.lower().split())
    
    if not words1 or not words2:
        return 0.0
    
    intersection = words1 & words2
    union = words1 | words2
    
    return len(intersection) / len(union) if union else 0.0
