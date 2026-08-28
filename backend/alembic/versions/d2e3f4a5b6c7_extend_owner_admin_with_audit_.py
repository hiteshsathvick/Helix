"""extend owner and admin roles with audit and analytics permissions

Revision ID: d2e3f4a5b6c7
Revises: c649ee198597
Create Date: 2026-08-28 07:40:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, None] = 'c649ee198597'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OWNER_ROLE_ID = "00000000-0000-0000-0000-000000000001"
_ADMIN_ROLE_ID = "00000000-0000-0000-0000-000000000002"


def upgrade() -> None:
    # Owner + Admin, same tier as connectors:manage -- unlike billing:manage
    # (Phase 16's Owner-only exception), seeing the audit trail and usage
    # analytics isn't a financial/payment-level decision.
    op.execute(
        f"""
        UPDATE roles
        SET permissions = permissions || ARRAY['audit:read', 'analytics:read']
        WHERE id IN ('{_OWNER_ROLE_ID}', '{_ADMIN_ROLE_ID}')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET permissions = array_remove(array_remove(permissions, 'audit:read'), 'analytics:read')
        WHERE id IN (
            '00000000-0000-0000-0000-000000000001',
            '00000000-0000-0000-0000-000000000002'
        )
        """
    )
