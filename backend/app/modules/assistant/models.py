import uuid

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.mixins import TenantScopedMixin, TimestampMixin, UUIDPKMixin


class Conversation(UUIDPKMixin, TimestampMixin, TenantScopedMixin, Base):
    __tablename__ = "conversations"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(500))


class Message(UUIDPKMixin, TimestampMixin, TenantScopedMixin, Base):
    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    # [{document_id, document_title, chunk_id, ordinal, snippet}, ...] — the
    # chunks actually included in context for this answer, not markers
    # parsed out of the model's own text (SPEC.md §18: "return citations
    # linking to chunks").
    citations: Mapped[list] = mapped_column(JSONB, default=list)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
