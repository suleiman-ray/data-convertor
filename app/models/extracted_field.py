import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, enum_col
from app.models.enums import FieldStatus


class ExtractedField(Base):
    __tablename__ = "extracted_fields"

    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("intake_submissions.submission_id"), nullable=False
    )
    raw_label: Mapped[str] = mapped_column(Text, nullable=False)
    raw_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_path: Mapped[str] = mapped_column(Text, nullable=False)
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    stable_field_id: Mapped[str] = mapped_column(String, nullable=False)
    extractor_version: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[FieldStatus] = mapped_column(
        enum_col(FieldStatus), nullable=False, default=FieldStatus.OK
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_extracted_fields_submission", "submission_id"),
        Index("ix_extracted_fields_stable_field", "stable_field_id"),
    )
