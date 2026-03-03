"""
Mapping Proposal service — Phase 6.

Dual-approval governance:
  1. POST /proposals              → create proposal (status=PENDING)
  2. POST /proposals/{id}/approve → clinical sign-off  (person 1)
  3. POST /proposals/{id}/second-approve → product sign-off (person 2)

Rules:
  - The same person CANNOT provide both approvals.
  - For FIELD_MAPPING proposals, final (second) approval atomically:
      a. Creates a FieldToCanonical mapping in the SAME transaction.
      b. Commits proposal APPROVED + mapping in one db.commit().
      c. If mapping creation fails the whole transaction rolls back,
         the proposal is set to SUPERSEDED, and a ProposalConflict is raised.
      d. After a successful commit, invalidates the Redis cache and calls
         requeue_needs_review_submissions().
  - Proposals in APPROVED, REJECTED, or SUPERSEDED status cannot be re-approved.

Duplicate PENDING proposals:
  When a FIELD_MAPPING proposal is created for a (stable_field_id, canonical_id)
  that already has a PENDING proposal, the older proposal is auto-superseded so
  operators are never left with two redundant items to approve.
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import invalidate_cached_mapping
from app.models.enums import MappingMethod, ProposalStatus, ProposalType
from app.models.mapping_proposal import MappingProposal
from app.schemas.authoring import MappingCreate, ProposalCreate, ProposalReject
from app.services.audit import audit_write
from app.services.authoring_mappings import (
    MappingConflict,
    MappingReferenceError,
    prepare_mapping,
)
from app.services.requeue import requeue_needs_review_submissions

logger = logging.getLogger(__name__)


class ProposalNotFound(Exception):
    """Raised when a proposal row does not exist — maps to HTTP 404."""


class ProposalConflict(Exception):
    """Raised for approval / state conflicts — maps to HTTP 409."""



async def create_proposal(db: AsyncSession, data: ProposalCreate) -> MappingProposal:
    if data.proposal_type == ProposalType.FIELD_MAPPING:
        sfid = data.payload.get("stable_field_id", "")
        cid = data.payload.get("canonical_id", "")
        if sfid and cid:
            duplicates = list(
                (
                    await db.scalars(
                        select(MappingProposal).where(
                            MappingProposal.proposal_type == ProposalType.FIELD_MAPPING,
                            MappingProposal.status == ProposalStatus.PENDING,
                            MappingProposal.payload["stable_field_id"].astext == sfid,
                            MappingProposal.payload["canonical_id"].astext == cid,
                        )
                    )
                ).all()
            )
            for old in duplicates:
                old.status = ProposalStatus.SUPERSEDED
                old.rejection_reason = (
                    f"Superseded by new proposal from '{data.proposed_by}'"
                )
                logger.info(
                    "create_proposal: auto-superseded duplicate proposal %s",
                    old.proposal_id,
                )

    proposal = MappingProposal(
        proposed_by=data.proposed_by,
        proposal_type=data.proposal_type,
        payload=data.payload,
        confidence_score=data.confidence_score,
        status=ProposalStatus.PENDING,
    )
    db.add(proposal)
    await db.commit()
    await db.refresh(proposal)
    logger.info(
        "Created proposal proposal_id=%s type=%s proposed_by=%s",
        proposal.proposal_id,
        data.proposal_type,
        data.proposed_by,
    )
    return proposal


async def get_proposal(db: AsyncSession, proposal_id: uuid.UUID) -> MappingProposal:
    proposal = await db.scalar(
        select(MappingProposal).where(MappingProposal.proposal_id == proposal_id)
    )
    if proposal is None:
        raise ProposalNotFound(f"Proposal '{proposal_id}' not found")
    return proposal


async def list_proposals(
    db: AsyncSession,
    status: ProposalStatus | None = None,
    proposal_type: ProposalType | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[MappingProposal]:
    q = select(MappingProposal)
    if status is not None:
        q = q.where(MappingProposal.status == status)
    if proposal_type is not None:
        q = q.where(MappingProposal.proposal_type == proposal_type)
    q = q.order_by(MappingProposal.created_at.desc()).limit(limit).offset(offset)
    return list((await db.scalars(q)).all())



async def clinical_approve(
    db: AsyncSession, proposal_id: uuid.UUID, approved_by: str
) -> MappingProposal:
    """
    First approval step (clinical sign-off).

    Sets clinical_approved_by / clinical_approved_at.
    Does NOT yet set status=APPROVED — that requires the second approval.
    """
    proposal = await get_proposal(db, proposal_id)
    _assert_actionable(proposal)

    if proposal.clinical_approved_by is not None:
        raise ProposalConflict(
            f"Proposal '{proposal_id}' already has a clinical approval "
            f"from '{proposal.clinical_approved_by}'"
        )

    proposal.clinical_approved_by = approved_by
    proposal.clinical_approved_at = datetime.now(timezone.utc)
    audit_write(
        db,
        actor_id=approved_by,
        action="proposal.clinical_approved",
        entity_type="mapping_proposal",
        entity_id=str(proposal_id),
        after_state={"clinical_approved_by": approved_by},
    )
    await db.commit()
    await db.refresh(proposal)
    logger.info(
        "Clinical approval recorded proposal_id=%s approved_by=%s",
        proposal_id,
        approved_by,
    )
    return proposal


async def product_approve(
    db: AsyncSession, proposal_id: uuid.UUID, approved_by: str
) -> MappingProposal:
    """
    Second approval step (product sign-off).

    Dual-sign enforcement: the product approver must differ from the clinical approver.

    For FIELD_MAPPING proposals the mapping is created INSIDE the same transaction
    so that a mapping-creation failure rolls back the APPROVED status too — the
    proposal is then set to SUPERSEDED and a ProposalConflict is raised.
    """
    proposal = await get_proposal(db, proposal_id)
    _assert_actionable(proposal)

    if proposal.clinical_approved_by is None:
        raise ProposalConflict(
            f"Proposal '{proposal_id}' requires clinical approval before product approval"
        )

    if proposal.clinical_approved_by == approved_by:
        raise ProposalConflict(
            "Dual-sign violation: the product approver must be a different person "
            f"from the clinical approver ('{proposal.clinical_approved_by}')"
        )

    if proposal.product_approved_by is not None:
        raise ProposalConflict(
            f"Proposal '{proposal_id}' already has a product approval "
            f"from '{proposal.product_approved_by}'"
        )

    now = datetime.now(timezone.utc)
    proposal.product_approved_by = approved_by
    proposal.product_approved_at = now
    proposal.status = ProposalStatus.APPROVED
    mapping_data: MappingCreate | None = None

    if proposal.proposal_type == ProposalType.FIELD_MAPPING:
        mapping_data = _build_mapping_data(proposal, approved_by)
        try:
            mapping = await prepare_mapping(db, mapping_data)
            audit_write(
                db,
                actor_id=approved_by,
                action="mapping.created",
                entity_type="field_to_canonical",
                entity_id=str(mapping.id),
                after_state={
                    "intake_type_id": mapping_data.intake_type_id,
                    "stable_field_id": mapping_data.stable_field_id,
                    "canonical_id": mapping_data.canonical_id,
                    "via_proposal": str(proposal_id),
                },
            )
        except (MappingReferenceError, MappingConflict, ValueError) as exc:
            # Roll back: proposal stays PENDING in the DB, mapping is discarded.
            await db.rollback()

            # Re-fetch the proposal (detached after rollback) and mark EXECUTION_FAILED
            # so the failure is clearly distinguished from a business-logic supersession
            # and is visible through the proposals API without digging into logs.
            proposal = await db.scalar(
                select(MappingProposal)
                .where(MappingProposal.proposal_id == proposal_id)
                .with_for_update()
            )
            proposal.status = ProposalStatus.EXECUTION_FAILED
            proposal.rejection_reason = f"Mapping creation failed during approval: {exc}"
            await db.commit()

            logger.error(
                "product_approve: proposal %s → EXECUTION_FAILED (mapping creation failed: %s)",
                proposal_id, exc,
            )
            raise ProposalConflict(
                f"Proposal approved but mapping creation failed: {exc}. "
                f"Proposal has been set to EXECUTION_FAILED."
            ) from exc

    audit_write(
        db,
        actor_id=approved_by,
        action="proposal.product_approved",
        entity_type="mapping_proposal",
        entity_id=str(proposal_id),
        after_state={"status": ProposalStatus.APPROVED.value, "product_approved_by": approved_by},
    )
    await db.commit()
    await db.refresh(proposal)
    logger.info(
        "Product approval recorded — proposal_id=%s now APPROVED (approved_by=%s)",
        proposal_id,
        approved_by,
    )

    if mapping_data is not None:
        await invalidate_cached_mapping(
            mapping_data.intake_type_id,
            mapping_data.intake_type_version,
            mapping_data.stable_field_id,
        )
        requeued = await requeue_needs_review_submissions(
            intake_type_id=mapping_data.intake_type_id,
            intake_type_version=mapping_data.intake_type_version,
            stable_field_id=mapping_data.stable_field_id,
        )
        logger.info(
            "Proposal %s: re-queued %d NEEDS_REVIEW submission(s) for sfid=%s",
            proposal_id,
            requeued,
            mapping_data.stable_field_id,
        )

    return proposal


async def reject_proposal(
    db: AsyncSession, proposal_id: uuid.UUID, data: ProposalReject
) -> MappingProposal:
    proposal = await get_proposal(db, proposal_id)
    _assert_actionable(proposal)

    proposal.status = ProposalStatus.REJECTED
    proposal.rejection_reason = f"[{data.rejected_by}] {data.rejection_reason}"
    audit_write(
        db,
        actor_id=data.rejected_by,
        action="proposal.rejected",
        entity_type="mapping_proposal",
        entity_id=str(proposal_id),
        after_state={
            "status": ProposalStatus.REJECTED.value,
            "rejection_reason": data.rejection_reason,
        },
    )
    await db.commit()
    await db.refresh(proposal)
    logger.info("Rejected proposal proposal_id=%s by=%s", proposal_id, data.rejected_by)
    return proposal



def _assert_actionable(proposal: MappingProposal) -> None:
    """Raise ProposalConflict if the proposal is in a terminal state."""
    if proposal.status in (
        ProposalStatus.APPROVED,
        ProposalStatus.REJECTED,
        ProposalStatus.SUPERSEDED,
        ProposalStatus.EXECUTION_FAILED,
    ):
        raise ProposalConflict(
            f"Proposal '{proposal.proposal_id}' is in status '{proposal.status}' "
            "and cannot be modified"
        )


def _build_mapping_data(proposal: MappingProposal, approved_by: str) -> MappingCreate:
    """
    Extract MappingCreate from a FIELD_MAPPING proposal's payload.

    Payload validation (required keys) is enforced by the ProposalCreate schema
    at creation time, so missing keys here indicate data predating that validation.
    """
    payload = proposal.payload
    required = {"stable_field_id", "canonical_id", "intake_type_id", "intake_type_version"}
    missing = required - payload.keys()
    if missing:
        # ValueError: this is a data integrity problem (malformed payload), not a
        # business-logic conflict about a duplicate active mapping.
        raise ValueError(
            f"Proposal {proposal.proposal_id} payload is missing required keys: {missing}"
        )

    return MappingCreate(
        intake_type_id=payload["intake_type_id"],
        intake_type_version=payload["intake_type_version"],
        stable_field_id=payload["stable_field_id"],
        canonical_id=payload["canonical_id"],
        # Use .value as the default so MappingMethod() receives a plain string,
        # avoiding the appearance of double-wrapping an enum instance.
        mapping_method=MappingMethod(
            payload.get("mapping_method", MappingMethod.AGENT.value)
        ),
        approved_by=approved_by,
    )
