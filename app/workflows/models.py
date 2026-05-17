from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import MessageMode
from app.validation import (
    MAX_DESCRIPTION_LENGTH,
    MAX_NAME_LENGTH,
    MAX_PROMPT_LENGTH,
    MAX_TITLE_LENGTH,
    clean_single_line,
    clean_text,
    validate_slug,
)


WorkflowExecution = Literal["direct", "loop"]


class WorkflowRetryPolicy(BaseModel):
    max: int = Field(default=0, ge=0, le=5)
    backoff: float = Field(default=0.0, ge=0.0, le=30.0)


class NodePosition(BaseModel):
    """Canvas coordinates for the visual workflow builder.

    Stored on the node so layouts survive reload. Defaults to (0, 0); the
    frontend falls back to an auto-layout when every node sits at the origin.
    """

    x: float = 0.0
    y: float = 0.0

    @field_validator("x", "y", mode="before")
    @classmethod
    def _clamp_coord(cls, value: Any) -> float:
        try:
            num = float(value)
        except (TypeError, ValueError):
            return 0.0
        if num != num:  # NaN
            return 0.0
        if num < -10000.0:
            return -10000.0
        if num > 10000.0:
            return 10000.0
        return num


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
        description="Maximum worker instances the planner may use; max_parallel remains the hard concurrency cap.",
    )
    position: NodePosition = Field(default_factory=NodePosition)
    config: dict[str, Any] = Field(default_factory=dict)
    retry: WorkflowRetryPolicy = Field(default_factory=WorkflowRetryPolicy)
    break_when: str = ""
    ref: str = ""

    @field_validator("id", mode="before")
    @classmethod
    def _validate_id(cls, value: Any) -> str:
        return validate_slug(value, field_name="node id")

    @field_validator("type", mode="before")
    @classmethod
    def _clean_type(cls, value: Any) -> str:
        node_type = clean_single_line(value or "", max_length=MAX_NAME_LENGTH, field_name="value").lower()
        aliases = {
            "final": "answer",
            "judge": "decision",
            "reviewer": "report",
        }
        return aliases.get(node_type, node_type)

    @field_validator("role", "output", mode="before")
    @classmethod
    def _clean_short(cls, value: Any) -> str:
        return clean_single_line(value or "", max_length=MAX_NAME_LENGTH, field_name="value")

    @field_validator("break_when", "ref", mode="before")
    @classmethod
    def _clean_optional_short(cls, value: Any) -> str:
        return clean_single_line(value or "", max_length=MAX_PROMPT_LENGTH, field_name="value")

    @field_validator("title", mode="before")
    @classmethod
    def _clean_title(cls, value: Any) -> str:
        return clean_single_line(value or "", max_length=MAX_TITLE_LENGTH, field_name="title")

    @field_validator("prompt", mode="before")
    @classmethod
    def _clean_prompt(cls, value: Any) -> str:
        return clean_text(value or "", max_length=MAX_PROMPT_LENGTH, field_name="prompt")

    @field_validator("input", mode="before")
    @classmethod
    def normalize_input(cls, value: Any) -> list[str]:
        return _normalize_string_list(value)

    @field_validator("receive_from", "reports_to", mode="before")
    @classmethod
    def normalize_node_links(cls, value: Any) -> list[str]:
        return _normalize_string_list(value)


def _normalize_string_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    raw = value if isinstance(value, list) else [value]
    cleaned: list[str] = []
    for item in raw:
        text = str(item).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


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

    @field_validator("id", mode="before")
    @classmethod
    def _validate_id(cls, value: Any) -> str:
        return validate_slug(value, field_name="workflow id")

    @field_validator("name", mode="before")
    @classmethod
    def _clean_name(cls, value: Any) -> str:
        cleaned = clean_single_line(value or "", max_length=MAX_TITLE_LENGTH, field_name="name")
        if not cleaned:
            raise ValueError("name is required")
        return cleaned

    @field_validator("description", mode="before")
    @classmethod
    def _clean_description(cls, value: Any) -> str:
        return clean_text(value or "", max_length=MAX_DESCRIPTION_LENGTH, field_name="description")

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
        self._migrate_answer_node_id()
        node_ids = {node.id for node in self.nodes if node.id}
        if not node_ids:
            return self

        seen: set[tuple[str, str, str]] = set()
        merged: list[WorkflowEdge] = []

        def add_edge(from_node: str, to_node: str, when: str = "") -> None:
            if from_node not in node_ids or to_node not in node_ids:
                return
            key = (from_node, to_node, when)
            if key in seen:
                return
            seen.add(key)
            merged.append(WorkflowEdge.model_validate({"from": from_node, "to": to_node, "when": when}))

        explicit_edges = list(self.edges)
        for edge in explicit_edges:
            add_edge(edge.from_node, edge.to, edge.when)

        if not explicit_edges:
            for node in self.nodes:
                for source in node.receive_from:
                    add_edge(str(source).strip(), node.id)
                for target in node.reports_to:
                    add_edge(node.id, str(target).strip())

        incoming: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
        outgoing: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
        for edge in merged:
            outgoing[edge.from_node].add(edge.to)
            incoming[edge.to].add(edge.from_node)
        for node in self.nodes:
            node.receive_from = sorted(incoming.get(node.id, set()))
            node.reports_to = sorted(outgoing.get(node.id, set()))
        self.edges = merged
        return self

    def _migrate_answer_node_id(self) -> None:
        node_ids = {node.id for node in self.nodes if node.id}
        if "final" not in node_ids or "answer" in node_ids:
            return
        for node in self.nodes:
            if node.id == "final":
                node.id = "answer"
            node.receive_from = ["answer" if item == "final" else item for item in node.receive_from]
            node.reports_to = ["answer" if item == "final" else item for item in node.reports_to]
        for edge in self.edges:
            if edge.from_node == "final":
                edge.from_node = "answer"
            if edge.to == "final":
                edge.to = "answer"


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
