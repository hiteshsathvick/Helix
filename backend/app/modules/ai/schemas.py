from pydantic import BaseModel, Field, field_validator

KNOWN_PROVIDERS = {"anthropic", "openai", "ollama"}


class OrgAIConfigRead(BaseModel):
    provider: str
    model: str
    monthly_cost_cap_usd: float | None


class OrgAIConfigUpdate(BaseModel):
    provider: str | None = None
    model: str | None = Field(default=None, min_length=1)
    # Sent explicitly as `null` to clear an org-level override back to the
    # global default (core/config.py's ai_default_monthly_cost_cap_usd);
    # omitting the field entirely (checked via model_fields_set in
    # service.update_org_ai_config) leaves whatever is currently set alone.
    monthly_cost_cap_usd: float | None = Field(default=None, ge=0)

    @field_validator("provider")
    @classmethod
    def _validate_provider(cls, value: str | None) -> str | None:
        if value is not None and value not in KNOWN_PROVIDERS:
            raise ValueError(f"provider must be one of {sorted(KNOWN_PROVIDERS)}")
        return value
