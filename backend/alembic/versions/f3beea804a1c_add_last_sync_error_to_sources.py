"""add last_sync_error to sources

Revision ID: f3beea804a1c
Revises: f65102cbb37f
Create Date: 2026-08-27 09:51:37.417926

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f3beea804a1c'
down_revision: Union[str, None] = 'f65102cbb37f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sources', sa.Column('last_sync_error', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('sources', 'last_sync_error')
