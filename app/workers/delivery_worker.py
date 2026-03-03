import asyncio
import logging
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.s3 import download_fhir_bundle
from app.models.enums import BundleStatus, DeliveryStatus
from app.models.fhir_bundle import FhirBundle
from app.services.audit import audit_write
from app.workers.base import SQSWorker

logger = logging.getLogger(__name__)

# Maximum delivery attempts before we give up and permanently mark DELIVERY_FAILED.
# Acts as a belt-and-suspenders guard alongside the SQS DLQ maxReceiveCount.
MAX_DELIVERY_ATTEMPTS = 5


class DeliveryWorker(SQSWorker):
    queue_url = settings.sqs_delivery_queue_url
    worker_name = "delivery"

    async def handle(self, body: dict, receipt_handle: str) -> None:
        raw_id = body.get("bundle_id")
        if not raw_id:
            raise ValueError(
                f"[delivery] malformed SQS message — missing 'bundle_id': {body}"
            )
        try:
            bundle_id = uuid.UUID(raw_id)
        except ValueError as exc:
            raise ValueError(
                f"[delivery] malformed SQS message — invalid UUID for 'bundle_id': {raw_id!r}"
            ) from exc
        async with AsyncSessionLocal() as db:
            await _process(db, bundle_id)


# ── Orchestrator ───────────────────────────────────────────────────────────────

async def _process(db: AsyncSession, bundle_id: uuid.UUID) -> None:
    fhir_bundle = await _load_and_guard(db, bundle_id)
    if fhir_bundle is None:
        return

    # delivery_attempts is incremented atomically in the same SQL UPDATE as each
    # committed outcome (success or permanent failure). Do NOT increment here in
    # memory — if the worker crashes before committing, the in-memory increment
    # would be lost and re-delivered messages would see a stale count.

    # Transient failure: log + raise WITHOUT committing FAILED status.
    # The session rolls back so delivery_status stays PENDING and SQS re-delivers.
    try:
        bundle_json = await asyncio.to_thread(download_fhir_bundle, fhir_bundle.bundle_uri)
    except Exception as exc:
        logger.exception("delivery: failed to download bundle %s from S3 (transient)", bundle_id)
        raise  # session rolls back; SQS re-delivers after visibility timeout

    if settings.healthlake_datastore_endpoint:
        await _deliver_to_healthlake(db, fhir_bundle, bundle_json)
    else:
        await _deliver_to_s3_dropzone(db, fhir_bundle)


# ── Delivery strategies ────────────────────────────────────────────────────────

async def _deliver_to_healthlake(
    db: AsyncSession, fhir_bundle: FhirBundle, bundle_json: str
) -> None:
    """POST the FHIR bundle to AWS HealthLake."""
    endpoint = f"{settings.healthlake_datastore_endpoint.rstrip('/')}/r4"
    headers = {
        "Content-Type": "application/fhir+json",
        "Accept": "application/fhir+json",
    }

    # Transport errors (TCP failure, timeout) — transient, do NOT commit FAILED.
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(endpoint, content=bundle_json, headers=headers)
    except httpx.TransportError as exc:
        logger.warning(
            "delivery: HealthLake transport error for bundle %s (transient): %s",
            fhir_bundle.bundle_id, exc,
        )
        raise  # session rolls back; SQS re-delivers

    if resp.status_code in (200, 201, 202):
        status = (
            DeliveryStatus.ACKNOWLEDGED if resp.status_code == 202 else DeliveryStatus.SENT
        )
        bundle_status = (
            BundleStatus.ACKNOWLEDGED if resp.status_code == 202 else BundleStatus.SENT
        )
        now = datetime.now(timezone.utc)
        fhir_bundle.delivery_status = status
        fhir_bundle.status = bundle_status
        fhir_bundle.sent_at = now
        if resp.status_code == 202:
            fhir_bundle.acknowledged_at = now
        fhir_bundle.delivery_attempts = FhirBundle.delivery_attempts + 1
        audit_write(
            db,
            actor_id="system/delivery",
            action="bundle.delivered",
            entity_type="fhir_bundle",
            entity_id=str(fhir_bundle.bundle_id),
            after_state={"delivery_status": status.value, "http_status": resp.status_code},
        )
        await db.commit()
        logger.info(
            "delivery: bundle %s delivered to HealthLake (HTTP %d)",
            fhir_bundle.bundle_id,
            resp.status_code,
        )
        return

    # 4xx = permanent client error (malformed bundle / authorization) — commit FAILED, ack.
    if 400 <= resp.status_code < 500:
        error = f"HealthLake rejected bundle (HTTP {resp.status_code}): {resp.text[:500]}"
        logger.error("delivery: permanent failure for bundle %s: %s", fhir_bundle.bundle_id, error)
        await _record_failure(db, fhir_bundle, error)
        return  # ack — the DLQ receives the message for manual triage

    # 5xx = transient server error — do NOT commit FAILED; SQS re-delivers.
    error = f"HealthLake server error (HTTP {resp.status_code}): {resp.text[:200]}"
    logger.warning(
        "delivery: transient HealthLake 5xx for bundle %s: %s", fhir_bundle.bundle_id, error
    )
    raise RuntimeError(error)  # session rolls back; delivery_status stays PENDING


async def _deliver_to_s3_dropzone(db: AsyncSession, fhir_bundle: FhirBundle) -> None:
    """
    Local-dev / CI delivery path: the bundle is already in S3; we simply mark it SENT.
    Simulates a successful delivery without a real HealthLake endpoint.
    """
    now = datetime.now(timezone.utc)
    fhir_bundle.delivery_status = DeliveryStatus.SENT
    fhir_bundle.status = BundleStatus.SENT
    fhir_bundle.sent_at = now
    fhir_bundle.delivery_attempts = FhirBundle.delivery_attempts + 1
    audit_write(
        db,
        actor_id="system/delivery",
        action="bundle.delivered",
        entity_type="fhir_bundle",
        entity_id=str(fhir_bundle.bundle_id),
        after_state={"delivery_status": DeliveryStatus.SENT.value, "mode": "s3_dropzone"},
    )
    await db.commit()
    logger.info(
        "delivery: bundle %s marked SENT (S3 drop-zone mode, uri=%s)",
        fhir_bundle.bundle_id,
        fhir_bundle.bundle_uri,
    )


# ── Guards & helpers ───────────────────────────────────────────────────────────

async def _load_and_guard(
    db: AsyncSession, bundle_id: uuid.UUID
) -> FhirBundle | None:
    fhir_bundle = await db.scalar(
        select(FhirBundle)
        .where(FhirBundle.bundle_id == bundle_id)
        .with_for_update()
    )
    if fhir_bundle is None:
        logger.error("delivery: fhir_bundle %s not found", bundle_id)
        return None
    if fhir_bundle.delivery_status != DeliveryStatus.PENDING:
        logger.info(
            "delivery: skipping bundle %s (delivery_status=%s)",
            bundle_id,
            fhir_bundle.delivery_status,
        )
        return None
    if fhir_bundle.delivery_attempts >= MAX_DELIVERY_ATTEMPTS:
        # This guard is belt-and-suspenders; it only fires when delivery_attempts
        # was committed (success or permanent failure path) many times. For transient
        # failures the count is not committed, so SQS ApproximateReceiveCount is the
        # primary retry limiter for those paths.
        logger.error(
            "delivery: bundle %s exceeded max committed attempts (%d) — marking DELIVERY_FAILED",
            bundle_id,
            MAX_DELIVERY_ATTEMPTS,
        )
        await _record_failure(
            db, fhir_bundle, f"Exceeded {MAX_DELIVERY_ATTEMPTS} delivery attempts"
        )
        return None
    return fhir_bundle


async def _record_failure(
    db: AsyncSession, fhir_bundle: FhirBundle, error: str
) -> None:
    """Commit a permanent DELIVERY_FAILED outcome. Only call for non-retryable errors."""
    fhir_bundle.delivery_status = DeliveryStatus.FAILED
    fhir_bundle.status = BundleStatus.DELIVERY_FAILED
    fhir_bundle.last_delivery_error = error
    fhir_bundle.delivery_attempts = FhirBundle.delivery_attempts + 1
    audit_write(
        db,
        actor_id="system/delivery",
        action="bundle.delivery_failed",
        entity_type="fhir_bundle",
        entity_id=str(fhir_bundle.bundle_id),
        after_state={"delivery_status": DeliveryStatus.FAILED.value, "error": error[:500]},
    )
    await db.commit()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(DeliveryWorker().run())
