"""add api_keys webhooks webhook_deliveries tables

Revision ID: 0a508022767b
Revises: d2e3f4a5b6c7
Create Date: 2026-08-28 09:06:03.343421

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0a508022767b'
down_revision: Union[str, None] = 'd2e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # api_keys deliberately carries no RLS policy -- it's resolved by hash
    # before any org context is known, the same bearer-token pattern
    # orgs.Invitation and auth.RefreshToken already use. See
    # api/models.py::ApiKey's docstring.
    op.create_table('api_keys',
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('prefix', sa.String(length=20), nullable=False),
    sa.Column('hash', sa.String(length=64), nullable=False),
    sa.Column('scopes', sa.ARRAY(sa.String()), nullable=False),
    sa.Column('created_by_user_id', sa.Uuid(), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_api_keys_hash'), 'api_keys', ['hash'], unique=True)
    op.create_index(op.f('ix_api_keys_org_id'), 'api_keys', ['org_id'], unique=False)
    op.create_index(op.f('ix_api_keys_prefix'), 'api_keys', ['prefix'], unique=False)

    op.create_table('webhooks',
    sa.Column('url', sa.String(length=2048), nullable=False),
    sa.Column('secret', sa.String(length=255), nullable=False),
    sa.Column('events', sa.ARRAY(sa.String()), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_by_user_id', sa.Uuid(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_webhooks_org_id'), 'webhooks', ['org_id'], unique=False)

    op.create_table('webhook_deliveries',
    sa.Column('webhook_id', sa.Uuid(), nullable=False),
    sa.Column('event_id', sa.Uuid(), nullable=False),
    sa.Column('event_type', sa.String(length=100), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('response_status', sa.Integer(), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['event_id'], ['domain_events.id'], ),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.ForeignKeyConstraint(['webhook_id'], ['webhooks.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_webhook_deliveries_org_id'), 'webhook_deliveries', ['org_id'], unique=False)
    op.create_index(op.f('ix_webhook_deliveries_webhook_id'), 'webhook_deliveries', ['webhook_id'], unique=False)

    for table in ("webhooks", "webhook_deliveries"):
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
    for table in ("webhooks", "webhook_deliveries"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")

    op.drop_index(op.f('ix_webhook_deliveries_webhook_id'), table_name='webhook_deliveries')
    op.drop_index(op.f('ix_webhook_deliveries_org_id'), table_name='webhook_deliveries')
    op.drop_table('webhook_deliveries')

    op.drop_index(op.f('ix_webhooks_org_id'), table_name='webhooks')
    op.drop_table('webhooks')

    op.drop_index(op.f('ix_api_keys_prefix'), table_name='api_keys')
    op.drop_index(op.f('ix_api_keys_org_id'), table_name='api_keys')
    op.drop_index(op.f('ix_api_keys_hash'), table_name='api_keys')
    op.drop_table('api_keys')
