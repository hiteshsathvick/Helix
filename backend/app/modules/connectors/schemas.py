import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class WebConnectorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    url_list: list[str] = Field(min_length=1)


class ConnectorRead(BaseModel):
    id: uuid.UUID
    type: str
    name: str
    # "active" (connected/idle) | "syncing" | "error"
    status: str
    last_synced_at: datetime | None
    last_sync_error: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class GitHubAuthorizeResponse(BaseModel):
    authorize_url: str
