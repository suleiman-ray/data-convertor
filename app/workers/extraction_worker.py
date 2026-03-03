import asyncio
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import sqs as sqs_client
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.s3 import download_raw_artifact
from app.models.enums import ContentFormat, FieldStatus, SubmissionStatus
from app.models.extracted_field import ExtractedField
from app.models.intake_submission import IntakeSubmission
from app.services.audit import audit_write
from app.services.extraction import parse_json_form, parse_structured_text
from app.workers.base import SQSWorker

logger = logging.getLogger(__name__)


class ExtractionWorker(SQSWorker):
    queue_url = settings.sqs_extraction_queue_url
    worker_name = "extraction"

    async def handle(self, body: dict, receipt_handle: str) -> None:
        raw_id = body.get("submission_id")
        if not raw_id:
            raise ValueError(
                f"[extraction] malformed SQS message — missing 'submission_id': {body}"
            )
        try:
            submission_id = uuid.UUID(raw_id)
        except ValueError as exc:
            raise ValueError(
                f"[extraction] malformed SQS message — invalid UUID for 'submission_id': {raw_id!r}"
            ) from exc

        async with AsyncSessionLocal() as db:
            # ── Idempotency guard ─────────────────────────────────────────────
            submission = await db.scalar(
                select(IntakeSubmission)
                .where(IntakeSubmission.submission_id == submission_id)
                .with_for_update()
            )

            if submission is None:
                logger.error("[extraction] submission %s not found — discarding", submission_id)
                return

            if submission.status != SubmissionStatus.PROCESSING:
                logger.info(
                    "[extraction] skipping submission %s (status=%s)",
                    submission_id, submission.status,
                )
                return

            logger.info(
                "[extraction] processing submission %s format=%s",
                submission_id, submission.content_format,
            )

            # ── Download raw artifact from S3 ─────────────────────────────────
            try:
                raw_bytes = await asyncio.to_thread(download_raw_artifact, submission.raw_uri)
            except Exception as exc:
                logger.exception("[extraction] S3 download failed submission %s", submission_id)
                await _fail(db, submission, f"S3 download failed: {exc}")
                return

            # ── Parse by content_format ───────────────────────────────────────
            try:
                if submission.content_format == ContentFormat.JSON_FORM:
                    fields = parse_json_form(raw_bytes, submission.raw_sha256)
                elif submission.content_format == ContentFormat.STRUCTURED_TEXT:
                    fields = parse_structured_text(raw_bytes, submission.raw_sha256)
                else:
                    raise NotImplementedError(
                        f"Parser not implemented for format: {submission.content_format}"
                    )
            except Exception as exc:
                logger.exception("[extraction] parsing failed submission %s", submission_id)
                await _fail(db, submission, f"Extraction failed: {exc}")
                return

            # ── Write extracted_fields (best-effort — include FAILED fields) ──
            ok_count = 0
            failed_count = 0
            for field in fields:
                db.add(ExtractedField(
                    instance_id=uuid.uuid4(),
                    submission_id=submission_id,
                    raw_label=field.raw_label,
                    raw_value=field.raw_value,
                    section_path=field.section_path,
                    provenance=field.provenance,
                    stable_field_id=field.stable_field_id,
                    extractor_version=field.extractor_version,
                    status=field.status,
                    failure_reason=field.failure_reason,
                ))
                if field.status == FieldStatus.OK:
                    ok_count += 1
                else:
                    failed_count += 1

            logger.info(
                "[extraction] submission %s fields_ok=%d fields_failed=%d",
                submission_id, ok_count, failed_count,
            )

            if ok_count == 0 and failed_count > 0:
                logger.error("[extraction] all fields failed submission %s", submission_id)
                await _fail(db, submission, f"All {failed_count} fields failed to extract")
                return

            # ── Publish to resolve-normalize-queue (before commit) ────────────
            # If SQS raises, the exception propagates out and the DB rolls back.
            # The extraction-queue message is not deleted so SQS re-delivers it.
            await asyncio.to_thread(
                sqs_client.send_message,
                settings.sqs_resolve_normalize_queue_url,
                {
                    "submission_id": str(submission_id),
                    "patient_id": submission.patient_id,
                    "intake_type_id": submission.intake_type_id,
                    "intake_type_version": submission.intake_type_version,
                },
            )

            # ── Commit — onupdate fires updated_at automatically ──────────────
            await db.commit()
            logger.info(
                "[extraction] done submission %s published to resolve-normalize-queue",
                submission_id,
            )


async def _fail(db: AsyncSession, submission: IntakeSubmission, reason: str) -> None:
    """Flip submission to FAILED and commit. onupdate handles updated_at."""
    submission.status = SubmissionStatus.FAILED
    submission.failure_reason = reason
    audit_write(
        db,
        actor_id="system/extraction",
        action="submission.failed",
        entity_type="intake_submission",
        entity_id=str(submission.submission_id),
        after_state={"status": SubmissionStatus.FAILED.value, "failure_reason": reason},
    )
    await db.commit()
    logger.error("[extraction] submission %s → FAILED: %s", submission.submission_id, reason)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(ExtractionWorker().run())
