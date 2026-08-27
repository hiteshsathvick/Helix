import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.mixins import SoftDeleteMixin, TenantScopedMixin, TimestampMixin, UUIDPKMixin


class Workflow(UUIDPKMixin, TimestampMixin, SoftDeleteMixin, TenantScopedMixin, Base):
    __tablename__ = "workflows"

    name: Mapped[str] = mapped_column(String(255))
    # "draft" (not eligible to fire on event/schedule/webhook triggers,
    # manual trigger still works) | "active" | "disabled".
    status: Mapped[str] = mapped_column(String(20), default="draft")
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    # Random per-workflow secret for the inbound webhook trigger
    # (POST /webhooks/workflows/{id}) — the caller has no org membership, so
    # this token is the entire access-control boundary for that endpoint.
    webhook_secret: Mapped[str] = mapped_column(String(64))
    # No current_version_id pointer: deliberately avoided to sidestep a
    # circular FK with workflow_versions (workflows <-> workflow_versions
    # would each need a forward reference to the other at DDL time). "The
    # current version" is simply the highest `version` for this workflow_id
    # — see workflows/service.py::get_current_version. A WorkflowRun always
    # captures its own version_id at creation time regardless (see below),
    # which is what actually matters for SPEC.md §20's versioning guarantee.


class WorkflowVersion(UUIDPKMixin, TimestampMixin, TenantScopedMixin, Base):
    __tablename__ = "workflow_versions"

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflows.id"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    # {"nodes": [{"id": str, "type": "trigger"|"action"|"ai"|"condition"|"notify",
    #             "config": {...}}],
    #  "edges": [{"from": node_id, "to": node_id, "condition": "true"|"false"|None}]}
    # Validated at the API boundary (workflows/schemas.py), not by a DB
    # constraint — same reasoning as Agent.allowed_tools in Phase 12.
    graph: Mapped[dict] = mapped_column(JSONB)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    __table_args__ = (UniqueConstraint("workflow_id", "version"),)


class WorkflowRun(UUIDPKMixin, TimestampMixin, TenantScopedMixin, Base):
    __tablename__ = "workflow_runs"

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflows.id"), nullable=False, index=True
    )
    # Captured once at run creation and never re-resolved — this is what
    # gives SPEC.md §20's versioning guarantee for free: editing a workflow
    # (creating a new WorkflowVersion) has zero effect on an in-flight run,
    # since the executor only ever reads WorkflowRun.version_id, never
    # Workflow's "current" version, once a run exists.
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_versions.id"), nullable=False, index=True
    )
    # "pending" -> "running" -> "completed" | "failed" | "cancelled"
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # {"type": "manual"|"event"|"schedule"|"webhook", ...trigger-specific}
    trigger: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Accumulated node outputs keyed by node_id, plus the trigger payload —
    # the run's working memory. condition nodes and action/ai nodes' "$ref"
    # templated args resolve against this (workflows/conditions.py).
    context: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Null for event/webhook-triggered runs (no human triggered them).
    triggered_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), default=None
    )
    # Ties an event to the run(s) it spawned, and a webhook/manual run to
    # itself — SPEC.md §21 "events carry org_id and a correlation id".
    correlation_id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4, index=True)
    # Summed AI-node token spend for this run (ai node type only) — same
    # role as AgentRun.cost, checked against the org's shared monthly cap
    # before a new run is created (workflows/service.py, mirrors
    # agents/service.py's _get_monthly_spend pattern).
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class StepRun(UUIDPKMixin, TimestampMixin, TenantScopedMixin, Base):
    __tablename__ = "step_runs"

    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_runs.id"), nullable=False, index=True
    )
    # Matches a node's "id" in the version's graph jsonb — not a FK, since
    # nodes live inside jsonb, not their own table.
    node_id: Mapped[str] = mapped_column(String(100))
    # "trigger" | "action" | "ai" | "condition" | "notify"
    node_type: Mapped[str] = mapped_column(String(20))
    # "pending" -> "running" -> "succeeded" | "failed" | "dlq" | "skipped"
    # ("skipped" = a condition node's branch this node was on wasn't taken).
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    # Backoff scheduling for a failed-but-retryable node (workflows/
    # executor.py) — null until a retry is pending.
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    input: Mapped[dict] = mapped_column(JSONB, default=dict)
    output: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text, default=None)

    # One StepRun per node per run — this is what makes re-deriving the
    # ready frontier after a crash safe (workflows/executor.py): a second
    # attempt to create the same node's row is a no-op, not a duplicate.
    __table_args__ = (UniqueConstraint("workflow_run_id", "node_id"),)
