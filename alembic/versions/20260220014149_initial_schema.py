"""initial_schema

Revision ID: 20260220014149
Revises:
Create Date: 2026-02-20 01:41:49

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from alembic import op

revision: str = "20260220014149"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── canonical_concepts ────────────────────────────────────────────────────
    op.create_table(
        "canonical_concepts",
        sa.Column("canonical_id", sa.String(), primary_key=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "value_type",
            sa.Enum("quantity", "boolean", "coded", "string", "date", name="valuetype"),
            nullable=False,
        ),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("value_domain", JSONB(), nullable=True),
        sa.Column("fhir_data_type", sa.String(), nullable=False),
        sa.Column("code_system", sa.String(), nullable=True),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "deprecated", name="conceptstatus"),
            nullable=False,
            server_default="active",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ── field_to_canonical ────────────────────────────────────────────────────
    op.create_table(
        "field_to_canonical",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("intake_type_id", sa.String(), nullable=False),
        sa.Column("intake_type_version", sa.String(), nullable=False),
        sa.Column("stable_field_id", sa.String(), nullable=False),
        sa.Column("canonical_id", sa.String(), sa.ForeignKey("canonical_concepts.canonical_id"), nullable=False),
        sa.Column(
            "mapping_method",
            sa.Enum("human", "agent", name="mappingmethod"),
            nullable=False,
        ),
        sa.Column("approved_by", sa.String(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_field_to_canonical_lookup", "field_to_canonical",
                    ["intake_type_id", "intake_type_version", "stable_field_id"])
    op.create_index(
        "ux_field_to_canonical_active",
        "field_to_canonical",
        ["intake_type_id", "intake_type_version", "stable_field_id"],
        unique=True,
        postgresql_where=sa.text("active = true"),
    )

    # ── intake_submissions ────────────────────────────────────────────────────
    op.create_table(
        "intake_submissions",
        sa.Column("submission_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("idempotency_key", sa.String(), unique=True, nullable=False),
        sa.Column("patient_id", sa.String(), nullable=False),
        sa.Column("intake_type_id", sa.String(), nullable=False),
        sa.Column("intake_type_version", sa.String(), nullable=False),
        sa.Column(
            "content_format",
            sa.Enum("JSON_FORM", "PDF_DIGITAL", "PDF_SCANNED", "HL7", name="contentformat"),
            nullable=False,
        ),
        sa.Column("raw_uri", sa.Text(), nullable=False),
        sa.Column("raw_sha256", sa.String(64), nullable=False),
        sa.Column("submitted_by", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("RECEIVED", "PROCESSING", "NEEDS_REVIEW", "BUILDING_FHIR", "COMPLETE", "FAILED",
                    name="submissionstatus"),
            nullable=False,
            server_default="RECEIVED",
        ),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_intake_submissions_patient", "intake_submissions", ["patient_id"])

    # ── extracted_fields ──────────────────────────────────────────────────────
    op.create_table(
        "extracted_fields",
        sa.Column("instance_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("submission_id", UUID(as_uuid=True), sa.ForeignKey("intake_submissions.submission_id"), nullable=False),
        sa.Column("raw_label", sa.Text(), nullable=False),
        sa.Column("raw_value", sa.Text(), nullable=True),
        sa.Column("section_path", sa.Text(), nullable=False),
        sa.Column("provenance", JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("stable_field_id", sa.String(), nullable=False),
        sa.Column("extractor_version", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("OK", "FAILED", name="fieldstatus"),
            nullable=False,
            server_default="OK",
        ),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_extracted_fields_submission", "extracted_fields", ["submission_id"])
    op.create_index("ix_extracted_fields_stable_field", "extracted_fields", ["stable_field_id"])

    # ── unmapped_fields ───────────────────────────────────────────────────────
    op.create_table(
        "unmapped_fields",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("submission_id", UUID(as_uuid=True), sa.ForeignKey("intake_submissions.submission_id"), nullable=False),
        sa.Column("instance_id", UUID(as_uuid=True), sa.ForeignKey("extracted_fields.instance_id"), nullable=False),
        sa.Column("intake_type_id", sa.String(), nullable=False),
        sa.Column("intake_type_version", sa.String(), nullable=False),
        sa.Column("stable_field_id", sa.String(), nullable=False),
        sa.Column("raw_label", sa.Text(), nullable=False),
        sa.Column("raw_value", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("PENDING_REVIEW", "MAPPING_CREATED", "IGNORED", name="unmappedstatus"),
            nullable=False,
            server_default="PENDING_REVIEW",
        ),
        sa.Column("reviewed_by", sa.String(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ── canonical_values ──────────────────────────────────────────────────────
    op.create_table(
        "canonical_values",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("submission_id", UUID(as_uuid=True), sa.ForeignKey("intake_submissions.submission_id"), nullable=False),
        sa.Column("patient_id", sa.String(), nullable=False),
        sa.Column("instance_id", UUID(as_uuid=True), sa.ForeignKey("extracted_fields.instance_id"), nullable=False),
        sa.Column("canonical_id", sa.String(), sa.ForeignKey("canonical_concepts.canonical_id"), nullable=False),
        sa.Column("value_raw", sa.Text(), nullable=False),
        sa.Column("value_normalized", JSONB(), nullable=False),
        sa.Column(
            "state",
            sa.Enum("DRAFT", "CONFIRMED", "LOCKED", "NORMALIZATION_FAILED", name="canonicalvaluestate"),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("normalizer_version", sa.String(), nullable=False),
        sa.Column("confirmed_by", sa.String(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_canonical_values_submission", "canonical_values", ["submission_id"])
    op.create_index("ix_canonical_values_patient", "canonical_values", ["patient_id"])

    # ── fhir_templates ────────────────────────────────────────────────────────
    op.create_table(
        "fhir_templates",
        sa.Column("template_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("intake_type_id", sa.String(), nullable=False),
        sa.Column("intake_type_version", sa.String(), nullable=False),
        sa.Column("fhir_version", sa.String(), nullable=False, server_default="R4"),
        sa.Column("template_json", JSONB(), nullable=False),
        sa.Column("placeholder_schema", JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("template_version", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("DRAFT", "APPROVED", "DEPRECATED", name="templatestatus"),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column("approved_by", sa.String(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ── fhir_bundles ──────────────────────────────────────────────────────────
    op.create_table(
        "fhir_bundles",
        sa.Column("bundle_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("submission_id", UUID(as_uuid=True), sa.ForeignKey("intake_submissions.submission_id"), nullable=False),
        sa.Column("template_id", UUID(as_uuid=True), sa.ForeignKey("fhir_templates.template_id"), nullable=False),
        sa.Column("bundle_uri", sa.Text(), nullable=False),
        sa.Column("bundle_sha256", sa.String(64), nullable=False),
        sa.Column("fhir_version", sa.String(), nullable=False, server_default="R4"),
        sa.Column(
            "status",
            sa.Enum("BUILDING", "BUILT", "VALIDATION_FAILED", "SENT", "DELIVERY_FAILED", "ACKNOWLEDGED",
                    name="bundlestatus"),
            nullable=False,
            server_default="BUILDING",
        ),
        sa.Column("validation_errors", JSONB(), nullable=True),
        sa.Column("destination", sa.String(), nullable=True),
        sa.Column(
            "delivery_status",
            sa.Enum("PENDING", "SENT", "FAILED", "ACKNOWLEDGED", name="deliverystatus"),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("delivery_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_delivery_error", sa.Text(), nullable=True),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_fhir_bundles_submission", "fhir_bundles", ["submission_id"])

    # ── mapping_proposals ─────────────────────────────────────────────────────
    op.create_table(
        "mapping_proposals",
        sa.Column("proposal_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("proposed_by", sa.String(), nullable=False),
        sa.Column(
            "proposal_type",
            sa.Enum("canonical_concept", "field_mapping", "fhir_template", name="proposaltype"),
            nullable=False,
        ),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("PENDING", "APPROVED", "REJECTED", "SUPERSEDED", name="proposalstatus"),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("clinical_approved_by", sa.String(), nullable=True),
        sa.Column("clinical_approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("product_approved_by", sa.String(), nullable=True),
        sa.Column("product_approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ── audit_log ─────────────────────────────────────────────────────────────
    op.create_table(
        "audit_log",
        sa.Column("log_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("before_state", JSONB(), nullable=True),
        sa.Column("after_state", JSONB(), nullable=True),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_audit_log_entity", "audit_log", ["entity_type", "entity_id"])
    op.create_index("ix_audit_log_actor", "audit_log", ["actor_id"])
    op.create_index("ix_audit_log_occurred", "audit_log", ["occurred_at"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("mapping_proposals")
    op.drop_table("fhir_bundles")
    op.drop_table("fhir_templates")
    op.drop_table("canonical_values")
    op.drop_table("unmapped_fields")
    op.drop_table("extracted_fields")
    op.drop_table("intake_submissions")
    op.drop_table("field_to_canonical")
    op.drop_table("canonical_concepts")

    for enum in [
        "valuetype", "conceptstatus", "mappingmethod", "contentformat",
        "submissionstatus", "fieldstatus", "unmappedstatus", "canonicalvaluestate",
        "templatestatus", "bundlestatus", "deliverystatus", "proposaltype", "proposalstatus",
    ]:
        sa.Enum(name=enum).drop(op.get_bind(), checkfirst=True)
