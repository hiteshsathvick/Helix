"""OpenTelemetry setup (SPEC.md §30). Both the api and worker processes call
`configure_tracing()` once at startup, each with their own `service_name`
(app/main.py uses the config default "helix-api"; app/workers/run.py passes
"helix-worker") -- otherwise every span from both processes would show up
under one indistinguishable service in Tempo/Grafana, defeating the point
of a "trace spans API -> worker -> LLM" view.

Instrumenting SQLAlchemy/redis-py happens here too (shared by both
processes); FastAPI instrumentation stays in main.py since it needs the
`app` instance, which this module never has.
"""

import time
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, TypeVar, cast

from opentelemetry import propagate, trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import get_settings
from app.core.metrics import worker_job_duration_seconds, worker_jobs_total

tracer = trace.get_tracer("helix")


def configure_tracing(service_name: str) -> None:
    settings = get_settings()
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint))
    )
    trace.set_tracer_provider(provider)

    RedisInstrumentor().instrument()


def instrument_sqlalchemy_engine(engine: AsyncEngine) -> None:
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)


def inject_trace_context() -> dict[str, str]:
    """Call at enqueue time (core/queue.py) to capture the current trace
    context onto the job payload -- an arq job runs in a separate worker
    process with no context of its own otherwise, so without this every
    job would start a disconnected root span instead of continuing the
    request that enqueued it (SPEC.md §30 "a single trace follows a
    request from ... API -> worker -> LLM")."""
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return carrier


_TaskFn = TypeVar("_TaskFn", bound=Callable[..., Awaitable[Any]])


def traced_task(fn: _TaskFn) -> _TaskFn:
    """Wraps an arq task function (workers/run.py's WorkerSettings.functions)
    so running it becomes a span that continues the trace from
    inject_trace_context above, plus worker_job_duration_seconds/
    worker_jobs_total (core/metrics.py) -- one wrapper applied at
    registration time, rather than repeating this in every task function's
    own body. `@wraps` preserves `fn.__name__`, which both arq's own
    registration and core/queue.py's enqueue_job(<name>, ...) calls key on
    by string, so job dispatch-by-name is unaffected. Cron-triggered tasks
    (no enqueuer, hence no _trace_context) fall back to a fresh root span
    via propagate.extract({}).

    Typed as `_TaskFn -> _TaskFn` (same TypeVar both ends), not the wrapper's
    own true signature (which adds a `_trace_context` kwarg) -- arq's own
    stubs (`arq.func`/`arq.cron`) expect exactly the original task's type at
    every call site in workers/run.py, and the actual extra kwarg is only
    ever supplied by core/queue.py/arq's own job dispatch, never by a type
    checker walking that call. `cast` at the return makes that intentional
    type-preserving-decorator shape explicit rather than an accident of
    inference."""
    task_name = fn.__name__

    @wraps(fn)
    async def wrapper(
        ctx: dict[str, Any], *args: Any, _trace_context: dict[str, str] | None = None, **kwargs: Any
    ) -> Any:
        parent_context = propagate.extract(_trace_context or {})
        start = time.perf_counter()
        status = "error"
        with tracer.start_as_current_span(f"worker.{task_name}", context=parent_context) as span:
            span.set_attribute("worker.task", task_name)
            try:
                result = await fn(ctx, *args, **kwargs)
                status = "success"
                return result
            finally:
                worker_job_duration_seconds.labels(task_name).observe(time.perf_counter() - start)
                worker_jobs_total.labels(task_name, status).inc()

    return cast("_TaskFn", wrapper)
