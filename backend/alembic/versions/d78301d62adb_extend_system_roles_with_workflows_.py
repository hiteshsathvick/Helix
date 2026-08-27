"""extend system roles with workflows permissions

Revision ID: d78301d62adb
Revises: 411fd6cdcd4a
Create Date: 2026-08-27 08:34:57.021971

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd78301d62adb'
down_revision: Union[str, None] = '411fd6cdcd4a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OWNER_ROLE_ID = "00000000-0000-0000-0000-000000000001"
_ADMIN_ROLE_ID = "00000000-0000-0000-0000-000000000002"
_MEMBER_ROLE_ID = "00000000-0000-0000-0000-000000000003"


def upgrade() -> None:
    # Same tier as agents:manage/agents:run (3321f8a020f9) -- Owner/Admin/
    # Member can build and run workflows, Viewer stays read-only everywhere.
    op.execute(
        f"""
        UPDATE roles
        SET permissions = permissions || ARRAY['workflows:manage', 'workflows:run']
        WHERE id IN ('{_OWNER_ROLE_ID}', '{_ADMIN_ROLE_ID}', '{_MEMBER_ROLE_ID}')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET permissions = array_remove(array_remove(permissions, 'workflows:manage'), 'workflows:run')
        WHERE id IN (
            '00000000-0000-0000-0000-000000000001',
            '00000000-0000-0000-0000-000000000002',
            '00000000-0000-0000-0000-000000000003'
        )
        """
    )
