"""extend system roles with agents permissions

Revision ID: 3321f8a020f9
Revises: 1689b2c7a2fe
Create Date: 2026-08-27 09:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '3321f8a020f9'
down_revision: Union[str, None] = '1689b2c7a2fe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OWNER_ROLE_ID = "00000000-0000-0000-0000-000000000001"
_ADMIN_ROLE_ID = "00000000-0000-0000-0000-000000000002"
_MEMBER_ROLE_ID = "00000000-0000-0000-0000-000000000003"


def upgrade() -> None:
    # Same tier as documents:write (c87db09244a0) — Owner/Admin/Member can
    # build and run agents, Viewer stays read-only everywhere.
    op.execute(
        f"""
        UPDATE roles
        SET permissions = permissions || ARRAY['agents:manage', 'agents:run']
        WHERE id IN ('{_OWNER_ROLE_ID}', '{_ADMIN_ROLE_ID}', '{_MEMBER_ROLE_ID}')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET permissions = array_remove(array_remove(permissions, 'agents:manage'), 'agents:run')
        WHERE id IN (
            '00000000-0000-0000-0000-000000000001',
            '00000000-0000-0000-0000-000000000002',
            '00000000-0000-0000-0000-000000000003'
        )
        """
    )
