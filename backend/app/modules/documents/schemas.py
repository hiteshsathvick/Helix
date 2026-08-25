import uuid
from datetime import datetime

from pydantic import BaseModel


class DocumentRead(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    title: str
    mime: str
    status: str
    checksum: str
    uploaded_by_user_id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}
