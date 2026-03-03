import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.canonical_concept import CanonicalConcept
from app.models.enums import ConceptStatus
from app.schemas.authoring import ConceptCreate, ConceptUpdate

logger = logging.getLogger(__name__)


class ConceptAlreadyExists(Exception):
    pass


class ConceptNotFound(Exception):
    pass


async def create_concept(db: AsyncSession, data: ConceptCreate) -> CanonicalConcept:
    existing = await db.scalar(
        select(CanonicalConcept).where(CanonicalConcept.canonical_id == data.canonical_id)
    )
    if existing is not None:
        raise ConceptAlreadyExists(f"Canonical concept '{data.canonical_id}' already exists")

    concept = CanonicalConcept(
        canonical_id=data.canonical_id,
        description=data.description,
        value_type=data.value_type,
        unit=data.unit,
        value_domain=data.value_domain,
        fhir_data_type=data.fhir_data_type,
        code_system=data.code_system,
        version=data.version,
        status=ConceptStatus.ACTIVE,
    )
    db.add(concept)
    await db.commit()
    await db.refresh(concept)
    logger.info("Created canonical concept canonical_id=%s", concept.canonical_id)
    return concept


async def get_concept(db: AsyncSession, canonical_id: str) -> CanonicalConcept:
    concept = await db.scalar(
        select(CanonicalConcept).where(CanonicalConcept.canonical_id == canonical_id)
    )
    if concept is None:
        raise ConceptNotFound(f"Canonical concept '{canonical_id}' not found")
    return concept


async def list_concepts(
    db: AsyncSession,
    status: ConceptStatus | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[CanonicalConcept]:
    q = select(CanonicalConcept)
    if status is not None:
        q = q.where(CanonicalConcept.status == status)
    q = q.order_by(CanonicalConcept.canonical_id).limit(limit).offset(offset)
    result = await db.scalars(q)
    return list(result.all())


async def update_concept(
    db: AsyncSession, canonical_id: str, data: ConceptUpdate
) -> CanonicalConcept:
    concept = await get_concept(db, canonical_id)

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(concept, field, value)

    await db.commit()
    await db.refresh(concept)
    logger.info("Updated canonical concept canonical_id=%s", canonical_id)
    return concept
