"""add subscriptions and usage_events tables

Revision ID: f70f5dc0533e
Revises: 2f6205403bc3
Create Date: 2026-08-27 13:04:07.197791

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f70f5dc0533e'
down_revision: Union[str, None] = '2f6205403bc3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('subscriptions',
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.Column('stripe_customer_id', sa.String(length=255), nullable=True),
    sa.Column('stripe_subscription_id', sa.String(length=255), nullable=True),
    sa.Column('plan', sa.String(length=50), nullable=False),
    sa.Column('seats', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_subscriptions_org_id'), 'subscriptions', ['org_id'], unique=True)

    op.create_table('usage_events',
    sa.Column('kind', sa.String(length=50), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('cost', sa.Numeric(precision=12, scale=6), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_usage_events_org_id'), 'usage_events', ['org_id'], unique=False)
    op.create_index(
        'ix_usage_events_org_occurred', 'usage_events', ['org_id', 'occurred_at'], unique=False
    )

    for table in ("subscriptions", "usage_events"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (org_id = current_setting('app.current_org', true)::uuid)
            WITH CHECK (org_id = current_setting('app.current_org', true)::uuid)
            """
        )


def downgrade() -> None:
    for table in ("subscriptions", "usage_events"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")

    op.drop_index('ix_usage_events_org_occurred', table_name='usage_events')
    op.drop_index(op.f('ix_usage_events_org_id'), table_name='usage_events')
    op.drop_table('usage_events')

    op.drop_index(op.f('ix_subscriptions_org_id'), table_name='subscriptions')
    op.drop_table('subscriptions')
