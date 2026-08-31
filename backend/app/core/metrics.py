"""Prometheus metrics (SPEC.md §30), defined once here and imported by
whichever module records them. prometheus_client's default registry raises
on a duplicate metric name, so every Counter/Histogram/Gauge the app owns
lives in exactly one place rather than being declared at each call site.

HTTP request metrics come for free from prometheus-fastapi-instrumentator
(main.py) -- everything here is the custom, business-specific half SPEC.md
§30 asks for: LLM cost/latency/tokens, worker job health, DLQ growth.
"""

from typing import cast

import redis as redis_sync
from prometheus_client import Counter, Gauge, Histogram

from app.core.config import get_settings

llm_requests_total = Counter(
    "helix_llm_requests_total", "LLM provider calls", ["provider", "model", "status"]
)
llm_request_duration_seconds = Histogram(
    "helix_llm_request_duration_seconds", "LLM provider call latency", ["provider", "model"]
)
llm_tokens_total = Counter(
    "helix_llm_tokens_total", "LLM tokens consumed", ["provider", "model", "direction"]
)
llm_cost_usd_total = Counter("helix_llm_cost_usd_total", "LLM spend in USD", ["provider", "model"])

worker_job_duration_seconds = Histogram(
    "helix_worker_job_duration_seconds", "Worker job execution time", ["task"]
)
worker_jobs_total = Counter("helix_worker_jobs_total", "Worker jobs completed", ["task", "status"])
dlq_jobs_total = Counter(
    "helix_dlq_jobs_total", "Jobs that exhausted retries and moved to the DLQ", ["task"]
)


def _sample_queue_depth() -> float:
    # A plain sync redis-py client, not core.redis.get_redis_client's async
    # one: prometheus_client's Gauge.set_function callback runs
    # synchronously at scrape time, called from inside the (async) /metrics
    # request handler -- a brief blocking round trip here every ~15s (a
    # typical scrape interval) is a fair trade against bridging an async
    # client into a sync callback for one cheap command. "arq:queue" is
    # arq's own default queue name (a Redis sorted set of pending + not-yet-
    # due deferred jobs) -- every core/queue.py enqueue call uses it since
    # none pass a custom _queue_name.
    settings = get_settings()
    client = redis_sync.Redis.from_url(settings.redis_url)
    try:
        # redis-py's command methods are typed to cover both its sync and
        # async clients from one shared signature (ResponseT includes
        # Awaitable[Any]) -- this client is the sync one, so the real
        # runtime return here is always an int.
        return float(cast(int, client.zcard("arq:queue")))
    finally:
        client.close()


queue_depth = Gauge("helix_queue_depth", "Pending + deferred jobs on the default arq queue")
queue_depth.set_function(_sample_queue_depth)
