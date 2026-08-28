"""extend owner role with billing permission

Revision ID: a1b2c3d4e5f6
Revises: f70f5dc0533e
Create Date: 2026-08-27 13:10:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f70f5dc0533e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OWNER_ROLE_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    # Owner only, unlike every prior per-phase permission extension (which
    # all went to Owner + Admin) -- billing/subscription changes are the
    # first permission this app reserves to Owner alone (see
    # system_roles.py's long-standing comment anticipating exactly this).
    op.execute(
        f"""
        UPDATE roles
        SET permissions = permissions || ARRAY['billing:manage']
        WHERE id = '{_OWNER_ROLE_ID}'
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        UPDATE roles
        SET permissions = array_remove(permissions, 'billing:manage')
        WHERE id = '{_OWNER_ROLE_ID}'
        """
    )
