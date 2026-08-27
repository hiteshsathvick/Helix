import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.modules.agents.tools import TOOLS


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    instructions: str = Field(min_length=1)
    allowed_tools: list[str] = Field(default_factory=list)

    @field_validator("allowed_tools")
    @classmethod
    def _validate_tools(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - TOOLS.keys())
        if unknown:
            raise ValueError(f"unknown tools: {unknown}; available: {sorted(TOOLS.keys())}")
        return value


class AgentRead(BaseModel):
    id: uuid.UUID
    name: str
    instructions: str
    allowed_tools: list[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class AgentRunTrigger(BaseModel):
    input: str = Field(min_length=1)


class AgentRunSummary(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    status: str
    created_at: datetime
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class AgentStepRead(BaseModel):
    id: uuid.UUID
    ordinal: int
    type: str
    tool: str | None
    input: dict[str, Any]
    output: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class AgentRunDetail(AgentRunSummary):
    input: str
    output: str | None
    error: str | None
    tokens: int
    cost: float
    steps: list[AgentStepRead]
