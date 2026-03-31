import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from fhir.resources.bundle import Bundle  # type: ignore[import]
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import FHIR_VERSION
from app.core.database import AsyncSessionLocal
from app.core.s3 import upload_fhir_bundle
from app.core.sqs import send_message_async_with_retry
from app.models.canonical_concept import CanonicalConcept
from app.models.canonical_value import CanonicalValue
from app.models.enums import (
    BundleStatus,
    CanonicalValueState,
    DeliveryStatus,
    SubmissionStatus,
    ValueType,
)
from app.models.fhir_bundle import FhirBundle
from app.models.intake_submission import IntakeSubmission
from app.services.audit import audit_write
from app.services.authoring_templates import get_approved_template
from app.workers.base import SQSWorker

logger = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r"\{\{canonical:([^}]+)\}\}")
_EXACT_PLACEHOLDER_RE = re.compile(r"^\{\{canonical:([^}]+)\}\}$")

# Value types whose normalizer produces {"value": <scalar>}.
# These are emitted as bare scalars in the FHIR template rather than objects.
_SCALAR_VALUE_TYPES: frozenset[ValueType] = frozenset(
    {ValueType.BOOLEAN, ValueType.DATE, ValueType.STRING}
)


class FhirBuilderWorker(SQSWorker):
    queue_url = settings.sqs_fhir_queue_url
    worker_name = "fhir-builder"

    async def handle(self, body: dict, receipt_handle: str) -> None:
        raw_id = body.get("submission_id")
        if not raw_id:
            raise ValueError(
                f"[fhir-builder] malformed SQS message — missing 'submission_id': {body}"
            )
        try:
            submission_id = uuid.UUID(raw_id)
        except ValueError as exc:
            raise ValueError(
                f"[fhir-builder] malformed SQS message — invalid UUID for 'submission_id': {raw_id!r}"
            ) from exc
        async with AsyncSessionLocal() as db:
            await _process(db, submission_id)


# ── Orchestrator ───────────────────────────────────────────────────────────────

async def _process(db: AsyncSession, submission_id: uuid.UUID) -> None:
    submission = await _load_and_guard(db, submission_id)
    if submission is None:
        return

    template = await get_approved_template(
        db, submission.intake_type_id, submission.intake_type_version
    )
    if template is None:
        await _fail(
            db,
            submission,
            f"No approved FHIR template for "
            f"{submission.intake_type_id}/{submission.intake_type_version}",
        )
        return

    rows = await _load_confirmed_values(db, submission_id)
    value_map = _build_value_map(rows)

    try:
        bundle_dict = _fill_placeholders(template.template_json, value_map)
    except ValueError as exc:
        await _fail(db, submission, f"Placeholder fill failed: {exc}")
        return

    validation_errors = _validate_bundle(bundle_dict)

    bundle_json = json.dumps(bundle_dict, ensure_ascii=False, indent=2)
    bundle_id = uuid.uuid4()
    bundle_uri, bundle_sha256 = await asyncio.to_thread(
        upload_fhir_bundle, str(bundle_id), bundle_json
    )

    bundle_status = BundleStatus.BUILT if not validation_errors else BundleStatus.VALIDATION_FAILED
    # Validation-failed bundles must NOT be queued for delivery — the delivery worker
    # uses delivery_status=PENDING as its "ready to deliver" sentinel.  Setting FAILED
    # here prevents _load_and_guard from picking up an invalid bundle.
    bundle_delivery_status = (
        DeliveryStatus.PENDING if not validation_errors else DeliveryStatus.FAILED
    )
    fhir_bundle = FhirBundle(
        bundle_id=bundle_id,
        submission_id=submission_id,
        template_id=template.template_id,
        bundle_uri=bundle_uri,
        bundle_sha256=bundle_sha256,
        fhir_version=FHIR_VERSION,
        status=bundle_status,
        validation_errors={"errors": validation_errors} if validation_errors else None,
        delivery_status=bundle_delivery_status,
        built_at=datetime.now(timezone.utc),
    )
    db.add(fhir_bundle)
    await db.flush()

    if validation_errors:
        await _fail(
            db,
            submission,
            f"FHIR R4 validation failed ({len(validation_errors)} error(s)): "
            f"{validation_errors[0][:200]}",
        )
        return

    # Commit FIRST, then publish.
    #
    # Ordering rationale:
    #   commit-first, publish-second: if commit fails the submission stays
    #   BUILDING_FHIR and the fhir-queue message is re-delivered for a clean
    #   retry.  If publish fails after a successful commit the bundle row exists
    #   in the DB with delivery_status=PENDING and can be recovered by a
    #   re-publish sweep without reprocessing the build phase.
    #
    #   The old publish-first approach had the inverse problem: a successful
    #   publish followed by a commit failure left the delivery worker with a
    #   bundle_id that did not yet exist in the DB, creating an inconsistent state
    #   with no automatic recovery path.
    submission.status = SubmissionStatus.COMPLETE
    audit_write(
        db,
        actor_id="system/fhir-builder",
        action="submission.complete",
        entity_type="intake_submission",
        entity_id=str(submission_id),
        after_state={"status": SubmissionStatus.COMPLETE.value, "bundle_id": str(bundle_id)},
    )
    await db.commit()

    await send_message_async_with_retry(
        settings.sqs_delivery_queue_url,
        {"submission_id": str(submission_id), "bundle_id": str(bundle_id)},
    )
    logger.info(
        "fhir-builder: submission %s → COMPLETE, bundle=%s uploaded to %s",
        submission_id,
        bundle_id,
        bundle_uri,
    )


# ── Step helpers ───────────────────────────────────────────────────────────────

async def _load_and_guard(
    db: AsyncSession, submission_id: uuid.UUID
) -> IntakeSubmission | None:
    submission = await db.scalar(
        select(IntakeSubmission)
        .where(IntakeSubmission.submission_id == submission_id)
        .with_for_update()
    )
    if submission is None:
        logger.error("fhir-builder: submission %s not found", submission_id)
        return None
    if submission.status != SubmissionStatus.BUILDING_FHIR:
        logger.info(
            "fhir-builder: skipping submission %s (status=%s)",
            submission_id,
            submission.status,
        )
        return None
    return submission


async def _load_confirmed_values(
    db: AsyncSession, submission_id: uuid.UUID
) -> list[tuple[CanonicalValue, ValueType]]:
    """
    Load CONFIRMED canonical values joined with their concept's ValueType.

    Returning ValueType here (rather than inferring it from the key shape of
    value_normalized) ensures _build_value_map dispatches correctly even for
    quantity values that have no unit field — {"value": 14.0} is still a
    FHIR Quantity object, not a scalar.
    """
    rows = (
        await db.execute(
            select(CanonicalValue, CanonicalConcept.value_type)
            .join(
                CanonicalConcept,
                CanonicalConcept.canonical_id == CanonicalValue.canonical_id,
            )
            .where(
                CanonicalValue.submission_id == submission_id,
                CanonicalValue.state == CanonicalValueState.CONFIRMED,
            )
        )
    ).all()
    return list(rows)


def _build_value_map(
    rows: list[tuple[CanonicalValue, ValueType]],
) -> dict[str, Any]:
    """
    Map canonical_id → Python value ready for JSON encoding.

    Dispatches on ValueType (not key shape) so QUANTITY values without a unit
    ({"value": 14.0}) are correctly emitted as FHIR Quantity objects rather
    than being mis-identified as scalars.
    """
    result: dict[str, Any] = {}
    for cv, value_type in rows:
        normalized = cv.value_normalized or {}
        if value_type in _SCALAR_VALUE_TYPES:
            # boolean, date, string — the template slot expects a bare scalar.
            result[cv.canonical_id] = normalized.get("value")
        else:
            # quantity {"value":…,"unit":…} or coded {"code":…,"display":…,"system":…}
            # Always emit the full structure so FHIR typing is preserved.
            result[cv.canonical_id] = normalized
    return result


def _fill_placeholders(template_json: dict, value_map: dict[str, Any]) -> dict:
    """
    Fill every {{canonical:<id>}} placeholder in template_json by recursively
    walking the structure rather than round-tripping through a JSON string.

    Two substitution modes:
      1. A string value that is *exactly* a placeholder → replaced with the typed
         Python value, preserving the correct FHIR type (bool, float, dict, …).
      2. A placeholder *embedded* inside a longer string → replaced with str(value).

    Raises ValueError if any placeholder remains after the walk (i.e. no canonical
    value was provided for it).
    """
    result = _walk(template_json, value_map)
    remaining = _collect_placeholders(result)
    if remaining:
        raise ValueError(
            f"Unfilled template placeholders — no canonical values for: {set(remaining)}"
        )
    return result  # type: ignore[return-value]


def _walk(node: Any, value_map: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        return {k: _walk(v, value_map) for k, v in node.items()}
    if isinstance(node, list):
        return [_walk(item, value_map) for item in node]
    if isinstance(node, str):
        # Exact match: the whole string is a placeholder → return the typed value.
        m = _EXACT_PLACEHOLDER_RE.match(node)
        if m:
            canonical_id = m.group(1)
            # If missing from value_map, leave intact so _collect_placeholders reports it.
            return value_map[canonical_id] if canonical_id in value_map else node

        # Partial match: one or more placeholders embedded in a larger string.
        def _sub(match: re.Match) -> str:
            cid = match.group(1)
            if cid not in value_map:
                return match.group(0)  # leave intact for _collect_placeholders
            val = value_map[cid]
            return val if isinstance(val, str) else str(val)

        return _PLACEHOLDER_RE.sub(_sub, node)
    return node


def _collect_placeholders(node: Any) -> list[str]:
    """Return all remaining {{canonical:<id>}} placeholders found in node."""
    if isinstance(node, dict):
        return [cid for v in node.values() for cid in _collect_placeholders(v)]
    if isinstance(node, list):
        return [cid for item in node for cid in _collect_placeholders(item)]
    if isinstance(node, str):
        return _PLACEHOLDER_RE.findall(node)
    return []


def _validate_bundle(bundle_dict: dict) -> list[str]:
    """
    Validate a FHIR R4 bundle with fhir.resources.
    Returns a list of error strings (empty list means valid).

    ``Bundle.model_validate`` normally raises :class:`pydantic.ValidationError`
    for schema violations. We also catch any other exception so a rare
    ``TypeError`` / internal error still becomes a validation failure record
    instead of crashing the worker loop.
    """
    try:
        Bundle.model_validate(bundle_dict)
        return []
    except ValidationError as exc:
        logger.warning("fhir-builder: FHIR R4 validation failed: %s", exc)
        return [str(exc)]
    except Exception as exc:
        logger.warning(
            "fhir-builder: unexpected error during bundle validation (non-ValidationError): %s",
            exc,
            exc_info=True,
        )
        return [str(exc)]


async def _fail(db: AsyncSession, submission: IntakeSubmission, reason: str) -> None:
    """Flip submission to FAILED and commit. onupdate handles updated_at."""
    submission.status = SubmissionStatus.FAILED
    submission.failure_reason = reason
    audit_write(
        db,
        actor_id="system/fhir-builder",
        action="submission.failed",
        entity_type="intake_submission",
        entity_id=str(submission.submission_id),
        after_state={"status": SubmissionStatus.FAILED.value, "failure_reason": reason},
    )
    await db.commit()
    logger.error(
        "fhir-builder: submission %s → FAILED: %s",
        submission.submission_id,
        reason,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(FhirBuilderWorker().run())
