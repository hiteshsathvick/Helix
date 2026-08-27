"""Arq worker entrypoint — run via `arq app.workers.run.WorkerSettings`
(see docker-compose.yml). Registers the ingestion pipeline's and agents
module's tasks; future phases (workflows) register their own tasks here
too.
"""

from arq import func as arq_func
from arq.connections import RedisSettings

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
from app.modules.assistant import models as assistant_models  # noqa: F401
from app.modules.auth import models as auth_models  # noqa: F401
from app.modules.documents import models as documents_models  # noqa: F401
from app.modules.ingestion import models as ingestion_models  # noqa: F401
from app.modules.ingestion.tasks import ingest_document_task
from app.modules.orgs import models as orgs_models  # noqa: F401

configure_logging()

_settings = get_settings()


class WorkerSettings:
    functions = [
        arq_func(ingest_document_task, max_tries=_settings.ingestion_max_job_attempts),
        arq_func(run_agent_task, max_tries=_settings.agent_max_job_attempts),
    ]
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
