"""Add created_at to fhir_bundles.

Revision ID: fhir_bundles_created_at_001
Revises: proposal_execution_failed_001
Create Date: 2026-02-24

The initial migration created fhir_bundles without a created_at column.
Every INSERT from the FHIR Builder Worker was failing because the ORM
model defines created_at matching the Base timestamp pattern.
"""

import sqlalchemy as sa
from alembic import op

revision = "fhir_bundles_created_at_001"
down_revision = "proposal_execution_failed_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "fhir_bundles",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_column("fhir_bundles", "created_at")
