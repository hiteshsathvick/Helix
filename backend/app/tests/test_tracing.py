"""Proves the actual DoD (SPEC.md §30 roadmap: "a single trace follows a
request from ... API -> worker -> LLM"), not just that instrumentation code
runs without erroring. Tested at the trace_id/context level rather than by
swapping in an InMemorySpanExporter: by the time these tests run,
app.main's module-level `app = create_app()` has already called
configure_tracing() once (importing app.main is how every other test file
gets a TestClient too), and OpenTelemetry's API deliberately ignores a
second trace.set_tracer_provider() call in the same process -- so a real
SDK TracerProvider is already active here regardless, which is exactly
what these tests exercise: real Span/context objects, independent of
whether the OTLP exporter can actually reach a collector in a test run.
"""

import pytest
from opentelemetry import propagate
from opentelemetry import trace as otel_trace

from app.core.metrics import worker_jobs_total
from app.core.tracing import inject_trace_context, traced_task, tracer


def test_inject_and_extract_trace_context_round_trips_the_same_trace():
    with tracer.start_as_current_span("test-parent") as parent_span:
        original_trace_id = parent_span.get_span_context().trace_id
        carrier = inject_trace_context()

    extracted_context = propagate.extract(carrier)
    extracted_span_context = otel_trace.get_current_span(extracted_context).get_span_context()
    assert extracted_span_context.trace_id == original_trace_id


@pytest.mark.asyncio
async def test_traced_task_continues_the_enqueuing_trace():
    # The actual API -> worker mechanism: core/queue.py captures a carrier
    # at enqueue time (inject_trace_context), the job crosses Redis to a
    # different process, and workers/run.py's traced_task wrapper extracts
    # it back into a real parent context -- this proves both ends produce
    # the *same* trace_id, not just that each half runs without error.
    captured_trace_ids: list[int] = []

    async def _fake_task(ctx: dict, value: str) -> str:
        captured_trace_ids.append(otel_trace.get_current_span().get_span_context().trace_id)
        return value

    wrapped = traced_task(_fake_task)

    with tracer.start_as_current_span("api-request") as api_span:
        original_trace_id = api_span.get_span_context().trace_id
        carrier = inject_trace_context()
    # Outside the `with` block on purpose: the real worker picks the job
    # up later, in its own call stack with no ambient span -- only the
    # carrier captured above (core/queue.py's actual shape).

    result = await wrapped({}, "payload", _trace_context=carrier)

    assert result == "payload"
    assert captured_trace_ids == [original_trace_id]


@pytest.mark.asyncio
async def test_traced_task_starts_a_fresh_trace_with_no_context():
    # Cron-triggered tasks (workers/run.py's cron_jobs) are never enqueued
    # via core/queue.py, so they never receive _trace_context -- must not
    # raise, must still run and get its own root span.
    async def _fake_task(ctx: dict) -> str:
        return "ran"

    wrapped = traced_task(_fake_task)
    assert await wrapped({}) == "ran"


@pytest.mark.asyncio
async def test_traced_task_records_worker_metrics():
    success_before = worker_jobs_total.labels("_metrics_test_task", "success")._value.get()

    async def _metrics_test_task(ctx: dict) -> None:
        return None

    _metrics_test_task.__name__ = "_metrics_test_task"
    await traced_task(_metrics_test_task)({})

    assert worker_jobs_total.labels("_metrics_test_task", "success")._value.get() == (
        success_before + 1
    )
