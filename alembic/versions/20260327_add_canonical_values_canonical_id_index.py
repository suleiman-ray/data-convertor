"""Add index on canonical_values.canonical_id for join/filter performance.

Revision ID: canonical_values_canonical_id_idx_001
Revises: structured_text_format_001
"""

import sqlalchemy as sa
from alembic import op

revision = "canonical_values_canonical_id_idx_001"
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
