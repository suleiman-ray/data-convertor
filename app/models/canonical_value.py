import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, enum_col
from app.models.enums import CanonicalValueState


class CanonicalValue(Base):
    __tablename__ = "canonical_values"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("intake_submissions.submission_id"), nullable=False
    )
    patient_id: Mapped[str] = mapped_column(String, nullable=False)
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extracted_fields.instance_id"), nullable=False
    )
    canonical_id: Mapped[str] = mapped_column(
        String, ForeignKey("canonical_concepts.canonical_id"), nullable=False
    )
    value_raw: Mapped[str] = mapped_column(Text, nullable=False)
    value_normalized: Mapped[dict] = mapped_column(JSONB, nullable=False)
    state: Mapped[CanonicalValueState] = mapped_column(
        enum_col(CanonicalValueState), nullable=False, default=CanonicalValueState.DRAFT
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalizer_version: Mapped[str] = mapped_column(String, nullable=False)
    confirmed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_canonical_values_submission", "submission_id"),
        Index("ix_canonical_values_patient", "patient_id"),
        Index("ix_canonical_values_canonical_id", "canonical_id"),
    )
