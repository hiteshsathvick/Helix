"""Arq worker entrypoint — run via `arq app.workers.run.WorkerSettings`
(see docker-compose.yml). Registers the ingestion pipeline's and agents
module's tasks; future phases (workflows) register their own tasks here
too.
"""

from arq import func as arq_func
from arq.connections import RedisSettings
from arq.cron import cron

from app.core.config import get_settings
from app.core.logging import configure_logging

# Every module's models must be imported somewhere before SQLAlchemy's
# mapper configuration runs, or FK strings like ForeignKey("organizations.id")
# fail to resolve — the API process gets this for free by importing the
# full router tree (app.main), but this worker entrypoint only ever
# imports the tasks it registers below, so it needs the same explicit
# imports alembic/env.py already carries for the same reason. Phase 10
# learned this the hard way: a module missing here means every job that
# touches its models crash-loops silently, undetected by tests (which all
# run inside the full FastAPI app's process, which imports every model
# transitively) until a real worker actually runs one.
from app.modules.agents import models as agents_models  # noqa: F401
from app.modules.agents.tasks import run_agent_task
from app.modules.api import models as api_models  # noqa: F401
from app.modules.api.tasks import deliver_webhook_task, dispatch_webhooks_for_event_task
from app.modules.assistant import models as assistant_models  # noqa: F401
from app.modules.auth import models as auth_models  # noqa: F401
from app.modules.connectors.tasks import sweep_connector_syncs_task, sync_connector_task
from app.modules.documents import models as documents_models  # noqa: F401
from app.modules.events import models as events_models  # noqa: F401
from app.modules.ingestion import models as ingestion_models  # noqa: F401
from app.modules.ingestion.tasks import ingest_document_task
from app.modules.notifications import models as notifications_models  # noqa: F401
from app.modules.notifications.tasks import send_digest_task, send_notification_task
from app.modules.orgs import models as orgs_models  # noqa: F401
from app.modules.workflows import models as workflows_models  # noqa: F401
from app.modules.workflows.tasks import dispatch_domain_event_task, execute_workflow_run_task

configure_logging()

_settings = get_settings()


class WorkerSettings:
    functions = [
        arq_func(ingest_document_task, max_tries=_settings.ingestion_max_job_attempts),
        arq_func(run_agent_task, max_tries=_settings.agent_max_job_attempts),
        arq_func(execute_workflow_run_task, max_tries=_settings.workflow_run_max_job_attempts),
        arq_func(dispatch_domain_event_task, max_tries=3),
        arq_func(sync_connector_task, max_tries=_settings.connector_sync_max_job_attempts),
        arq_func(send_notification_task, max_tries=_settings.notification_max_job_attempts),
        arq_func(dispatch_webhooks_for_event_task, max_tries=3),
        arq_func(deliver_webhook_task, max_tries=_settings.webhook_delivery_max_job_attempts),
    ]
    # Fixed, platform-wide periodic sweeps (SPEC.md §26 connector syncs,
    # §23 notification digests) -- not per-item dynamic schedules, which
    # is exactly the case Phase 13 deliberately left for Arq's own static
    # cron support rather than adding a new dependency.
    cron_jobs = [
        cron(
            sweep_connector_syncs_task,
            minute=set(range(0, 60, _settings.connector_sync_interval_minutes)),
        ),
        cron(send_digest_task, hour={_settings.notification_digest_hour}, minute={0}),
    ]
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
