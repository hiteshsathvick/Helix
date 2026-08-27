import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.modules.agents.tools import TOOLS

NODE_TYPES = ("trigger", "action", "ai", "condition", "notify")
_TOOL_NODE_TYPES = ("action", "ai")


class WorkflowNode(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    type: Literal["trigger", "action", "ai", "condition", "notify"]
    config: dict[str, Any] = Field(default_factory=dict)


class WorkflowEdge(BaseModel):
    from_node: str = Field(alias="from", min_length=1)
    to: str = Field(min_length=1)
    # Which branch of a condition node this edge follows; None for edges out
    # of any other node type (there's only ever one outgoing path).
    condition: Literal["true", "false"] | None = None

    model_config = {"populate_by_name": True}


class WorkflowGraph(BaseModel):
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_graph(self) -> "WorkflowGraph":
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("node ids must be unique")
        id_set = set(node_ids)

        for edge in self.edges:
            if edge.from_node not in id_set or edge.to not in id_set:
                raise ValueError(
                    f"edge references an unknown node id: {edge.from_node!r} -> {edge.to!r}"
                )

        for node in self.nodes:
            if node.type in _TOOL_NODE_TYPES:
                _validate_tool_config(node)

        _reject_cycles(node_ids, self.edges)
        return self


def _validate_tool_config(node: WorkflowNode) -> None:
    if node.type == "action":
        tool = node.config.get("tool")
        if tool not in TOOLS:
            raise ValueError(
                f"node {node.id!r}: unknown tool {tool!r}; available: {sorted(TOOLS.keys())}"
            )
    elif node.type == "ai":
        unknown = sorted(set(node.config.get("allowed_tools", [])) - TOOLS.keys())
        if unknown:
            raise ValueError(
                f"node {node.id!r}: unknown tools {unknown}; available: {sorted(TOOLS.keys())}"
            )


def _reject_cycles(node_ids: list[str], edges: list[WorkflowEdge]) -> None:
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for edge in edges:
        adjacency[edge.from_node].append(edge.to)

    WHITE, GRAY, BLACK = 0, 1, 2
    color = dict.fromkeys(node_ids, WHITE)

    def dfs(node_id: str) -> None:
        color[node_id] = GRAY
        for neighbor in adjacency[node_id]:
            if color[neighbor] == GRAY:
                raise ValueError(f"workflow graph contains a cycle involving node {neighbor!r}")
            if color[neighbor] == WHITE:
                dfs(neighbor)
        color[node_id] = BLACK

    for node_id in node_ids:
        if color[node_id] == WHITE:
            dfs(node_id)


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    graph: WorkflowGraph


class WorkflowUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    status: Literal["draft", "active", "disabled"] | None = None


class WorkflowRead(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    # Safe to return here: every caller who can GET a workflow already has
    # workflows:manage, which can already read/edit/trigger it directly --
    # seeing the secret needed to trigger it externally isn't a privilege
    # escalation, and the webhook trigger feature is unusable if the UI can
    # never actually show the caller the value they need to configure.
    webhook_secret: str
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkflowVersionCreate(BaseModel):
    graph: WorkflowGraph


class WorkflowVersionRead(BaseModel):
    id: uuid.UUID
    version: int
    graph: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkflowRunTrigger(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)


class WorkflowRunSummary(BaseModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    version_id: uuid.UUID
    status: str
    trigger: dict[str, Any]
    created_at: datetime
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class StepRunRead(BaseModel):
    id: uuid.UUID
    node_id: str
    node_type: str
    status: str
    attempts: int
    input: dict[str, Any]
    output: dict[str, Any]
    error: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkflowRunDetail(WorkflowRunSummary):
    context: dict[str, Any]
    cost: float
    error: str | None
    steps: list[StepRunRead]
