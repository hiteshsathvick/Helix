"""Arq worker entrypoint — run via `arq app.workers.run.WorkerSettings`
(see docker-compose.yml). Registers the ingestion pipeline's and agents
module's tasks; future phases (workflows) register their own tasks here
too.
"""

from arq import func as arq_func
from arq.connections import RedisSettings
from arq.cron import cron
from prometheus_client import start_http_server

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.tracing import configure_tracing, traced_task

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
# Hardcoded, not settings.otel_service_name -- that setting is main.py's
# (the api process reads it from the same .env the worker does, so a
# shared setting can't give the two processes different names). Every
# span this process creates needs to show up as "helix-worker" in Tempo/
# Grafana, distinct from the api process's spans, for "API -> worker" to
# read as one trace crossing two services rather than one undifferentiated
# blob (SPEC.md §30).
configure_tracing("helix-worker")
# The worker has no request/response cycle to hang a /metrics route on the
# way main.py's Instrumentator().expose() does -- this is prometheus_client's
# own standalone server, just for this process's registry (SPEC.md §30's
# worker job/queue/DLQ metrics). Port matches infra/prometheus/prometheus.yml's
# helix-worker scrape target and docker-compose.yml's worker port mapping.
start_http_server(9100)

_settings = get_settings()


class WorkerSettings:
    functions = [
        arq_func(traced_task(ingest_document_task), max_tries=_settings.ingestion_max_job_attempts),
        arq_func(traced_task(run_agent_task), max_tries=_settings.agent_max_job_attempts),
        arq_func(
            traced_task(execute_workflow_run_task),
            max_tries=_settings.workflow_run_max_job_attempts,
        ),
        arq_func(traced_task(dispatch_domain_event_task), max_tries=3),
        arq_func(
            traced_task(sync_connector_task), max_tries=_settings.connector_sync_max_job_attempts
        ),
        arq_func(
            traced_task(send_notification_task),
            max_tries=_settings.notification_max_job_attempts,
        ),
        arq_func(traced_task(dispatch_webhooks_for_event_task), max_tries=3),
        arq_func(
            traced_task(deliver_webhook_task),
            max_tries=_settings.webhook_delivery_max_job_attempts,
        ),
    ]
    # Fixed, platform-wide periodic sweeps (SPEC.md §26 connector syncs,
    # §23 notification digests) -- not per-item dynamic schedules, which
    # is exactly the case Phase 13 deliberately left for Arq's own static
    # cron support rather than adding a new dependency.
    cron_jobs = [
        cron(
            traced_task(sweep_connector_syncs_task),
            minute=set(range(0, 60, _settings.connector_sync_interval_minutes)),
        ),
        cron(
            traced_task(send_digest_task),
            hour={_settings.notification_digest_hour},
            minute={0},
        ),
    ]
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
