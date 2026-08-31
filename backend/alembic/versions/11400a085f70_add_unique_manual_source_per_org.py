"""add_unique_manual_source_per_org

Revision ID: 11400a085f70
Revises: 1f2e3d4c5b6a
Create Date: 2026-08-31 06:00:51.433041

Phase 20: found via a real concurrent load test (infra/load/ingestion.js)
-- get_or_create_manual_source (documents/service.py) is a classic
check-then-insert race with no DB-level constraint backing it. Concurrent
first uploads to a brand-new org could each see no existing "manual" source
and each insert one, after which every later call raised
sqlalchemy.exc.MultipleResultsFound. This migration first soft-deletes any
duplicates already created by that race (keeping the earliest per org, and
consistent with this table's normal soft-delete convention rather than a
hard DELETE), then adds a partial unique index so the database itself
rejects a second one going forward. The application fix (catching the
resulting IntegrityError and falling back to a re-query) lives in the same
PR, documents/service.py::get_or_create_manual_source.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '11400a085f70'
down_revision: Union[str, None] = '1f2e3d4c5b6a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Soft-delete every duplicate "manual" source beyond the earliest one
    # per org -- the index below only needs to be unique among non-deleted
    # rows, so this is enough to let it be created.
    op.execute(
        """
        UPDATE sources
        SET deleted_at = now()
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY org_id ORDER BY created_at, id
                       ) AS rn
                FROM sources
                WHERE type = 'manual' AND deleted_at IS NULL
            ) ranked
            WHERE rn > 1
        )
        """
    )
    op.create_index(
        "ix_sources_org_id_manual_singleton",
        "sources",
        ["org_id"],
        unique=True,
        postgresql_where=sa.text("type = 'manual' AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_sources_org_id_manual_singleton", table_name="sources")
