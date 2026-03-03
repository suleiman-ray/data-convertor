"""Add EXECUTION_FAILED value to proposalstatus enum.

Revision ID: proposal_execution_failed_001
Revises: arch_review_001
Create Date: 2026-02-23

Notes:
  ALTER TYPE ... ADD VALUE requires PostgreSQL 9.1+.
  In PostgreSQL 12+ it is allowed inside a transaction block when the new
  value has not yet been used. On older PostgreSQL the migration must run
  outside a transaction; add transactional = False to env.py if needed.
"""

import sqlalchemy as sa
from alembic import op

revision = "proposal_execution_failed_001"
down_revision = "arch_review_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text("ALTER TYPE proposalstatus ADD VALUE IF NOT EXISTS 'EXECUTION_FAILED'")
    )


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; a full type replacement
    # would be needed. This downgrade is a no-op to avoid data loss.
    pass
