"""extend system roles with documents permissions

Revision ID: c87db09244a0
Revises: a79516612dbf
Create Date: 2026-08-25 10:59:42.341658

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c87db09244a0'
down_revision: Union[str, None] = 'a79516612dbf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OWNER_ROLE_ID = "00000000-0000-0000-0000-000000000001"
_ADMIN_ROLE_ID = "00000000-0000-0000-0000-000000000002"
_MEMBER_ROLE_ID = "00000000-0000-0000-0000-000000000003"
_VIEWER_ROLE_ID = "00000000-0000-0000-0000-000000000004"


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE roles
        SET permissions = permissions || ARRAY['documents:read', 'documents:write']
        WHERE id IN ('{_OWNER_ROLE_ID}', '{_ADMIN_ROLE_ID}', '{_MEMBER_ROLE_ID}')
        """
    )
    op.execute(
        f"""
        UPDATE roles
        SET permissions = permissions || ARRAY['documents:read']
        WHERE id = '{_VIEWER_ROLE_ID}'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET permissions = array_remove(array_remove(permissions, 'documents:read'), 'documents:write')
        WHERE id IN (
            '00000000-0000-0000-0000-000000000001',
            '00000000-0000-0000-0000-000000000002',
            '00000000-0000-0000-0000-000000000003',
            '00000000-0000-0000-0000-000000000004'
        )
        """
    )
