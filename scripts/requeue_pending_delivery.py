"""
Sweep for FHIR bundles with delivery_status=PENDING that have no pending
SQS message — this can happen when the fhir-builder commits successfully but
the subsequent delivery-queue publish fails after exhausting all retries.

Usage:
    python scripts/requeue_pending_delivery.py [--min-age-minutes N] [--dry-run]

The script finds all FhirBundle rows where:
  - delivery_status = PENDING
  - built_at is older than --min-age-minutes (default: 10)

…and re-publishes each to the delivery queue.

Safe to run multiple times: the delivery worker uses SELECT FOR UPDATE +
idempotency checks, so duplicate messages are harmlessly skipped.
"""
import argparse
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Allow running from the repo root without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.sqs import send_message_async_with_retry
from app.models.enums import DeliveryStatus
from app.models.fhir_bundle import FhirBundle

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("requeue_pending_delivery")


async def requeue_pending(min_age_minutes: int, dry_run: bool) -> int:
    """
    Re-publish stuck PENDING bundles to the delivery queue.
    Returns the count of bundles re-queued (or that would be re-queued in dry-run).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=min_age_minutes)

    async with AsyncSessionLocal() as db:
        bundles = list(
            (
                await db.scalars(
                    select(FhirBundle).where(
                        FhirBundle.delivery_status == DeliveryStatus.PENDING,
                        FhirBundle.built_at < cutoff,
                    )
                )
            ).all()
        )

    if not bundles:
        logger.info("No stuck PENDING bundles found (min_age=%dm).", min_age_minutes)
        return 0

    logger.info(
        "Found %d stuck PENDING bundle(s) older than %d minutes.",
        len(bundles),
        min_age_minutes,
    )

    count = 0
    for bundle in bundles:
        logger.info(
            "%sRe-queuing bundle_id=%s submission_id=%s built_at=%s",
            "[DRY-RUN] " if dry_run else "",
            bundle.bundle_id,
            bundle.submission_id,
            bundle.built_at,
        )
        if not dry_run:
            await send_message_async_with_retry(
                settings.sqs_delivery_queue_url,
                {
                    "submission_id": str(bundle.submission_id),
                    "bundle_id": str(bundle.bundle_id),
                },
            )
        count += 1

    logger.info("%d bundle(s) re-queued.", count)
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-queue stuck PENDING delivery bundles.")
    parser.add_argument(
        "--min-age-minutes",
        type=int,
        default=10,
        help="Only requeue bundles whose built_at is older than this many minutes (default: 10).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be re-queued without sending any SQS messages.",
    )
    args = parser.parse_args()
    asyncio.run(requeue_pending(args.min_age_minutes, args.dry_run))


if __name__ == "__main__":
    main()
