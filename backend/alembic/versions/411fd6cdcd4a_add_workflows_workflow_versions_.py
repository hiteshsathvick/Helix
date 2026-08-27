"""add workflows workflow_versions workflow_runs and step_runs tables

Revision ID: 411fd6cdcd4a
Revises: ad74b6f802c0
Create Date: 2026-08-27 08:34:54.549956

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '411fd6cdcd4a'
down_revision: Union[str, None] = 'ad74b6f802c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('workflows',
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_by_user_id', sa.Uuid(), nullable=False),
    sa.Column('webhook_secret', sa.String(length=64), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_workflows_org_id'), 'workflows', ['org_id'], unique=False)

    op.create_table('workflow_versions',
    sa.Column('workflow_id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('graph', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_by_user_id', sa.Uuid(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.ForeignKeyConstraint(['workflow_id'], ['workflows.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workflow_id', 'version')
    )
    op.create_index(op.f('ix_workflow_versions_org_id'), 'workflow_versions', ['org_id'], unique=False)
    op.create_index(op.f('ix_workflow_versions_workflow_id'), 'workflow_versions', ['workflow_id'], unique=False)

    op.create_table('workflow_runs',
    sa.Column('workflow_id', sa.Uuid(), nullable=False),
    sa.Column('version_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('trigger', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('triggered_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('correlation_id', sa.Uuid(), nullable=False),
    sa.Column('cost', sa.Float(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.ForeignKeyConstraint(['triggered_by_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['version_id'], ['workflow_versions.id'], ),
    sa.ForeignKeyConstraint(['workflow_id'], ['workflows.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_workflow_runs_org_id'), 'workflow_runs', ['org_id'], unique=False)
    op.create_index(op.f('ix_workflow_runs_workflow_id'), 'workflow_runs', ['workflow_id'], unique=False)
    op.create_index(op.f('ix_workflow_runs_version_id'), 'workflow_runs', ['version_id'], unique=False)
    op.create_index(op.f('ix_workflow_runs_correlation_id'), 'workflow_runs', ['correlation_id'], unique=False)

    op.create_table('step_runs',
    sa.Column('workflow_run_id', sa.Uuid(), nullable=False),
    sa.Column('node_id', sa.String(length=100), nullable=False),
    sa.Column('node_type', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('input', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('output', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('org_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ),
    sa.ForeignKeyConstraint(['workflow_run_id'], ['workflow_runs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workflow_run_id', 'node_id')
    )
    op.create_index(op.f('ix_step_runs_org_id'), 'step_runs', ['org_id'], unique=False)
    op.create_index(op.f('ix_step_runs_workflow_run_id'), 'step_runs', ['workflow_run_id'], unique=False)

    for table in ("workflows", "workflow_versions", "workflow_runs", "step_runs"):
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
    for table in ("workflows", "workflow_versions", "workflow_runs", "step_runs"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")

    op.drop_index(op.f('ix_step_runs_workflow_run_id'), table_name='step_runs')
    op.drop_index(op.f('ix_step_runs_org_id'), table_name='step_runs')
    op.drop_table('step_runs')

    op.drop_index(op.f('ix_workflow_runs_correlation_id'), table_name='workflow_runs')
    op.drop_index(op.f('ix_workflow_runs_version_id'), table_name='workflow_runs')
    op.drop_index(op.f('ix_workflow_runs_workflow_id'), table_name='workflow_runs')
    op.drop_index(op.f('ix_workflow_runs_org_id'), table_name='workflow_runs')
    op.drop_table('workflow_runs')

    op.drop_index(op.f('ix_workflow_versions_workflow_id'), table_name='workflow_versions')
    op.drop_index(op.f('ix_workflow_versions_org_id'), table_name='workflow_versions')
    op.drop_table('workflow_versions')

    op.drop_index(op.f('ix_workflows_org_id'), table_name='workflows')
    op.drop_table('workflows')
