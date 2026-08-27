"""add domain events table

Revision ID: ad74b6f802c0
Revises: 3321f8a020f9
Create Date: 2026-08-27 08:34:51.999039

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'ad74b6f802c0'
down_revision: Union[str, None] = '3321f8a020f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('domain_events',
    sa.Column('type', sa.String(length=100), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('correlation_id', sa.Uuid(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_domain_events_org_id'), 'domain_events', ['org_id'], unique=False)
    op.create_index(op.f('ix_domain_events_correlation_id'), 'domain_events', ['correlation_id'], unique=False)

    op.execute("ALTER TABLE domain_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE domain_events FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON domain_events
        USING (org_id = current_setting('app.current_org', true)::uuid)
        WITH CHECK (org_id = current_setting('app.current_org', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON domain_events")
    op.drop_index(op.f('ix_domain_events_correlation_id'), table_name='domain_events')
    op.drop_index(op.f('ix_domain_events_org_id'), table_name='domain_events')
    op.drop_table('domain_events')
