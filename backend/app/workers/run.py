"""Arq worker entrypoint — run via `arq app.workers.run.WorkerSettings`
(see docker-compose.yml). Registers the ingestion pipeline's task; future
phases (agents, workflows) register their own tasks here too.
"""

from arq import func as arq_func
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.modules.ingestion.tasks import ingest_document_task

configure_logging()

_settings = get_settings()


class WorkerSettings:
    functions = [arq_func(ingest_document_task, max_tries=_settings.ingestion_max_job_attempts)]
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
