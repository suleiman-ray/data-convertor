from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, enum_col
from app.models.enums import ConceptStatus, ValueType


class CanonicalConcept(Base):
    __tablename__ = "canonical_concepts"

    canonical_id: Mapped[str] = mapped_column(String, primary_key=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[ValueType] = mapped_column(enum_col(ValueType), nullable=False)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    value_domain: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    fhir_data_type: Mapped[str] = mapped_column(String, nullable=False)
    code_system: Mapped[str | None] = mapped_column(String, nullable=True)
    version: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[ConceptStatus] = mapped_column(
        enum_col(ConceptStatus), nullable=False, default=ConceptStatus.ACTIVE
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
