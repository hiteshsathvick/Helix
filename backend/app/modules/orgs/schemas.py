import re
import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class OrgCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        if not _SLUG_PATTERN.match(value):
            raise ValueError("slug must be lowercase alphanumeric with hyphens (e.g. 'acme-corp')")
        return value


class OrgRead(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    plan: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MemberRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    status: str
    created_at: datetime


class InvitationCreate(BaseModel):
    email: EmailStr


class InvitationRead(BaseModel):
    id: uuid.UUID
    email: str
    status: str
    expires_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class InvitationCreatedResponse(BaseModel):
    invitation: InvitationRead
    # Shown once, at creation time, the same way a refresh token is: the
    # inviter copies/shares this manually since there's no email delivery
    # yet (that's Phase 15, the notifications module).
    token: str
