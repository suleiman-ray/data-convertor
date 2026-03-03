"""Add partial unique index enforcing one APPROVED template per intake type; add updated_at to fhir_bundles.

Revision ID: arch_review_001
Revises: 20260220014149
Create Date: 2026-02-22
"""
from alembic import op
import sqlalchemy as sa

revision = "arch_review_001"
down_revision = "20260220014149"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Partial unique index: at most one APPROVED template per intake type ──
    # Mirrors the application-level guard in approve_template().
    op.create_index(
        "ux_fhir_templates_approved_per_intake",
        "fhir_templates",
        ["intake_type_id", "intake_type_version"],
        unique=True,
        postgresql_where="status = 'APPROVED'",
    )

    # ── 2. fhir_bundles.updated_at — tracks status transition timestamps ────────
    op.add_column(
        "fhir_bundles",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_index("ux_fhir_templates_approved_per_intake", table_name="fhir_templates")
    op.drop_column("fhir_bundles", "updated_at")
