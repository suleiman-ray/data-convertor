import asyncio
import logging
import uuid
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.sqs import send_message
from app.models.canonical_value import CanonicalValue
from app.models.enums import CanonicalValueState, SubmissionStatus, UnmappedStatus
from app.models.extracted_field import ExtractedField
from app.models.intake_submission import IntakeSubmission
from app.models.unmapped_field import UnmappedField
from app.services.audit import audit_write
from app.services.normalizer import NORMALIZER_VERSION, NormalizationError, normalize
from app.services.resolver import MappingNotFound, resolve
from app.workers.base import SQSWorker

logger = logging.getLogger(__name__)


class ResolveNormalizeWorker(SQSWorker):
    queue_url = settings.sqs_resolve_normalize_queue_url
    worker_name = "resolve-normalize"

    async def handle(self, body: dict, receipt_handle: str) -> None:
        raw_id = body.get("submission_id")
        if not raw_id:
            raise ValueError(
                f"[resolve-normalize] malformed SQS message — missing 'submission_id': {body}"
            )
        try:
            submission_id = uuid.UUID(raw_id)
        except ValueError as exc:
            raise ValueError(
                f"[resolve-normalize] malformed SQS message — invalid UUID for 'submission_id': {raw_id!r}"
            ) from exc
        async with AsyncSessionLocal() as db:
            await _process(db, submission_id)


# ── Orchestrator ──────────────────────────────────────────────────────────────

async def _process(db: AsyncSession, submission_id: uuid.UUID) -> None:
    submission = await _load_and_guard(db, submission_id)
    if submission is None:
        return

    fields = await _load_fields(db, submission_id)
    if not fields:
        await _fail(db, submission, "No extracted fields found")
        return

    already_handled = await _already_handled_instance_ids(db, submission_id)
    pending_fields = [f for f in fields if f.instance_id not in already_handled]

    has_unmapped = await _resolve_and_normalize(db, submission, pending_fields)

    # If there were previously unmapped fields (from an earlier run), include them
    if not has_unmapped:
        existing_unmapped_count = await db.scalar(
            select(UnmappedField.id)
            .where(
                UnmappedField.submission_id == submission_id,
                UnmappedField.status == UnmappedStatus.PENDING_REVIEW,
            )
            .limit(1)
        )
        has_unmapped = existing_unmapped_count is not None

    await db.flush()

    if has_unmapped:
        submission.status = SubmissionStatus.NEEDS_REVIEW
        audit_write(
            db,
            actor_id="system/resolve-normalize",
            action="submission.needs_review",
            entity_type="intake_submission",
            entity_id=str(submission_id),
            after_state={"status": SubmissionStatus.NEEDS_REVIEW.value},
        )
        await db.commit()
        logger.info("resolve-normalize: submission %s → NEEDS_REVIEW", submission_id)
        return

    failed_count = await _normalization_failed_count(db, submission_id)
    if failed_count:
        await _fail(db, submission, f"{failed_count} field(s) failed normalization")
        return

    await _advance_to_building_fhir(db, submission)


# ── Step functions ────────────────────────────────────────────────────────────

async def _load_and_guard(
    db: AsyncSession, submission_id: uuid.UUID
) -> IntakeSubmission | None:
    submission = await db.scalar(
        select(IntakeSubmission)
        .where(IntakeSubmission.submission_id == submission_id)
        .with_for_update()
    )
    if submission is None:
        logger.error("resolve-normalize: submission %s not found", submission_id)
        return None
    if submission.status != SubmissionStatus.PROCESSING:
        logger.info(
            "resolve-normalize: skipping submission %s (status=%s)",
            submission_id, submission.status,
        )
        return None
    return submission


async def _load_fields(
    db: AsyncSession, submission_id: uuid.UUID
) -> list[ExtractedField]:
    return list(
        (await db.scalars(
            select(ExtractedField).where(ExtractedField.submission_id == submission_id)
        )).all()
    )


async def _already_handled_instance_ids(
    db: AsyncSession, submission_id: uuid.UUID
) -> set[uuid.UUID]:
    cv_ids = set(
        (await db.scalars(
            select(CanonicalValue.instance_id).where(
                CanonicalValue.submission_id == submission_id
            )
        )).all()
    )
    unmapped_ids = set(
        (await db.scalars(
            select(UnmappedField.instance_id).where(
                UnmappedField.submission_id == submission_id
            )
        )).all()
    )
    return cv_ids | unmapped_ids


async def _resolve_and_normalize(
    db: AsyncSession,
    submission: IntakeSubmission,
    fields: list[ExtractedField],
) -> bool:
    """
    Resolve and normalize each field.  Returns True if any field was unmapped.
    All DB objects are added to the session but NOT yet flushed.
    """
    has_unmapped = False

    for field in fields:
        try:
            concept = await resolve(
                db,
                submission.intake_type_id,
                submission.intake_type_version,
                field.stable_field_id,
            )
        except MappingNotFound:
            has_unmapped = True
            db.add(UnmappedField(
                submission_id=submission.submission_id,
                instance_id=field.instance_id,
                intake_type_id=submission.intake_type_id,
                intake_type_version=submission.intake_type_version,
                stable_field_id=field.stable_field_id,
                raw_label=field.raw_label,
                raw_value=field.raw_value,
                status=UnmappedStatus.PENDING_REVIEW,
            ))
            logger.warning(
                "resolve-normalize: unmapped field %s (sfid=%s) submission=%s",
                field.instance_id, field.stable_field_id, submission.submission_id,
            )
            continue

        try:
            normalized = normalize(
                value_type=concept.value_type,
                raw=field.raw_value or "",
                unit=concept.unit,
                value_domain=concept.value_domain,
            )
            cv_state = CanonicalValueState.CONFIRMED
            failure_reason = None
        except NormalizationError as exc:
            normalized = {}
            cv_state = CanonicalValueState.NORMALIZATION_FAILED
            failure_reason = str(exc)
            logger.warning(
                "resolve-normalize: normalization failed field=%s concept=%s: %s",
                field.instance_id, concept.canonical_id, exc,
            )

        db.add(CanonicalValue(
            submission_id=submission.submission_id,
            patient_id=submission.patient_id,
            instance_id=field.instance_id,
            canonical_id=concept.canonical_id,
            value_raw=field.raw_value or "",
            value_normalized=normalized,
            state=cv_state,
            failure_reason=failure_reason,
            normalizer_version=NORMALIZER_VERSION,
        ))

    return has_unmapped


async def _normalization_failed_count(
    db: AsyncSession, submission_id: uuid.UUID
) -> int:
    return await db.scalar(
        select(func.count()).where(
            CanonicalValue.submission_id == submission_id,
            CanonicalValue.state == CanonicalValueState.NORMALIZATION_FAILED,
        )
    ) or 0


async def _advance_to_building_fhir(
    db: AsyncSession, submission: IntakeSubmission
) -> None:
    """
    Publish to fhir-queue FIRST, then commit status change.

    If publish raises, the exception propagates out of the async with block,
    the DB transaction rolls back, and the SQS message for this submission
    is re-delivered after the visibility timeout.
    """
    await asyncio.to_thread(
        send_message,
        settings.sqs_fhir_queue_url,
        {"submission_id": str(submission.submission_id)},
    )
    submission.status = SubmissionStatus.BUILDING_FHIR
    audit_write(
        db,
        actor_id="system/resolve-normalize",
        action="submission.building_fhir",
        entity_type="intake_submission",
        entity_id=str(submission.submission_id),
        after_state={"status": SubmissionStatus.BUILDING_FHIR.value},
    )
    await db.commit()
    logger.info(
        "resolve-normalize: submission %s → BUILDING_FHIR (published to fhir-queue)",
        submission.submission_id,
    )


async def _fail(
    db: AsyncSession, submission: IntakeSubmission, reason: str
) -> None:
    submission.status = SubmissionStatus.FAILED
    submission.failure_reason = reason
    audit_write(
        db,
        actor_id="system/resolve-normalize",
        action="submission.failed",
        entity_type="intake_submission",
        entity_id=str(submission.submission_id),
        after_state={"status": SubmissionStatus.FAILED.value, "failure_reason": reason},
    )
    await db.commit()
    logger.error(
        "resolve-normalize: submission %s → FAILED: %s",
        submission.submission_id, reason,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(ResolveNormalizeWorker().run())
