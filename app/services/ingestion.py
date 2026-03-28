"""
Intake ingestion service.

Responsibilities:
  1. Idempotency — return existing submission if idempotency_key already seen.
  2. Validate intake_type_id + version — an (id, version) pair is accepted if at
     least one FhirTemplate row exists for it (any status). This replaces the
     former hardcoded KNOWN_INTAKE_TYPES set; new intake types are onboarded by
     creating a template via POST /authoring/templates without any code change.
  3. Serialize payload → bytes, compute SHA-256, upload to S3 (via asyncio.to_thread — non-blocking).
  4. Write intake_submissions row (RECEIVED → PROCESSING) and commit.
  5. Publish to extraction queue *after* commit so the worker never receives
     a message for a row that doesn't exist yet.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.s3 import upload_raw_artifact
from app.core.sqs import send_message_async_with_retry
from app.models.canonical_value import CanonicalValue
from app.models.enums import CanonicalValueState, ContentFormat, SubmissionStatus
from app.models.fhir_template import FhirTemplate
from app.models.intake_submission import IntakeSubmission
from app.schemas.submission import SubmissionCreate

logger = logging.getLogger(__name__)


class IngestionError(Exception):
    pass


class DuplicateSubmission(Exception):
    def __init__(self, submission: IntakeSubmission) -> None:
        self.submission = submission


async def ingest(db: AsyncSession, data: SubmissionCreate) -> IntakeSubmission:
    """
    Create and queue a new submission, or return the existing one if the
    idempotency_key has already been used.

    Raises IngestionError for validation failures.
    """
    # An intake type/version pair is valid if any FhirTemplate row exists for it.
    template_count = await db.scalar(
        select(func.count()).select_from(FhirTemplate).where(
            FhirTemplate.intake_type_id == data.intake_type_id,
            FhirTemplate.intake_type_version == data.intake_type_version,
        )
    )
    if not template_count:
        raise IngestionError(
            f"Unknown intake type '{data.intake_type_id}' version '{data.intake_type_version}'. "
            f"Create a FhirTemplate for this type before submitting."
        )

    existing = await db.scalar(
        select(IntakeSubmission).where(
            IntakeSubmission.idempotency_key == data.idempotency_key
        )
    )
    if existing is not None:
        logger.info(
            "Duplicate submission — idempotency_key=%s submission_id=%s",
            data.idempotency_key, existing.submission_id,
        )
        raise DuplicateSubmission(existing)

    raw_bytes = json.dumps(data.payload, ensure_ascii=False).encode("utf-8")
    submission_id = uuid.uuid4()

    raw_uri, raw_sha256 = await asyncio.to_thread(
        upload_raw_artifact,
        str(submission_id),
        raw_bytes,
        "application/json",
    )
    logger.info("Raw artifact uploaded uri=%s sha256=%s", raw_uri, raw_sha256)

    submission = IntakeSubmission(
        submission_id=submission_id,
        idempotency_key=data.idempotency_key,
        patient_id=data.patient_id,
        intake_type_id=data.intake_type_id,
        intake_type_version=data.intake_type_version,
        content_format=data.content_format,
        raw_uri=raw_uri,
        raw_sha256=raw_sha256,
        submitted_by=data.submitted_by,
        status=SubmissionStatus.RECEIVED,
    )
    db.add(submission)
    submission.status = SubmissionStatus.PROCESSING
    submission.queued_at = datetime.now(timezone.utc)

    # ── 5. Flush + commit (with race guard) ─────────────────────────────────
    # Two concurrent requests with the same idempotency_key can both pass the
    # read check above (step 2) and race to insert.  The UNIQUE constraint on
    # idempotency_key ensures only one writer wins; the loser gets an
    # IntegrityError which we convert into the same DuplicateSubmission path.
    try:
        await db.flush()
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await db.scalar(
            select(IntakeSubmission).where(
                IntakeSubmission.idempotency_key == data.idempotency_key
            )
        )
        raise DuplicateSubmission(existing)
    await db.refresh(submission)

    # ── 6. Publish to extraction queue (after commit) ────────────────────────
    message = {
        "submission_id": str(submission.submission_id),
        "patient_id": submission.patient_id,
        "raw_uri": submission.raw_uri,
        "raw_sha256": submission.raw_sha256,
        "intake_type_id": submission.intake_type_id,
        "intake_type_version": submission.intake_type_version,
        "content_format": submission.content_format.value,
    }
    await send_message_async_with_retry(settings.sqs_extraction_queue_url, message)
    logger.info(
        "Submission queued submission_id=%s queue=%s",
        submission.submission_id, settings.sqs_extraction_queue_url,
    )

    return submission


class RebuildError(Exception):
    """Raised when a rebuild is not permitted in the current submission state."""


async def rebuild_submission(db: AsyncSession, submission_id: uuid.UUID) -> IntakeSubmission:
    """
    Reset a FAILED submission back to BUILDING_FHIR and re-publish to fhir-queue.

    Preconditions (raises RebuildError if not met):
      1. The submission must be in FAILED status.
      2. At least one CONFIRMED CanonicalValue must exist for the submission,
         proving that extraction and normalization completed successfully.
         This prevents a rebuild from being triggered for submissions that
         failed before the FHIR build phase — those would immediately re-fail
         with a placeholder error, giving operators no useful recovery signal.
    """
    submission = await db.scalar(
        select(IntakeSubmission).where(IntakeSubmission.submission_id == submission_id)
        .with_for_update()
    )
    if submission is None:
        return None

    if submission.status != SubmissionStatus.FAILED:
        raise RebuildError(
            f"Submission {submission_id} cannot be rebuilt from status "
            f"'{submission.status.value}' — only FAILED submissions are eligible."
        )

    confirmed_count = await db.scalar(
        select(func.count()).where(
            CanonicalValue.submission_id == submission_id,
            CanonicalValue.state == CanonicalValueState.CONFIRMED,
        )
    ) or 0
    if confirmed_count == 0:
        raise RebuildError(
            f"Submission {submission_id} has no CONFIRMED canonical values. "
            f"Rebuild is only valid for submissions that failed during the FHIR build "
            f"phase. Submissions that failed at extraction or normalization must be "
            f"re-submitted via POST /submissions."
        )

    submission.status = SubmissionStatus.BUILDING_FHIR
    submission.failure_reason = None
    await db.commit()
    await db.refresh(submission)

    await send_message_async_with_retry(
        settings.sqs_fhir_queue_url,
        {"submission_id": str(submission_id)},
    )
    logger.info(
        "Submission %s reset to BUILDING_FHIR and re-published to fhir-queue",
        submission_id,
    )
    return submission


async def get_submission(db: AsyncSession, submission_id: uuid.UUID) -> IntakeSubmission | None:
    return await db.scalar(
        select(IntakeSubmission).where(IntakeSubmission.submission_id == submission_id)
    )


async def list_submissions(
    db: AsyncSession,
    status: SubmissionStatus | None = None,
    patient_id: str | None = None,
    intake_type_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[IntakeSubmission]:
    q = select(IntakeSubmission)
    if status is not None:
        q = q.where(IntakeSubmission.status == status)
    if patient_id is not None:
        q = q.where(IntakeSubmission.patient_id == patient_id)
    if intake_type_id is not None:
        q = q.where(IntakeSubmission.intake_type_id == intake_type_id)
    q = q.order_by(IntakeSubmission.received_at.desc()).limit(limit).offset(offset)
    return list((await db.scalars(q)).all())
