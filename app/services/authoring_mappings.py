"""
Field-to-canonical mapping service.

  Every write that changes which canonical_id a stable_field_id resolves to
  MUST call invalidate_cached_mapping() for the affected key.

  prepare_mapping(db, data) — validates and adds a FieldToCanonical to the
    session WITHOUT committing.  Used by the proposal service so that the
    mapping and the proposal's APPROVED status can be committed atomically.
    Lower-level than create_mapping; callers are responsible for committing
    and calling invalidate_cached_mapping after the transaction succeeds.
  create_mapping(db, data) — standard entry-point for the authoring API.
    Calls prepare_mapping, commits, and invalidates the cache.
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import invalidate_cached_mapping
from app.models.canonical_concept import CanonicalConcept
from app.models.enums import ConceptStatus
from app.models.field_to_canonical import FieldToCanonical
from app.schemas.authoring import MappingCreate
from app.services.audit import audit_write

logger = logging.getLogger(__name__)


class MappingNotFound(Exception):
    """Raised when a mapping row does not exist — maps to HTTP 404."""


class MappingConflict(Exception):
    """Raised for true duplicate-state conflicts — maps to HTTP 409."""


class MappingReferenceError(Exception):
    """Raised when a referenced resource (e.g. canonical concept) does not exist — maps to HTTP 404."""


async def prepare_mapping(db: AsyncSession, data: MappingCreate) -> FieldToCanonical:
    """
    Validate and add a new FieldToCanonical to the session.

    Does NOT commit and does NOT invalidate the Redis cache.  Callers are
    responsible for both after the surrounding transaction commits.

    Raises:
        MappingReferenceError: if the canonical_id does not exist.
        MappingConflict: if an active mapping already exists for this key.
    """
    concept = await db.scalar(
        select(CanonicalConcept).where(CanonicalConcept.canonical_id == data.canonical_id)
    )
    if concept is None:
        raise MappingReferenceError(
            f"Canonical concept '{data.canonical_id}' does not exist"
        )
    if concept.status == ConceptStatus.DEPRECATED:
        raise MappingReferenceError(
            f"Canonical concept '{data.canonical_id}' is deprecated "
            f"and cannot be mapped to. Activate or replace the concept first."
        )

    existing = await db.scalar(
        select(FieldToCanonical).where(
            FieldToCanonical.intake_type_id == data.intake_type_id,
            FieldToCanonical.intake_type_version == data.intake_type_version,
            FieldToCanonical.stable_field_id == data.stable_field_id,
            FieldToCanonical.active.is_(True),
        )
    )
    if existing is not None:
        raise MappingConflict(
            f"An active mapping already exists for "
            f"({data.intake_type_id}, {data.intake_type_version}, {data.stable_field_id}). "
            f"Deactivate it first."
        )

    mapping = FieldToCanonical(
        intake_type_id=data.intake_type_id,
        intake_type_version=data.intake_type_version,
        stable_field_id=data.stable_field_id,
        canonical_id=data.canonical_id,
        mapping_method=data.mapping_method,
        approved_by=data.approved_by,
        active=True,
    )
    db.add(mapping)
    return mapping


async def create_mapping(db: AsyncSession, data: MappingCreate) -> FieldToCanonical:
    mapping = await prepare_mapping(db, data)
    audit_write(
        db,
        actor_id=data.approved_by,
        action="mapping.created",
        entity_type="field_to_canonical",
        entity_id=str(mapping.id),
        after_state={
            "intake_type_id": data.intake_type_id,
            "intake_type_version": data.intake_type_version,
            "stable_field_id": data.stable_field_id,
            "canonical_id": data.canonical_id,
            "mapping_method": data.mapping_method.value,
        },
    )
    await db.commit()
    await db.refresh(mapping)

    # Invalidate cache so the next resolution picks up the new mapping immediately.
    await invalidate_cached_mapping(
        data.intake_type_id, data.intake_type_version, data.stable_field_id
    )

    logger.info(
        "Created mapping id=%s %s/%s/%s → %s",
        mapping.id, data.intake_type_id, data.intake_type_version,
        data.stable_field_id, data.canonical_id,
    )
    return mapping


async def get_mapping(db: AsyncSession, mapping_id: uuid.UUID) -> FieldToCanonical:
    mapping = await db.scalar(
        select(FieldToCanonical).where(FieldToCanonical.id == mapping_id)
    )
    if mapping is None:
        raise MappingNotFound(f"Mapping '{mapping_id}' not found")
    return mapping


async def list_mappings(
    db: AsyncSession,
    intake_type_id: str | None = None,
    intake_type_version: str | None = None,
    stable_field_id: str | None = None,
    active_only: bool = True,
    limit: int = 100,
    offset: int = 0,
) -> list[FieldToCanonical]:
    q = select(FieldToCanonical)
    if intake_type_id:
        q = q.where(FieldToCanonical.intake_type_id == intake_type_id)
    if intake_type_version:
        q = q.where(FieldToCanonical.intake_type_version == intake_type_version)
    if stable_field_id:
        q = q.where(FieldToCanonical.stable_field_id == stable_field_id)
    if active_only:
        q = q.where(FieldToCanonical.active.is_(True))
    q = q.order_by(FieldToCanonical.created_at.desc()).limit(limit).offset(offset)
    result = await db.scalars(q)
    return list(result.all())


async def deactivate_mapping(
    db: AsyncSession, mapping_id: uuid.UUID, *, actor_id: str = "api"
) -> FieldToCanonical:
    mapping = await get_mapping(db, mapping_id)
    if not mapping.active:
        raise MappingConflict(f"Mapping '{mapping_id}' is already inactive")

    mapping.active = False
    mapping.deactivated_at = datetime.now(timezone.utc)
    audit_write(
        db,
        actor_id=actor_id,
        action="mapping.deactivated",
        entity_type="field_to_canonical",
        entity_id=str(mapping_id),
        before_state={"active": True},
        after_state={"active": False},
    )
    await db.commit()
    await db.refresh(mapping)

    # Invalidate cache — new submissions will get a cache miss and see no active mapping.
    await invalidate_cached_mapping(
        mapping.intake_type_id, mapping.intake_type_version, mapping.stable_field_id
    )

    logger.info("Deactivated mapping id=%s", mapping_id)
    return mapping
