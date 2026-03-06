"""Agent state definitions and checkpoint model."""
from __future__ import annotations
from typing import TypedDict, Dict, Any, Optional
from pydantic import BaseModel, Field


class AgentState(TypedDict, total=False):
    goal: str
    plan: str
    generated_code: str
    static_analysis_result: Dict[str, Any]
    execution_result: Dict[str, Any]
    test_result: Dict[str, Any]
    reflection: str
    iteration: int
    max_iterations: int
    last_error_signature: Optional[str]
    repeated_error_count: int
    cost_accumulated: float
    status: str


class AgentStateModel(BaseModel):
    goal: str = Field(...)
    plan: str = Field(default="")
    generated_code: str = Field(default="")
    static_analysis_result: Dict[str, Any] = Field(default_factory=dict)
    execution_result: Dict[str, Any] = Field(default_factory=dict)
    test_result: Dict[str, Any] = Field(default_factory=dict)
    reflection: str = Field(default="")
    iteration: int = Field(default=0)
    max_iterations: int = Field(default=8)
    last_error_signature: Optional[str] = Field(default=None)
    repeated_error_count: int = Field(default=0)
    cost_accumulated: float = Field(default=0.0)
    status: str = Field(default="RUNNING")

    model_config = {"extra": "forbid"}

