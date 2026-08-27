"""Condition/branch node evaluation (SPEC.md §20). A condition's config is
authored by an org admin and stored as jsonb — untrusted input from the
platform's own point of view, same as any other user-supplied data. This
module deliberately never evaluates it as code: a fixed allow-list of
comparison operators against a value resolved by a hand-rolled dotted-path
lookup, nothing else. `eval()`/`exec()` on workflow config would be a
code-execution vulnerability, not just bad practice (CLAUDE.md §5).
"""

from typing import Any

_OPS = ("eq", "ne", "gt", "gte", "lt", "lte", "contains", "exists")


def resolve_path(context: dict[str, Any], path: str) -> Any:
    """Dotted-path lookup into a nested dict/list, e.g. "trigger.payload.status"
    or "steps.node_1.output.count". Returns None for any missing segment —
    a missing path is a value, not an error, so conditions can safely test
    "does this exist yet" without raising.
    """
    current: Any = context
    for segment in path.split("."):
        if isinstance(current, dict):
            current = current.get(segment)
        elif isinstance(current, list):
            try:
                current = current[int(segment)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return current


def resolve_refs(value: Any, context: dict[str, Any]) -> Any:
    """Recursively resolves `{"$ref": "dotted.path"}` placeholders inside a
    node's config against the run's context, so a later node can use an
    earlier node's output (or the trigger payload) as its own input. Plain
    values pass through unchanged; a dict that is exactly `{"$ref": ...}` is
    replaced by the resolved value, other dicts/lists are resolved
    element-wise.
    """
    if isinstance(value, dict):
        if set(value.keys()) == {"$ref"}:
            return resolve_path(context, value["$ref"])
        return {key: resolve_refs(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_refs(item, context) for item in value]
    return value


def evaluate_condition(context: dict[str, Any], condition: dict[str, Any]) -> bool:
    """condition shape: {"left": {"path": "..."}, "op": "eq", "right": <value>}.
    `op` must be one of _OPS — anything else is a validation-time error
    (workflows/schemas.py), never something this function silently coerces.
    """
    left = resolve_path(context, condition["left"]["path"])
    op = condition["op"]
    right = condition.get("right")

    if op == "exists":
        return left is not None
    if op == "eq":
        return left == right
    if op == "ne":
        return left != right
    if op == "contains":
        try:
            return right in left
        except TypeError:
            return False
    if op in ("gt", "gte", "lt", "lte"):
        if not isinstance(left, int | float) or not isinstance(right, int | float):
            return False
        if op == "gt":
            return left > right
        if op == "gte":
            return left >= right
        if op == "lt":
            return left < right
        return left <= right

    raise ValueError(f"unsupported condition operator: {op!r}; must be one of {_OPS}")
