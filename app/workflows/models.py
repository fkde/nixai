from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    max_parallel: int = Field(
        default=1,
        ge=1,
        le=8,
        description="Concurrency cap for simultaneously running worker items.",
    )
    max_items: int = Field(default=4, ge=1, le=12)
    expects_json: bool = False
    receive_from: list[str] = Field(default_factory=list)
    reports_to: list[str] = Field(default_factory=list)
    worker_instances: int = Field(
        default=1,
        ge=1,
        le=8,
        description="Worker pool size; max_parallel remains the concurrency cap.",
    )
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

    @field_validator("receive_from", "reports_to", mode="before")
    @classmethod
    def normalize_node_links(cls, value: Any) -> list[str]:
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
    mode: MessageMode = "chat"
    modes: list[MessageMode] = Field(default_factory=list)
    execution: WorkflowExecution = "loop"
    max_iterations: int = Field(default=1, ge=1, le=8)
    nodes: list[WorkflowNode] = Field(default_factory=list)
    edges: list[WorkflowEdge] = Field(default_factory=list)

    @field_validator("modes", mode="before")
    @classmethod
    def normalize_modes(cls, value: Any) -> list[MessageMode]:
        if value is None or value == "":
            return []
        raw_modes = value if isinstance(value, list) else [value]
        modes: list[MessageMode] = []
        for item in raw_modes:
            mode = str(item).strip().lower()
            if mode in {"chat", "code", "agentic"} and mode not in modes:
                modes.append(mode)  # type: ignore[arg-type]
        return modes

    def is_direct(self) -> bool:
        return self.execution == "direct"

    def node(self, node_id: str) -> WorkflowNode | None:
        return next((node for node in self.nodes if node.id == node_id), None)

    def supported_modes(self) -> list[MessageMode]:
        return self.modes or [self.mode]

    def supports_mode(self, mode: MessageMode) -> bool:
        return mode in self.supported_modes()

    @model_validator(mode="after")
    def sync_node_links_and_edges(self) -> "WorkflowDefinition":
        """Keep links and edges aligned; explicit edges are the canonical source."""
        node_ids = {node.id for node in self.nodes if node.id}
        if not node_ids:
            return self

        if self.edges:
            incoming: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
            outgoing: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
            for edge in self.edges:
                source = edge.from_node
                target = edge.to
                if source in node_ids and target in node_ids:
                    outgoing[source].add(target)
                    incoming[target].add(source)
            for node in self.nodes:
                node.receive_from = sorted(incoming.get(node.id, set()))
                node.reports_to = sorted(outgoing.get(node.id, set()))
            return self

        seen: set[tuple[str, str, str]] = set()
        derived: list[WorkflowEdge] = []

        def add_edge(from_node: str, to_node: str) -> None:
            if from_node not in node_ids or to_node not in node_ids:
                return
            key = (from_node, to_node, "")
            if key in seen:
                return
            seen.add(key)
            derived.append(WorkflowEdge.model_validate({"from": from_node, "to": to_node}))

        for node in self.nodes:
            for source in node.receive_from:
                add_edge(str(source).strip(), node.id)
            for target in node.reports_to:
                add_edge(node.id, str(target).strip())
        self.edges = derived
        return self


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
    mode: MessageMode = "chat"
    modes: list[MessageMode] = Field(default_factory=list)
    execution: WorkflowExecution = "loop"
    max_iterations: int = 1
    nodes: list[WorkflowNode] = Field(default_factory=list)
    edges: list[WorkflowEdge] = Field(default_factory=list)
