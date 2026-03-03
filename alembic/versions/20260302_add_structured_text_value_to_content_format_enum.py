"""Add STRUCTURED_TEXT value to contentformat enum.

Revision ID: structured_text_format_001
Revises: fhir_bundles_created_at_001
Create Date: 2026-03-02

The content_format column on intake_submissions is backed by the PostgreSQL
native enum type 'contentformat'.  Adding a new member requires ALTER TYPE;
Alembic's server_default/add_column path cannot extend native enums directly.

IF NOT EXISTS means this is safe to re-run on databases where the value was
already added manually (e.g. during development hotfixes).
"""

import sqlalchemy as sa
from alembic import op

revision = "structured_text_format_001"
down_revision = "fhir_bundles_created_at_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text("ALTER TYPE contentformat ADD VALUE IF NOT EXISTS 'STRUCTURED_TEXT'")
    )


def downgrade() -> None:
    # PostgreSQL does not support removing values from an enum type without
    # recreating it.  A full downgrade would require a schema rebuild and is
    # out of scope here.  Deployments that need to roll back should use a
    # point-in-time DB restore.
    pass
