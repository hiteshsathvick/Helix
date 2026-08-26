import uuid
from datetime import datetime

from pydantic import BaseModel


class QueryRequest(BaseModel):
    query: str
    conversation_id: uuid.UUID | None = None


class Citation(BaseModel):
    document_id: uuid.UUID
    document_title: str
    chunk_id: uuid.UUID
    ordinal: int
    snippet: str


class MessageRead(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    citations: list[Citation]
    tokens: int
    cost: float
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationSummary(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationRead(ConversationSummary):
    messages: list[MessageRead]
