import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, enum_col
from app.models.enums import UnmappedStatus


class UnmappedField(Base):
    __tablename__ = "unmapped_fields"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("intake_submissions.submission_id"), nullable=False
    )
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extracted_fields.instance_id"), nullable=False
    )
    intake_type_id: Mapped[str] = mapped_column(String, nullable=False)
    intake_type_version: Mapped[str] = mapped_column(String, nullable=False)
    stable_field_id: Mapped[str] = mapped_column(String, nullable=False)
    raw_label: Mapped[str] = mapped_column(Text, nullable=False)
    raw_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[UnmappedStatus] = mapped_column(
        enum_col(UnmappedStatus), nullable=False, default=UnmappedStatus.PENDING_REVIEW
    )
    reviewed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
