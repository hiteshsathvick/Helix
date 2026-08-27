"""add external_id to documents

Revision ID: f65102cbb37f
Revises: d78301d62adb
Create Date: 2026-08-27 09:51:34.700134

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f65102cbb37f'
down_revision: Union[str, None] = 'd78301d62adb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('external_id', sa.String(length=1024), nullable=True))
    op.create_index(
        'ix_documents_source_id_external_id', 'documents', ['source_id', 'external_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_documents_source_id_external_id', table_name='documents')
    op.drop_column('documents', 'external_id')
