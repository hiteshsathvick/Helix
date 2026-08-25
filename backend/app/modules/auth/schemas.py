import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserRead(BaseModel):
    id: uuid.UUID
    email: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead
