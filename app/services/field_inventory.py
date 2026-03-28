"""
Distinct (intake_type_id, intake_type_version, stable_field_id) from extraction.

Used by mapping agents and operators to discover which field triples exist in the
database and which still lack an active field_to_canonical row.
"""

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import FieldStatus
from app.models.extracted_field import ExtractedField
from app.models.field_to_canonical import FieldToCanonical
from app.models.intake_submission import IntakeSubmission


async def list_field_inventory(
    db: AsyncSession,
    *,
    intake_type_id: str | None = None,
    intake_type_version: str | None = None,
    unmapped_only: bool = False,
) -> list[tuple[str, str, str]]:
    """
    Return distinct triples from extracted_fields joined to intake_submissions.

    Only rows with FieldStatus.OK are included (failed extractions are omitted).

    When unmapped_only=True, keep triples that have **no** active FieldToCanonical
    row for the same (intake_type_id, intake_type_version, stable_field_id).
    """
    stmt = (
        select(
            IntakeSubmission.intake_type_id,
            IntakeSubmission.intake_type_version,
            ExtractedField.stable_field_id,
        )
        .distinct()
        .select_from(ExtractedField)
        .join(
            IntakeSubmission,
            ExtractedField.submission_id == IntakeSubmission.submission_id,
        )
        .where(ExtractedField.status == FieldStatus.OK)
    )

    if intake_type_id is not None:
        stmt = stmt.where(IntakeSubmission.intake_type_id == intake_type_id)
    if intake_type_version is not None:
        stmt = stmt.where(IntakeSubmission.intake_type_version == intake_type_version)

    if unmapped_only:
        stmt = stmt.outerjoin(
            FieldToCanonical,
            and_(
                FieldToCanonical.intake_type_id == IntakeSubmission.intake_type_id,
                FieldToCanonical.intake_type_version
                == IntakeSubmission.intake_type_version,
                FieldToCanonical.stable_field_id == ExtractedField.stable_field_id,
                FieldToCanonical.active.is_(True),
            ),
        ).where(FieldToCanonical.id.is_(None))

    result = await db.execute(stmt.order_by(
        IntakeSubmission.intake_type_id,
        IntakeSubmission.intake_type_version,
        ExtractedField.stable_field_id,
    ))
    return [(row[0], row[1], row[2]) for row in result.all()]
