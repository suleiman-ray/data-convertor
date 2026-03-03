import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, enum_col
from app.models.enums import ProposalStatus, ProposalType


class MappingProposal(Base):
    __tablename__ = "mapping_proposals"

    proposal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    proposed_by: Mapped[str] = mapped_column(String, nullable=False)
    proposal_type: Mapped[ProposalType] = mapped_column(enum_col(ProposalType), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[ProposalStatus] = mapped_column(
        enum_col(ProposalStatus), nullable=False, default=ProposalStatus.PENDING
    )
    clinical_approved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    clinical_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    product_approved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    product_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
