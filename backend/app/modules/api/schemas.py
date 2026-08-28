import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

SCOPES = Literal["search:read", "documents:read", "documents:write"]


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    scopes: list[SCOPES] = Field(min_length=1)


class ApiKeyRead(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str
    scopes: list[str]
    last_used_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiKeyCreatedResponse(BaseModel):
    key: ApiKeyRead
    raw_key: str  # shown exactly once


class WebhookCreate(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    events: list[str] = Field(min_length=1)


class WebhookRead(BaseModel):
    id: uuid.UUID
    url: str
    events: list[str]
    active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class WebhookCreatedResponse(BaseModel):
    webhook: WebhookRead
    secret: str  # shown exactly once


class WebhookDeliveryRead(BaseModel):
    id: uuid.UUID
    event_type: str
    status: str
    response_status: int | None
    attempts: int
    error: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
