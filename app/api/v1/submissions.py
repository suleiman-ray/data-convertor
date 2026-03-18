import asyncio
import json
import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.s3 import download_fhir_bundle
from app.models.enums import SubmissionStatus
from app.models.extracted_field import ExtractedField
from app.models.fhir_bundle import FhirBundle
from app.schemas.submission import (
    BundleMetaResponse,
    ExtractedFieldResponse,
    SubmissionCreate,
    SubmissionResponse,
    SubmissionStatusResponse,
    SubmissionSummary,
)
from app.services.ingestion import (
    DuplicateSubmission,
    IngestionError,
    RebuildError,
    get_submission,
    ingest,
    list_submissions,
    rebuild_submission,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/submissions", tags=["Submissions"])


@router.post(
    "",
    response_model=SubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit an intake for FHIR conversion",
)
async def create_submission(
    body: SubmissionCreate,
    db: AsyncSession = Depends(get_db),
) -> SubmissionResponse:
    """
    Accept an intake payload, store it, and queue it for processing.

    - Returns **202 Accepted** with the submission record immediately.
    - If the same `idempotency_key` is submitted again, returns **200 OK**
      with the existing submission (safe to retry).
    - Returns **422** for unknown intake types or malformed payloads.
    """
    try:
        submission = await ingest(db, body)
        logger.info("Submission created submission_id=%s", submission.submission_id)
        return SubmissionResponse.model_validate(submission)

    except DuplicateSubmission as exc:
        # Idempotent — return the existing submission with 200 (not 202)
        return JSONResponse(
            content=SubmissionResponse.model_validate(exc.submission).model_dump(mode="json"),
            status_code=status.HTTP_200_OK,
        )

    except IngestionError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    except Exception:
        logger.exception("Unexpected error during ingestion")
        raise


@router.get(
    "",
    response_model=list[SubmissionSummary],
    summary="List submissions",
)
async def list_submissions_endpoint(
    submission_status: SubmissionStatus | None = Query(None, alias="status"),
    patient_id: str | None = Query(None),
    intake_type_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[SubmissionSummary]:
    """
    List submissions with optional filters.

    - **status**: filter by pipeline status (RECEIVED, PROCESSING, NEEDS_REVIEW, …)
    - **patient_id**: filter to a single patient's submissions
    - **intake_type_id**: filter to a specific intake type
    - Results are ordered newest-first.
    """
    submissions = await list_submissions(
        db,
        status=submission_status,
        patient_id=patient_id,
        intake_type_id=intake_type_id,
        limit=limit,
        offset=offset,
    )
    return [SubmissionSummary.model_validate(s) for s in submissions]


@router.post(
    "/{submission_id}/rebuild",
    response_model=SubmissionStatusResponse,
    summary="Re-trigger FHIR build for a failed submission",
)
async def rebuild_submission_endpoint(
    submission_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> SubmissionStatusResponse:
    """
    Reset a **FAILED** submission back to **BUILDING_FHIR** and re-queue it for the
    FHIR Builder Worker.

    Use this after fixing the root cause of the failure — typically updating or
    replacing the approved FHIR template, then calling this endpoint to retry
    the build without re-submitting the original intake payload.

    Returns **404** if the submission does not exist.
            **409** if the submission is not in FAILED status.
    """
    try:
        submission = await rebuild_submission(db, submission_id)
    except RebuildError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if submission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")
    return SubmissionStatusResponse.model_validate(submission)


@router.get(
    "/{submission_id}/fields",
    response_model=list[ExtractedFieldResponse],
    summary="List fields extracted from a submission",
)
async def list_extracted_fields(
    submission_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[ExtractedFieldResponse]:
    """
    Return every field that the Extraction Worker parsed out of the raw intake payload.
    """
    submission = await get_submission(db, submission_id)
    if submission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")

    result = await db.execute(
        select(ExtractedField)
        .where(ExtractedField.submission_id == submission_id)
        .order_by(ExtractedField.extracted_at)
    )
    fields = result.scalars().all()
    return [ExtractedFieldResponse.model_validate(f) for f in fields]


@router.get(
    "/{submission_id}/bundle",
    response_model=BundleMetaResponse,
    summary="Fetch the FHIR R4 bundle produced for a submission",
)
async def get_fhir_bundle(
    submission_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> BundleMetaResponse:
    """
    Return the FHIR R4 bundle for a completed submission.
    """
    result = await db.execute(
        select(FhirBundle)
        .where(FhirBundle.submission_id == submission_id)
        .order_by(FhirBundle.created_at.desc())
        .limit(1)
    )
    bundle_row = result.scalar_one_or_none()
    if bundle_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No bundle found for this submission — it may still be processing.",
        )

    try:
        bundle_json_str = await asyncio.to_thread(download_fhir_bundle, bundle_row.bundle_uri)
        bundle_doc = json.loads(bundle_json_str)
    except Exception as exc:
        logger.exception("Failed to fetch bundle from S3 uri=%s", bundle_row.bundle_uri)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not retrieve bundle from storage: {exc}",
        )

    return BundleMetaResponse(
        bundle_id=bundle_row.bundle_id,
        submission_id=bundle_row.submission_id,
        bundle_uri=bundle_row.bundle_uri,
        bundle_sha256=bundle_row.bundle_sha256,
        fhir_version=bundle_row.fhir_version,
        status=bundle_row.status.value,
        delivery_status=bundle_row.delivery_status.value,
        built_at=bundle_row.built_at,
        created_at=bundle_row.created_at,
        updated_at=bundle_row.updated_at,
        bundle=bundle_doc,
    )


@router.get(
    "/{submission_id}",
    response_model=SubmissionStatusResponse,
    summary="Get submission status",
)
async def get_submission_status(
    submission_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> SubmissionStatusResponse:
    submission = await get_submission(db, submission_id)
    if submission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")
    return SubmissionStatusResponse.model_validate(submission)
