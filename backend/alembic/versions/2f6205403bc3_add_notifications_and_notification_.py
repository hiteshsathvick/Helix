"""add notifications and notification_prefs tables

Revision ID: 2f6205403bc3
Revises: c252fc29ed66
Create Date: 2026-08-27 10:47:05.705872

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '2f6205403bc3'
down_revision: Union[str, None] = 'c252fc29ed66'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('notifications',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('channel', sa.String(length=20), nullable=False),
    sa.Column('event_type', sa.String(length=100), nullable=False),
    sa.Column('template', sa.String(length=100), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('subject', sa.String(length=500), nullable=True),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_notifications_org_id'), 'notifications', ['org_id'], unique=False)
    op.create_index(op.f('ix_notifications_user_id'), 'notifications', ['user_id'], unique=False)
    op.create_index(
        'ix_notifications_org_user_created', 'notifications',
        ['org_id', 'user_id', 'created_at', 'id'], unique=False
    )

    op.create_table('notification_prefs',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('channel', sa.String(length=20), nullable=False),
    sa.Column('event', sa.String(length=100), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('frequency', sa.String(length=20), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'user_id', 'channel', 'event')
    )
    op.create_index(op.f('ix_notification_prefs_org_id'), 'notification_prefs', ['org_id'], unique=False)
    op.create_index(op.f('ix_notification_prefs_user_id'), 'notification_prefs', ['user_id'], unique=False)

    for table in ("notifications", "notification_prefs"):
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
    for table in ("notifications", "notification_prefs"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")

    op.drop_index(op.f('ix_notification_prefs_user_id'), table_name='notification_prefs')
    op.drop_index(op.f('ix_notification_prefs_org_id'), table_name='notification_prefs')
    op.drop_table('notification_prefs')

    op.drop_index('ix_notifications_org_user_created', table_name='notifications')
    op.drop_index(op.f('ix_notifications_user_id'), table_name='notifications')
    op.drop_index(op.f('ix_notifications_org_id'), table_name='notifications')
    op.drop_table('notifications')
