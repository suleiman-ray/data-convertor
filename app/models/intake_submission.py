import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, enum_col
from app.models.enums import ContentFormat, SubmissionStatus


class IntakeSubmission(Base):
    __tablename__ = "intake_submissions"

    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    idempotency_key: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    patient_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    intake_type_id: Mapped[str] = mapped_column(String, nullable=False)
    intake_type_version: Mapped[str] = mapped_column(String, nullable=False)
    content_format: Mapped[ContentFormat] = mapped_column(enum_col(ContentFormat), nullable=False)
    raw_uri: Mapped[str] = mapped_column(Text, nullable=False)
    raw_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    submitted_by: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[SubmissionStatus] = mapped_column(
        enum_col(SubmissionStatus), nullable=False, default=SubmissionStatus.RECEIVED
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
