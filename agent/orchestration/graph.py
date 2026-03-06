"""Deterministic LangGraph orchestrator with explicit conditional edges.

The orchestrator owns all routing decisions. Nodes are pure functions that
accept an `AgentStateModel` and return a tuple `(next_node: str | None, state)`.
Edges are explicit and deterministic.
"""
from __future__ import annotations
from typing import Callable, Dict, Optional
import logging
from ..telemetry.tracing import start_span
from .state import AgentStateModel

logger = logging.getLogger(__name__)


class CircuitOpen(Exception):
    pass


class LangGraph:
    def __init__(self):
        self.nodes: Dict[str, Callable[[AgentStateModel], tuple[Optional[str], AgentStateModel]]] = {}
        self.edges: Dict[str, Callable[[AgentStateModel], Optional[str]]] = {}

    def register_node(self, name: str, fn: Callable[[AgentStateModel], tuple[Optional[str], AgentStateModel]], route: Callable[[AgentStateModel], Optional[str]]):
        self.nodes[name] = fn
        self.edges[name] = route

    def run(self, entry: str, state: AgentStateModel) -> AgentStateModel:
        current = entry
        while current is not None:
            node_fn = self.nodes.get(current)
            if node_fn is None:
                logger.error("No node registered: %s", current)
                break
            with start_span("node", node_name=current, iteration=state.iteration):
                logger.info("Executing node=%s iteration=%d", current, state.iteration)
                next_node, state = node_fn(state)
            # edges are authoritative if provided
            if current in self.edges:
                routed = self.edges[current](state)
                if routed is not None:
                    current = routed
                    continue
            current = next_node
        return state
