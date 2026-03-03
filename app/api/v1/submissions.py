import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.enums import SubmissionStatus
from app.schemas.submission import (
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
