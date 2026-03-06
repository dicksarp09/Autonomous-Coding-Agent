"""Build LLM prompt from limited context (working memory + optional retrieval summary).

Enforces token caps and compression rules. Returns structured prompt payload.
Integrates with RetrievalTrigger for conditional memory retrieval and Summarizer for compression.
"""
from __future__ import annotations
from typing import List, Dict, Any, Optional
from .memory.working_memory import WorkingMemory, IterationRecord
from .memory.retrieval_trigger import RetrievalTrigger, RetrievalTriggerManager, compute_similarity
from .memory.summarizer import summarize_failures


def _estimate_tokens(text: str) -> int:
    """Estimate token count using simple character-based heuristic."""
    return max(1, len(text) // 4)


def build_prompt(
    goal: str,
    plan: str,
    wm: WorkingMemory,
    retrieved_summary: Optional[str] = None,
    token_cap: int = 2048
) -> Dict[str, Any]:
    """Build prompt from goal, plan, working memory, and optional retrieval summary.
    
    Args:
        goal: Current goal/task
        plan: Current plan
        wm: Working memory instance
        retrieved_summary: Optional pre-retrieved memory summary
        token_cap: Maximum tokens to include
        
    Returns:
        Dict with 'prompt' and 'token_estimate' keys
    """
    # Include only specified pieces
    parts: List[str] = []
    parts.append(f"Goal:\n{goal}\n")
    parts.append(f"Plan:\n{plan}\n")

    recent = wm.get_recent(5)
    total_tokens = _estimate_tokens('\n'.join(parts))

    included = []
    for rec in recent[::-1]:
        est = rec.token_estimate or _estimate_tokens(rec.plan + rec.code_diff)
        if total_tokens + est > token_cap:
            break
        included.append(rec)
        total_tokens += est

    included_text = '\n'.join([f"Iteration {r.iteration_id}: plan={r.plan} diff={r.code_diff} error={r.error}" for r in reversed(included)])
    prompt = "\n".join(parts) + "\nRecent Iterations:\n" + included_text
    
    if retrieved_summary:
        # ensure adding summary doesn't exceed cap, truncate if needed
        summary_tokens = _estimate_tokens(retrieved_summary)
        if total_tokens + summary_tokens <= token_cap:
            prompt += "\nRetrieved Summary:\n" + retrieved_summary
        else:
            # truncate summary conservatively
            max_chars = max(50, (token_cap - total_tokens) * 4)
            prompt += "\nRetrieved Summary:\n" + retrieved_summary[:max_chars]

    return {"prompt": prompt, "token_estimate": total_tokens}


class ContextBuilder:
    """Manages context building with retrieval and summarization."""
    
    def __init__(
        self,
        token_cap: int = 2048,
        retrieval_threshold: float = 0.7,
        compression_ratio: float = 10.0
    ):
        self.token_cap = token_cap
        self.retrieval_threshold = retrieval_threshold
        self.compression_ratio = compression_ratio
        self.trigger_manager = RetrievalTriggerManager(default_threshold=retrieval_threshold)
        self._working_memory: Optional[WorkingMemory] = None
    
    def set_working_memory(self, wm: WorkingMemory) -> None:
        """Set the working memory instance."""
        self._working_memory = wm
    
    def build_context(
        self,
        goal: str,
        plan: str,
        error_text: Optional[str] = None,
        long_term_memory_results: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Build complete context for LLM prompt.
        
        Args:
            goal: Current goal
            plan: Current execution plan
            error_text: Optional error text for retrieval trigger evaluation
            long_term_memory_results: Optional results from long-term memory query
            
        Returns:
            Dict with 'prompt', 'token_estimate', 'retrieval_triggered', 'summary'
        """
        # Determine if we should retrieve from long-term memory
        retrieval_triggered = False
        summary = None
        
        if error_text and long_term_memory_results:
            # Evaluate retrieval trigger
            if long_term_memory_results:
                # Get similarity score from results
                max_similarity = 0.0
                for item in long_term_memory_results:
                    sim = compute_similarity(error_text, item.get('root_cause', '') + item.get('fix_summary', ''))
                    max_similarity = max(max_similarity, sim)
                
                decision = self.trigger_manager.evaluate(
                    similarity_score=max_similarity,
                    error_text=error_text
                )
                
                if decision.should_retrieve:
                    retrieval_triggered = True
                    # Summarize the retrieved failures
                    result = summarize_failures(long_term_memory_results, reason=decision.reason)
                    summary = result.get("summary", "")
        
        # Get working memory
        wm = self._working_memory or WorkingMemory(session_id="default")
        
        # Build the prompt
        return build_prompt(
            goal=goal,
            plan=plan,
            wm=wm,
            retrieved_summary=summary,
            token_cap=self.token_cap
        )
    
    def reset(self) -> None:
        """Reset state for new workflow."""
        self.trigger_manager.reset()
        if self._working_memory:
            self._working_memory.reset()
