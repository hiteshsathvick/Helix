import logging
import sys

from opentelemetry import trace

from app.core.request_context import request_id_var


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class TraceIdFilter(logging.Filter):
    """Log <-> trace correlation (SPEC.md §30): whichever span is active
    when a log line is emitted, formatted the way Tempo/Grafana expect so a
    trace_id in a log line is directly clickable/searchable there. "0" (an
    invalid trace_id) when nothing's tracing this code path -- harmless,
    not worth a conditional field."""

    def filter(self, record: logging.LogRecord) -> bool:
        span_context = trace.get_current_span().get_span_context()
        record.trace_id = format(span_context.trace_id, "032x")
        record.span_id = format(span_context.span_id, "016x")
        return True


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIdFilter())
    handler.addFilter(TraceIdFilter())
    handler.setFormatter(
        logging.Formatter(
            '{"level": "%(levelname)s", "logger": "%(name)s", '
            '"request_id": "%(request_id)s", "trace_id": "%(trace_id)s", '
            '"span_id": "%(span_id)s", "message": "%(message)s"}'
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)

    # uvicorn installs its own non-propagating handlers on these loggers;
    # clear them so access/error logs flow through our JSON formatter too.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers = []
        uv_logger.propagate = True
