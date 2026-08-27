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

# Owner and Admin are identical today — SPEC.md §14 requires each
# permission to be listed explicitly rather than an implicit bypass, and
# nothing yet needs a permission reserved to Owner alone (that appears once
# billing exists in a later phase).
_FULL_PERMISSIONS = [
    PERMISSION_MEMBERS_READ,
    PERMISSION_MEMBERS_INVITE,
    PERMISSION_MEMBERS_MANAGE,
    PERMISSION_ROLES_MANAGE,
    PERMISSION_DOCUMENTS_READ,
    PERMISSION_DOCUMENTS_WRITE,
    PERMISSION_AI_CONFIG_MANAGE,
    PERMISSION_AGENTS_MANAGE,
    PERMISSION_AGENTS_RUN,
]
_MEMBER_PERMISSIONS = [
    PERMISSION_MEMBERS_READ,
    PERMISSION_DOCUMENTS_READ,
    PERMISSION_DOCUMENTS_WRITE,
    PERMISSION_AGENTS_MANAGE,
    PERMISSION_AGENTS_RUN,
]
_VIEWER_PERMISSIONS = [PERMISSION_MEMBERS_READ, PERMISSION_DOCUMENTS_READ]

SYSTEM_ROLES: dict[uuid.UUID, tuple[str, list[str]]] = {
    OWNER_ROLE_ID: ("Owner", _FULL_PERMISSIONS),
    ADMIN_ROLE_ID: ("Admin", _FULL_PERMISSIONS),
    MEMBER_ROLE_ID: ("Member", _MEMBER_PERMISSIONS),
    VIEWER_ROLE_ID: ("Viewer", _VIEWER_PERMISSIONS),
}
