import logging

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.sqs import send_message_async_with_retry
from app.models.enums import SubmissionStatus, UnmappedStatus
from app.models.intake_submission import IntakeSubmission
from app.models.unmapped_field import UnmappedField

logger = logging.getLogger(__name__)


async def requeue_needs_review_submissions(
    intake_type_id: str,
    intake_type_version: str,
    stable_field_id: str,
) -> int:
    """
    After a new mapping is approved, unblock all NEEDS_REVIEW submissions
    that were blocked on that stable_field_id.

    Commits **before** publish per submission (aligned with FHIR builder). SQS
    send uses retries; if all attempts fail after commit, the row is PROCESSING
    without a queue message — operator may re-call the requeue API.

    Returns the count of submissions re-queued.
    """
    # Collect IDs in a short-lived session to avoid holding a connection
    # across the per-submission loop below.
    async with AsyncSessionLocal() as db:
        blocked = list(
            (await db.scalars(
                select(IntakeSubmission.submission_id)
                .join(
                    UnmappedField,
                    UnmappedField.submission_id == IntakeSubmission.submission_id,
                )
                .where(
                    IntakeSubmission.status == SubmissionStatus.NEEDS_REVIEW,
                    UnmappedField.intake_type_id == intake_type_id,
                    UnmappedField.intake_type_version == intake_type_version,
                    UnmappedField.stable_field_id == stable_field_id,
                    UnmappedField.status == UnmappedStatus.PENDING_REVIEW,
                )
            )).all()
        )

    count = 0
    for sid in blocked:
        async with AsyncSessionLocal() as db:
            sub = await db.scalar(
                select(IntakeSubmission)
                .where(IntakeSubmission.submission_id == sid)
                .with_for_update()
            )
            if not sub or sub.status != SubmissionStatus.NEEDS_REVIEW:
                continue

            # A stable_field_id may appear in multiple instances within a form
            # (e.g. a repeated question). Update ALL of them so none stay in
            # PENDING_REVIEW, which would cause the next resolve run to flip
            # the submission back to NEEDS_REVIEW in an infinite loop.
            unmapped_rows = list(
                (await db.scalars(
                    select(UnmappedField).where(
                        UnmappedField.submission_id == sid,
                        UnmappedField.stable_field_id == stable_field_id,
                        UnmappedField.status == UnmappedStatus.PENDING_REVIEW,
                    )
                )).all()
            )
            for unmapped in unmapped_rows:
                unmapped.status = UnmappedStatus.MAPPING_CREATED

            sub.status = SubmissionStatus.PROCESSING

            # Commit FIRST, then publish (aligned with fhir_builder_worker / ingestion).
            # Transient SQS failures are retried via send_message_async_with_retry; if all
            # attempts fail, DB already shows PROCESSING — operator may re-run requeue API.
            await db.commit()
            await send_message_async_with_retry(
                settings.sqs_resolve_normalize_queue_url,
                {"submission_id": str(sid)},
            )
            count += 1
            logger.info("requeue: re-enqueued submission %s after mapping created", sid)

    return count
