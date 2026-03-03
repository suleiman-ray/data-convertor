import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_cached_mapping, set_cached_mapping
from app.models.canonical_concept import CanonicalConcept
from app.models.enums import ValueType
from app.models.field_to_canonical import FieldToCanonical

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConceptData:
    """
    Immutable value object carrying the fields the normalizer and FHIR builder
    need.  Using a dataclass instead of the ORM model prevents callers from
    mistakenly assuming this is a live session-tracked entity.
    """
    canonical_id: str
    value_type: ValueType          # always a ValueType enum instance, not a raw string
    fhir_data_type: str
    unit: str | None
    value_domain: dict | None
    code_system: str | None
    description: str
    version: str


class MappingNotFound(Exception):
    """Raised when no active mapping exists for a stable_field_id."""


async def resolve(
    db: AsyncSession,
    intake_type_id: str,
    intake_type_version: str,
    stable_field_id: str,
) -> ConceptData:
    """
    Return the ConceptData for (intake_type, version, stable_field_id).
    Raises MappingNotFound if no active mapping exists — caller must write
    an unmapped_fields record and flip the submission to NEEDS_REVIEW.
    """
    # 1. Redis cache
    cached = await get_cached_mapping(intake_type_id, intake_type_version, stable_field_id)
    if cached is not None:
        logger.debug(
            "resolver cache HIT %s/%s/%s → %s",
            intake_type_id, intake_type_version, stable_field_id, cached["canonical_id"],
        )
        return _from_dict(cached)

    # 2. DB fallback — single JOIN
    row = await db.execute(
        select(FieldToCanonical, CanonicalConcept)
        .join(CanonicalConcept, FieldToCanonical.canonical_id == CanonicalConcept.canonical_id)
        .where(
            FieldToCanonical.intake_type_id == intake_type_id,
            FieldToCanonical.intake_type_version == intake_type_version,
            FieldToCanonical.stable_field_id == stable_field_id,
            FieldToCanonical.active.is_(True),
        )
    )
    result = row.first()

    if result is None:
        logger.warning(
            "resolver MISS (unmapped) %s/%s/%s",
            intake_type_id, intake_type_version, stable_field_id,
        )
        raise MappingNotFound(
            f"No active mapping for ({intake_type_id}, {intake_type_version}, {stable_field_id})"
        )

    _mapping, concept = result
    logger.debug(
        "resolver DB HIT %s/%s/%s → %s",
        intake_type_id, intake_type_version, stable_field_id, concept.canonical_id,
    )

    # 3. Populate Redis so next call is a cache hit
    payload = _to_dict(concept)
    await set_cached_mapping(intake_type_id, intake_type_version, stable_field_id, payload)

    return _from_dict(payload)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_dict(concept: CanonicalConcept) -> dict:
    """Serialize a live ORM object to a JSON-safe dict for Redis storage."""
    return {
        "canonical_id": concept.canonical_id,
        # Store the .value (a plain string) so JSON round-trips cleanly
        "value_type": concept.value_type.value if isinstance(concept.value_type, ValueType) else concept.value_type,
        "fhir_data_type": concept.fhir_data_type,
        "unit": concept.unit,
        "value_domain": concept.value_domain,
        "code_system": concept.code_system,
        "description": concept.description,
        "version": concept.version,
    }


def _from_dict(d: dict) -> ConceptData:
    """
    Deserialise a dict (from Redis or freshly serialised) into a ConceptData.
    value_type is always returned as a ValueType enum instance so callers get
    type-safe comparisons rather than raw string equality.
    """
    return ConceptData(
        canonical_id=d["canonical_id"],
        value_type=ValueType(d["value_type"]),   # str → enum, safe via str-enum equality
        fhir_data_type=d["fhir_data_type"],
        unit=d.get("unit"),
        value_domain=d.get("value_domain"),
        code_system=d.get("code_system"),
        description=d.get("description", ""),
        version=d.get("version", "1.0"),
    )
