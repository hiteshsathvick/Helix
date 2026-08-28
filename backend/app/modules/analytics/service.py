from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agents import service as agents_service
from app.modules.analytics.schemas import AnalyticsOverview
from app.modules.audit import service as audit_service
from app.modules.billing import service as billing_service
from app.modules.documents import service as documents_service
from app.modules.workflows import service as workflows_service


def _month_start() -> datetime:
    return datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def get_overview(db: AsyncSession, org_id: UUID) -> AnalyticsOverview:
    """A dashboard-shaped aggregate (SPEC.md §27) built entirely from other
    modules' own service functions -- analytics owns no table of its own
    and never queries agents/workflows/documents/audit's tables directly
    (CLAUDE.md §3). "Top queries/gaps" and eval-score/thumbs quality
    metrics are explicitly out of scope for this phase: no query-text
    frequency tracking or user-feedback persistence exists anywhere yet,
    so surfacing them here would mean building a new feature, not wiring
    up analytics on data that already exists.
    """
    month_start = _month_start()
    usage = await billing_service.get_usage_summary(db, org_id)
    agent_runs_by_status = await agents_service.get_run_status_counts(db, org_id, month_start)
    workflow_runs_by_status = await workflows_service.get_run_status_counts(db, org_id, month_start)
    documents_by_status = await documents_service.get_status_counts(db, org_id)
    active_users = await audit_service.count_distinct_actors_since(db, org_id, month_start)

    return AnalyticsOverview(
        month=month_start.strftime("%Y-%m"),
        usage=usage,
        agent_runs_by_status=agent_runs_by_status,
        workflow_runs_by_status=workflow_runs_by_status,
        documents_by_status=documents_by_status,
        active_users=active_users,
    )
