from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
import uuid

from app.models.base import Base, enum_col
from app.models.enums import MappingMethod


class FieldToCanonical(Base):
    __tablename__ = "field_to_canonical"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    intake_type_id: Mapped[str] = mapped_column(String, nullable=False)
    intake_type_version: Mapped[str] = mapped_column(String, nullable=False)
    stable_field_id: Mapped[str] = mapped_column(String, nullable=False)
    canonical_id: Mapped[str] = mapped_column(
        String, ForeignKey("canonical_concepts.canonical_id"), nullable=False
    )
    mapping_method: Mapped[MappingMethod] = mapped_column(enum_col(MappingMethod), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "ux_field_to_canonical_active",
            "intake_type_id",
            "intake_type_version",
            "stable_field_id",
            unique=True,
            postgresql_where="active = true",
        ),
        Index("ix_field_to_canonical_lookup", "intake_type_id", "intake_type_version", "stable_field_id"),
    )
