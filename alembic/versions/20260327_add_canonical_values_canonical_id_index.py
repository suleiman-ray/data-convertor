"""Add index on canonical_values.canonical_id for join/filter performance.

Revision ID: cv_canonical_id_idx_01 (max 32 chars for alembic_version)
Revises: structured_text_format_001
"""

import sqlalchemy as sa
from alembic import op

revision = "cv_canonical_id_idx_01"
down_revision = "structured_text_format_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_canonical_values_canonical_id",
        "canonical_values",
        ["canonical_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_canonical_values_canonical_id", table_name="canonical_values")
