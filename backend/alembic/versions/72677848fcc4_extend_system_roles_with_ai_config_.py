"""extend system roles with ai config permission

Revision ID: 72677848fcc4
Revises: dc57409e6d8e
Create Date: 2026-08-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '72677848fcc4'
down_revision: Union[str, None] = 'dc57409e6d8e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OWNER_ROLE_ID = "00000000-0000-0000-0000-000000000001"
_ADMIN_ROLE_ID = "00000000-0000-0000-0000-000000000002"


def upgrade() -> None:
    # Owner/Admin only (SPEC.md §17 "model config per org" is an org-wide
    # setting, not a per-member one) — Member/Viewer are untouched.
    op.execute(
        f"""
        UPDATE roles
        SET permissions = permissions || ARRAY['ai:manage']
        WHERE id IN ('{_OWNER_ROLE_ID}', '{_ADMIN_ROLE_ID}')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET permissions = array_remove(permissions, 'ai:manage')
        WHERE id IN (
            '00000000-0000-0000-0000-000000000001',
            '00000000-0000-0000-0000-000000000002'
        )
        """
    )
