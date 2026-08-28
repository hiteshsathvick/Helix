import uuid

# Fixed IDs so the seeding migration and application code agree on identity
# without a lookup-by-name query. Never reuse these for a custom org role.
OWNER_ROLE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
ADMIN_ROLE_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
MEMBER_ROLE_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")
VIEWER_ROLE_ID = uuid.UUID("00000000-0000-0000-0000-000000000004")

PERMISSION_MEMBERS_READ = "members:read"
PERMISSION_MEMBERS_INVITE = "members:invite"
PERMISSION_MEMBERS_MANAGE = "members:manage"
PERMISSION_ROLES_MANAGE = "roles:manage"
PERMISSION_DOCUMENTS_READ = "documents:read"
PERMISSION_DOCUMENTS_WRITE = "documents:write"
PERMISSION_AI_CONFIG_MANAGE = "ai:manage"
PERMISSION_AGENTS_MANAGE = "agents:manage"
PERMISSION_AGENTS_RUN = "agents:run"
PERMISSION_WORKFLOWS_MANAGE = "workflows:manage"
PERMISSION_WORKFLOWS_RUN = "workflows:run"
PERMISSION_CONNECTORS_MANAGE = "connectors:manage"
# Billing (Phase 16) is the first permission reserved to Owner alone --
# subscription/payment changes are a materially different trust level than
# any org-configuration permission an Admin already holds, and Stripe
# itself treats "who can change the plan" as an owner-level decision.
PERMISSION_BILLING_MANAGE = "billing:manage"

# Owner and Admin were identical before billing existed (SPEC.md §14
# requires each permission to be listed explicitly rather than an implicit
# bypass) -- they now diverge by exactly PERMISSION_BILLING_MANAGE.
_SHARED_ADMIN_PERMISSIONS = [
    PERMISSION_MEMBERS_READ,
    PERMISSION_MEMBERS_INVITE,
    PERMISSION_MEMBERS_MANAGE,
    PERMISSION_ROLES_MANAGE,
    PERMISSION_DOCUMENTS_READ,
    PERMISSION_DOCUMENTS_WRITE,
    PERMISSION_AI_CONFIG_MANAGE,
    PERMISSION_AGENTS_MANAGE,
    PERMISSION_AGENTS_RUN,
    PERMISSION_WORKFLOWS_MANAGE,
    PERMISSION_WORKFLOWS_RUN,
    # Connectors, unlike agents/workflows, get one tier only (see Phase 14
    # plan §6): a sync touches OAuth credentials and external ingestion, a
    # materially different trust level than running someone else's agent
    # or workflow, and there's no legitimate "wants to sync but not
    # configure" persona -- Owner/Admin only, not Member.
    PERMISSION_CONNECTORS_MANAGE,
]
_FULL_PERMISSIONS = [*_SHARED_ADMIN_PERMISSIONS, PERMISSION_BILLING_MANAGE]
_MEMBER_PERMISSIONS = [
    PERMISSION_MEMBERS_READ,
    PERMISSION_DOCUMENTS_READ,
    PERMISSION_DOCUMENTS_WRITE,
    PERMISSION_AGENTS_MANAGE,
    PERMISSION_AGENTS_RUN,
    PERMISSION_WORKFLOWS_MANAGE,
    PERMISSION_WORKFLOWS_RUN,
]
_VIEWER_PERMISSIONS = [PERMISSION_MEMBERS_READ, PERMISSION_DOCUMENTS_READ]

SYSTEM_ROLES: dict[uuid.UUID, tuple[str, list[str]]] = {
    OWNER_ROLE_ID: ("Owner", _FULL_PERMISSIONS),
    ADMIN_ROLE_ID: ("Admin", _SHARED_ADMIN_PERMISSIONS),
    MEMBER_ROLE_ID: ("Member", _MEMBER_PERMISSIONS),
    VIEWER_ROLE_ID: ("Viewer", _VIEWER_PERMISSIONS),
}
