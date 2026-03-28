import uuid
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.enums import ConceptStatus, ProposalStatus, ProposalType, TemplateStatus
from app.schemas.authoring import (
    ConceptCreate, ConceptResponse, ConceptUpdate,
    FieldInventoryItem,
    MappingCreate, MappingResponse,
    ProposalApprove, ProposalCreate, ProposalReject, ProposalResponse,
    TemplateApprove, TemplateCreate, TemplateResponse,
)
from app.services.authoring_concepts import (
    ConceptAlreadyExists, ConceptNotFound,
    create_concept, get_concept, list_concepts, update_concept,
)
from app.services.authoring_mappings import (
    MappingConflict, MappingNotFound, MappingReferenceError,
    create_mapping, deactivate_mapping, get_mapping, list_mappings,
)
from app.services.authoring_proposals import (
    ProposalConflict, ProposalNotFound,
    clinical_approve, create_proposal, get_proposal, list_proposals,
    product_approve, reject_proposal,
)
from app.services.authoring_templates import (
    TemplateConflict, TemplateNotFound,
    approve_template, create_template, deprecate_template,
    get_template, list_templates,
)
from app.services.field_inventory import list_field_inventory
from app.services.requeue import requeue_needs_review_submissions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/authoring", tags=["Authoring"])


class RequeueResponse(BaseModel):
    requeued: int


@router.post("/concepts", response_model=ConceptResponse, status_code=status.HTTP_201_CREATED)
async def create_concept_endpoint(
    body: ConceptCreate,
    db: AsyncSession = Depends(get_db),
) -> ConceptResponse:
    try:
        concept = await create_concept(db, body)
        return ConceptResponse.model_validate(concept)
    except ConceptAlreadyExists as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("/concepts", response_model=list[ConceptResponse])
async def list_concepts_endpoint(
    concept_status: ConceptStatus | None = Query(None, alias="status"),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
) -> list[ConceptResponse]:
    concepts = await list_concepts(db, status=concept_status, limit=limit, offset=offset)
    return [ConceptResponse.model_validate(c) for c in concepts]


@router.get("/concepts/{canonical_id}", response_model=ConceptResponse)
async def get_concept_endpoint(
    canonical_id: str,
    db: AsyncSession = Depends(get_db),
) -> ConceptResponse:
    try:
        return ConceptResponse.model_validate(await get_concept(db, canonical_id))
    except ConceptNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.patch("/concepts/{canonical_id}", response_model=ConceptResponse)
async def update_concept_endpoint(
    canonical_id: str,
    body: ConceptUpdate,
    db: AsyncSession = Depends(get_db),
) -> ConceptResponse:
    try:
        return ConceptResponse.model_validate(await update_concept(db, canonical_id, body))
    except ConceptNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/mappings", response_model=MappingResponse, status_code=status.HTTP_201_CREATED)
async def create_mapping_endpoint(
    body: MappingCreate,
    db: AsyncSession = Depends(get_db),
) -> MappingResponse:
    try:
        mapping = await create_mapping(db, body)
        return MappingResponse.model_validate(mapping)
    except MappingReferenceError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except MappingConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("/mappings", response_model=list[MappingResponse])
async def list_mappings_endpoint(
    intake_type_id: str | None = Query(None),
    intake_type_version: str | None = Query(None),
    stable_field_id: str | None = Query(None),
    active_only: bool = Query(True),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
) -> list[MappingResponse]:
    mappings = await list_mappings(
        db,
        intake_type_id=intake_type_id,
        intake_type_version=intake_type_version,
        stable_field_id=stable_field_id,
        active_only=active_only,
        limit=limit,
        offset=offset,
    )
    return [MappingResponse.model_validate(m) for m in mappings]


@router.get(
    "/field-inventory",
    response_model=list[FieldInventoryItem],
    summary="Distinct extracted field triples (mapping discovery)",
)
async def field_inventory_endpoint(
    intake_type_id: str | None = Query(None),
    intake_type_version: str | None = Query(None),
    unmapped_only: bool = Query(
        False,
        description="If true, return only triples with no active field_to_canonical row",
    ),
    db: AsyncSession = Depends(get_db),
) -> list[FieldInventoryItem]:
    """
    Return distinct **(intake_type_id, intake_type_version, stable_field_id)** values
    from **OK** `extracted_fields` joined to submissions.

    Use this for mapping agents and operators
    """
    rows = await list_field_inventory(
        db,
        intake_type_id=intake_type_id,
        intake_type_version=intake_type_version,
        unmapped_only=unmapped_only,
    )
    return [
        FieldInventoryItem(
            intake_type_id=a,
            intake_type_version=b,
            stable_field_id=c,
        )
        for a, b, c in rows
    ]


@router.get("/mappings/{mapping_id}", response_model=MappingResponse)
async def get_mapping_endpoint(
    mapping_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> MappingResponse:
    try:
        return MappingResponse.model_validate(await get_mapping(db, mapping_id))
    except MappingNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/mappings/{mapping_id}/requeue", response_model=RequeueResponse)
async def requeue_mapping_endpoint(
    mapping_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> RequeueResponse:
    """
    Re-enqueue all NEEDS_REVIEW submissions blocked on the given mapping's field.
    Call this after creating a mapping for a previously unmapped stable_field_id.
    """
    try:
        mapping = await get_mapping(db, mapping_id)
    except MappingNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    count = await requeue_needs_review_submissions(
        intake_type_id=mapping.intake_type_id,
        intake_type_version=mapping.intake_type_version,
        stable_field_id=mapping.stable_field_id,
    )
    logger.info("requeue: mapping_id=%s re-enqueued %d submission(s)", mapping_id, count)
    return RequeueResponse(requeued=count)


@router.delete("/mappings/{mapping_id}", response_model=MappingResponse)
async def deactivate_mapping_endpoint(
    mapping_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    x_actor_id: str | None = Header(None, alias="X-Actor-Id"),
) -> MappingResponse:
    actor_id = (x_actor_id or "").strip() or "api"
    try:
        mapping = await deactivate_mapping(db, mapping_id, actor_id=actor_id)
        return MappingResponse.model_validate(mapping)
    except MappingNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except MappingConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))



@router.post("/templates", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template_endpoint(
    body: TemplateCreate,
    db: AsyncSession = Depends(get_db),
) -> TemplateResponse:
    template = await create_template(db, body)
    return TemplateResponse.model_validate(template)


@router.get("/templates", response_model=list[TemplateResponse])
async def list_templates_endpoint(
    intake_type_id: str | None = Query(None),
    intake_type_version: str | None = Query(None),
    template_status: TemplateStatus | None = Query(None, alias="status"),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
) -> list[TemplateResponse]:
    templates = await list_templates(
        db,
        intake_type_id=intake_type_id,
        intake_type_version=intake_type_version,
        status=template_status,
        limit=limit,
        offset=offset,
    )
    return [TemplateResponse.model_validate(t) for t in templates]


@router.get("/templates/{template_id}", response_model=TemplateResponse)
async def get_template_endpoint(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> TemplateResponse:
    try:
        return TemplateResponse.model_validate(await get_template(db, template_id))
    except TemplateNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/templates/{template_id}/approve", response_model=TemplateResponse)
async def approve_template_endpoint(
    template_id: uuid.UUID,
    body: TemplateApprove,
    db: AsyncSession = Depends(get_db),
) -> TemplateResponse:
    try:
        return TemplateResponse.model_validate(
            await approve_template(db, template_id, body.approved_by)
        )
    except TemplateNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except TemplateConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post("/templates/{template_id}/deprecate", response_model=TemplateResponse)
async def deprecate_template_endpoint(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    x_actor_id: str | None = Header(None, alias="X-Actor-Id"),
) -> TemplateResponse:
    actor_id = (x_actor_id or "").strip() or "api"
    try:
        return TemplateResponse.model_validate(
            await deprecate_template(db, template_id, actor_id=actor_id)
        )
    except TemplateNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except TemplateConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))



@router.post("/proposals", response_model=ProposalResponse, status_code=status.HTTP_201_CREATED)
async def create_proposal_endpoint(
    body: ProposalCreate,
    db: AsyncSession = Depends(get_db),
) -> ProposalResponse:
    """Create an AI-generated or human mapping proposal."""
    proposal = await create_proposal(db, body)
    return ProposalResponse.model_validate(proposal)


@router.get("/proposals", response_model=list[ProposalResponse])
async def list_proposals_endpoint(
    proposal_status: ProposalStatus | None = Query(None, alias="status"),
    proposal_type: ProposalType | None = Query(None, alias="type"),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
) -> list[ProposalResponse]:
    proposals = await list_proposals(
        db,
        status=proposal_status,
        proposal_type=proposal_type,
        limit=limit,
        offset=offset,
    )
    return [ProposalResponse.model_validate(p) for p in proposals]


@router.get("/proposals/{proposal_id}", response_model=ProposalResponse)
async def get_proposal_endpoint(
    proposal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ProposalResponse:
    try:
        return ProposalResponse.model_validate(await get_proposal(db, proposal_id))
    except ProposalNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/proposals/{proposal_id}/approve", response_model=ProposalResponse)
async def clinical_approve_endpoint(
    proposal_id: uuid.UUID,
    body: ProposalApprove,
    db: AsyncSession = Depends(get_db),
) -> ProposalResponse:
    """
    Clinical sign-off (first approval).
    Sets clinical_approved_by; does not yet promote the proposal to APPROVED.
    """
    try:
        return ProposalResponse.model_validate(
            await clinical_approve(db, proposal_id, body.approved_by)
        )
    except ProposalNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ProposalConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post("/proposals/{proposal_id}/second-approve", response_model=ProposalResponse)
async def product_approve_endpoint(
    proposal_id: uuid.UUID,
    body: ProposalApprove,
    db: AsyncSession = Depends(get_db),
) -> ProposalResponse:
    """
    Product sign-off (second approval, must be a different person from clinical approver).

    On success the proposal is promoted to APPROVED.  For FIELD_MAPPING proposals the
    corresponding mapping is created automatically and any blocked NEEDS_REVIEW
    submissions are re-queued.
    """
    try:
        return ProposalResponse.model_validate(
            await product_approve(db, proposal_id, body.approved_by)
        )
    except ProposalNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ProposalConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post("/proposals/{proposal_id}/reject", response_model=ProposalResponse)
async def reject_proposal_endpoint(
    proposal_id: uuid.UUID,
    body: ProposalReject,
    db: AsyncSession = Depends(get_db),
) -> ProposalResponse:
    try:
        return ProposalResponse.model_validate(
            await reject_proposal(db, proposal_id, body)
        )
    except ProposalNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ProposalConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
