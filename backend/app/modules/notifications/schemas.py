import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class NotificationRead(BaseModel):
    id: uuid.UUID
    channel: str
    event_type: str
    subject: str | None
    body: str
    status: str
    read_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationInboxResponse(BaseModel):
    results: list[NotificationRead]
    next_cursor: str | None


class NotificationPrefRead(BaseModel):
    channel: str
    event: str
    enabled: bool
    frequency: str


class NotificationPrefUpdate(BaseModel):
    channel: Literal["email", "in_app"]
    event: str
    enabled: bool
    frequency: Literal["immediate", "digest"] = "immediate"


class NotificationPrefsUpdateRequest(BaseModel):
    prefs: list[NotificationPrefUpdate] = Field(min_length=1)

    def as_dicts(self) -> list[dict[str, Any]]:
        return [pref.model_dump() for pref in self.prefs]
