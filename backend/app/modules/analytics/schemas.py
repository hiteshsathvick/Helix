from pydantic import BaseModel

from app.modules.billing.schemas import UsageSummary


class AnalyticsOverview(BaseModel):
    month: str
    usage: UsageSummary
    agent_runs_by_status: dict[str, int]
    workflow_runs_by_status: dict[str, int]
    documents_by_status: dict[str, int]
    active_users: int
