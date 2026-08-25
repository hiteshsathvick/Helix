"""extend memberships RLS policy to allow self-row visibility across orgs

Revision ID: 4a6ed578fb4f
Revises: b6e0d623e32c
Create Date: 2026-08-25 10:02:46.969418

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '4a6ed578fb4f'
down_revision: Union[str, None] = 'b6e0d623e32c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Phase 2's policy only granted visibility into the currently-scoped
    # org (app.current_org). Phase 4 needs "list the orgs I belong to" — a
    # self-service query that legitimately spans every org a user is in —
    # so this adds an OR branch for the caller's own rows regardless of
    # which org (if any) the session is scoped to.
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON memberships")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON memberships
        USING (
            org_id = current_setting('app.current_org', true)::uuid
            OR user_id = current_setting('app.current_user_id', true)::uuid
        )
        WITH CHECK (
            org_id = current_setting('app.current_org', true)::uuid
            OR user_id = current_setting('app.current_user_id', true)::uuid
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON memberships")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON memberships
        USING (org_id = current_setting('app.current_org', true)::uuid)
        WITH CHECK (org_id = current_setting('app.current_org', true)::uuid)
        """
    )
