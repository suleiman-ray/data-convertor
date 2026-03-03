import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, enum_col
from app.models.enums import TemplateStatus


class FhirTemplate(Base):
    __tablename__ = "fhir_templates"

    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    intake_type_id: Mapped[str] = mapped_column(String, nullable=False)
    intake_type_version: Mapped[str] = mapped_column(String, nullable=False)
    fhir_version: Mapped[str] = mapped_column(String, nullable=False, default="R4")
    template_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # Maps placeholder canonical_id → {required: bool, fhir_path: str}
    placeholder_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    template_version: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[TemplateStatus] = mapped_column(
        enum_col(TemplateStatus), nullable=False, default=TemplateStatus.DRAFT
    )
    approved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
