"""extend owner and admin roles with api_keys and webhooks permissions

Revision ID: 1f2e3d4c5b6a
Revises: 0a508022767b
Create Date: 2026-08-28 09:15:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = '1f2e3d4c5b6a'
down_revision: Union[str, None] = '0a508022767b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OWNER_ROLE_ID = "00000000-0000-0000-0000-000000000001"
_ADMIN_ROLE_ID = "00000000-0000-0000-0000-000000000002"


def upgrade() -> None:
    # Owner + Admin, same tier as connectors:manage -- external credentials
    # (API keys) and integrations (webhooks) are a materially different
    # trust level than the Member tier's day-to-day agents:run/workflows:run.
    op.execute(
        f"""
        UPDATE roles
        SET permissions = permissions || ARRAY['api_keys:manage', 'webhooks:manage']
        WHERE id IN ('{_OWNER_ROLE_ID}', '{_ADMIN_ROLE_ID}')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET permissions = array_remove(array_remove(permissions, 'api_keys:manage'), 'webhooks:manage')
        WHERE id IN (
            '00000000-0000-0000-0000-000000000001',
            '00000000-0000-0000-0000-000000000002'
        )
        """
    )
