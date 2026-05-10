from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import MessageMode


WorkflowExecution = Literal["direct", "loop"]


class WorkflowNode(BaseModel):
    id: str
    type: str
    role: str = ""
    title: str = ""
    prompt: str = ""
    input: list[str] = Field(default_factory=list)
    output: str = ""
    max_parallel: int = Field(default=1, ge=1, le=8)
    max_items: int = Field(default=4, ge=1, le=12)
    expects_json: bool = False
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("input", mode="before")
    @classmethod
    def normalize_input(cls, value: Any) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        return []


class WorkflowEdge(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_node: str = Field(alias="from")
    to: str
    when: str = ""


class WorkflowDefinition(BaseModel):
    id: str
    name: str
    description: str = ""
    mode: MessageMode
    execution: WorkflowExecution = "loop"
    max_iterations: int = Field(default=1, ge=1, le=8)
    nodes: list[WorkflowNode] = Field(default_factory=list)
    edges: list[WorkflowEdge] = Field(default_factory=list)

    def is_direct(self) -> bool:
        return self.execution == "direct"

    def node(self, node_id: str) -> WorkflowNode | None:
        return next((node for node in self.nodes if node.id == node_id), None)


class WorkflowEvent(BaseModel):
    node: str
    type: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class WorkflowResult(BaseModel):
    workflow_id: str
    answer: str
    status: str = "done"
    events: list[WorkflowEvent] = Field(default_factory=list)
    state: dict[str, Any] = Field(default_factory=dict)


class WorkflowSummary(BaseModel):
    id: str
    name: str
    description: str = ""
    mode: MessageMode
    execution: WorkflowExecution = "loop"
    max_iterations: int = 1
    nodes: list[WorkflowNode] = Field(default_factory=list)
    edges: list[WorkflowEdge] = Field(default_factory=list)
