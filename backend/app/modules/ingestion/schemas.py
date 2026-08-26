import uuid
from datetime import datetime

from pydantic import BaseModel


class JobRead(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    attempts: int
    error: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
