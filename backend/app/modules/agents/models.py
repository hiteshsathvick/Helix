import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.mixins import SoftDeleteMixin, TenantScopedMixin, TimestampMixin, UUIDPKMixin


class Agent(UUIDPKMixin, TimestampMixin, SoftDeleteMixin, TenantScopedMixin, Base):
    __tablename__ = "agents"

    name: Mapped[str] = mapped_column(String(255))
    instructions: Mapped[str] = mapped_column(Text)
    # Names must be keys in app/modules/agents/tools.py's TOOLS registry —
    # validated at the API boundary (agents/schemas.py), not by a DB
    # constraint, so adding a new tool never needs a migration.
    allowed_tools: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)


class AgentRun(UUIDPKMixin, TimestampMixin, TenantScopedMixin, Base):
    __tablename__ = "agent_runs"

    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id"), nullable=False, index=True)
    triggered_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    # "pending" (created, not yet picked up by a worker) -> "running" ->
    # "completed" | "failed". TimestampMixin.created_at doubles as
    # SPEC.md §10's `started_at` — a run row is created at the moment it
    # starts, so a separate column would only ever duplicate it.
    status: Mapped[str] = mapped_column(String(20), default="pending")
    input: Mapped[str] = mapped_column(Text)
    output: Mapped[str | None] = mapped_column(Text, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class AgentStep(UUIDPKMixin, TimestampMixin, TenantScopedMixin, Base):
    __tablename__ = "agent_steps"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    # "tool_call" | "final_answer"
    type: Mapped[str] = mapped_column(String(20))
    tool: Mapped[str | None] = mapped_column(String(100), default=None)
    input: Mapped[dict] = mapped_column(JSONB, default=dict)
    output: Mapped[dict] = mapped_column(JSONB, default=dict)
