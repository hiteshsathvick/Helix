"""Notification template registry (SPEC.md §23 "templated messages").
Plain `.format()` templates, not a templating-engine dependency -- the
need is modest (a handful of short, reviewable-in-git strings), mirroring
ai/prompts.py's PromptRegistry shape at a conceptual level without pulling
in Jinja2 for it.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NotificationTemplate:
    event_type: str
    subject_template: str  # email only -- unused for in_app
    body_template: str


_REGISTRY: dict[str, NotificationTemplate] = {
    # The agents `notify` tool / workflows `notify` node catch-all --
    # both origins are functionally identical ("someone explicitly asked
    # to notify someone"), so v1 doesn't distinguish them as separate
    # preference-controllable event types.
    "notify.manual": NotificationTemplate(
        event_type="notify.manual",
        subject_template="{subject}",
        body_template="{message}",
    ),
    # The one real system-notification producer this phase wires up (see
    # connectors/service.py::run_sync) -- picked because it already has a
    # concrete failure path (Source.status="error"/last_sync_error) with
    # zero user-facing signal today.
    "connector.sync_failed": NotificationTemplate(
        event_type="connector.sync_failed",
        subject_template="Sync failed: {source_name}",
        body_template="The connector sync for {source_name} failed: {error}",
    ),
}


def render_template(event_type: str, payload: dict[str, Any]) -> tuple[str, str]:
    """Returns (subject, body). Falls back to the generic "notify.manual"
    template for an unregistered event_type rather than raising -- a
    caller-supplied payload with a `message`/`subject` key still renders
    sensibly even if `event_type` doesn't match a specific template.
    """
    template = _REGISTRY.get(event_type, _REGISTRY["notify.manual"])
    return template.subject_template.format(**payload), template.body_template.format(**payload)
