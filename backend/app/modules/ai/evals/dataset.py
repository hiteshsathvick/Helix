"""Fixed offline eval set (SPEC.md §17 "Eval harness"). Small and
synthetic on purpose — its job is to catch a retrieval or prompt regression
in CI, not to be a representative corpus. Never edit a case in place once
it's shipped without also reviewing `MIN_HIT_RATE`/`MIN_MRR`/
`MIN_GROUNDED_RATE` in `runner.py` — a dataset change silently shifts what
those thresholds actually mean.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalDocument:
    key: str
    title: str
    content: str


@dataclass(frozen=True)
class EvalCase:
    query: str
    expected_doc_key: str
    expected_keywords: tuple[str, ...]


DOCUMENTS: tuple[EvalDocument, ...] = (
    EvalDocument(
        "helix-overview",
        "Helix Product Overview",
        "Helix is a multi-tenant, AI-native enterprise platform that makes an "
        "organization's knowledge searchable, answerable, and actionable. It ships "
        "with SSO, RBAC, billing, audit logging, and a public API.",
    ),
    EvalDocument(
        "helix-rag",
        "Helix RAG Pipeline",
        "The Helix assistant answers questions using retrieval-augmented generation. "
        "It retrieves chunks with hybrid search, assembles a token-budgeted context, "
        "and streams a grounded answer with citations linking back to source documents.",
    ),
    EvalDocument(
        "helix-tenancy",
        "Helix Multi-Tenancy Model",
        "Every tenant-scoped table in Helix carries an org_id column. Enforcement is "
        "layered: a base query layer auto-applies org_id from request context, and "
        "PostgreSQL row-level security policies act as defense-in-depth.",
    ),
    EvalDocument(
        "helix-workflows",
        "Helix Workflow Engine",
        "The Helix workflow engine is a durable, event-driven DAG executor. Runs are "
        "persisted as a state machine, so a crashed worker's run is resumable by "
        "another worker without losing progress.",
    ),
    EvalDocument(
        "coffee-brewing",
        "Pour-Over Coffee Brewing Guide",
        "A good pour-over starts with a 1:16 ratio of coffee to water. Rinse the "
        "filter first, bloom the grounds for 30 seconds, then pour in slow circles.",
    ),
    EvalDocument(
        "sourdough-bread",
        "Sourdough Bread Basics",
        "A sourdough starter needs regular feeding with equal parts flour and water. "
        "Fermentation time depends heavily on ambient temperature.",
    ),
)

CASES: tuple[EvalCase, ...] = (
    EvalCase("What is Helix?", "helix-overview", ("multi-tenant", "enterprise")),
    EvalCase(
        "How does the Helix assistant ground its answers?",
        "helix-rag",
        ("citations", "retrieval"),
    ),
    EvalCase(
        "How is tenant data isolated in Helix?",
        "helix-tenancy",
        ("org_id", "row-level security"),
    ),
    EvalCase(
        "What happens if a worker crashes mid-workflow?",
        "helix-workflows",
        ("resumable", "state machine"),
    ),
    EvalCase(
        "What ratio of coffee to water should I use for pour-over?", "coffee-brewing", ("1:16",)
    ),
    EvalCase(
        "How often should I feed my sourdough starter?", "sourdough-bread", ("feeding", "flour")
    ),
)
