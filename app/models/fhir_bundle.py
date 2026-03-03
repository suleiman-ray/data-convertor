import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, enum_col
from app.models.enums import BundleStatus, DeliveryStatus


class FhirBundle(Base):
    __tablename__ = "fhir_bundles"

    bundle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("intake_submissions.submission_id"), nullable=False, index=True
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fhir_templates.template_id"), nullable=False
    )
    # Bundle stored in S3; not inline to avoid DB bloat
    bundle_uri: Mapped[str] = mapped_column(Text, nullable=False)
    bundle_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    fhir_version: Mapped[str] = mapped_column(String, nullable=False, default="R4")
    status: Mapped[BundleStatus] = mapped_column(
        enum_col(BundleStatus), nullable=False, default=BundleStatus.BUILDING
    )
    validation_errors: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    destination: Mapped[str | None] = mapped_column(String, nullable=True)
    delivery_status: Mapped[DeliveryStatus] = mapped_column(
        enum_col(DeliveryStatus), nullable=False, default=DeliveryStatus.PENDING
    )
    delivery_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_delivery_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    built_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
