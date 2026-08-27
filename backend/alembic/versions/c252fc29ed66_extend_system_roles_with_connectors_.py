"""extend system roles with connectors permissions

Revision ID: c252fc29ed66
Revises: f3beea804a1c
Create Date: 2026-08-27 09:51:40.200678

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c252fc29ed66'
down_revision: Union[str, None] = 'f3beea804a1c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OWNER_ROLE_ID = "00000000-0000-0000-0000-000000000001"
_ADMIN_ROLE_ID = "00000000-0000-0000-0000-000000000002"


def upgrade() -> None:
    # Owner/Admin only, unlike agents/workflows (which also grant Member) --
    # a connector sync touches OAuth credentials and external ingestion, a
    # materially different trust level than running someone else's agent
    # or workflow.
    op.execute(
        f"""
        UPDATE roles
        SET permissions = permissions || ARRAY['connectors:manage']
        WHERE id IN ('{_OWNER_ROLE_ID}', '{_ADMIN_ROLE_ID}')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET permissions = array_remove(permissions, 'connectors:manage')
        WHERE id IN (
            '00000000-0000-0000-0000-000000000001',
            '00000000-0000-0000-0000-000000000002'
        )
        """
    )
