import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import FHIR_VERSION
from app.models.enums import TemplateStatus
from app.models.fhir_template import FhirTemplate
from app.schemas.authoring import TemplateCreate
from app.services.audit import audit_write

logger = logging.getLogger(__name__)


class TemplateNotFound(Exception):
    pass


class TemplateConflict(Exception):
    pass


async def create_template(db: AsyncSession, data: TemplateCreate) -> FhirTemplate:
    template = FhirTemplate(
        intake_type_id=data.intake_type_id,
        intake_type_version=data.intake_type_version,
        fhir_version=FHIR_VERSION,
        template_json=data.template_json,
        placeholder_schema=data.placeholder_schema,
        template_version=data.template_version,
        status=TemplateStatus.DRAFT,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    logger.info(
        "Created FHIR template template_id=%s intake=%s/%s",
        template.template_id, data.intake_type_id, data.intake_type_version,
    )
    return template


async def get_template(db: AsyncSession, template_id: uuid.UUID) -> FhirTemplate:
    template = await db.scalar(
        select(FhirTemplate).where(FhirTemplate.template_id == template_id)
    )
    if template is None:
        raise TemplateNotFound(f"Template '{template_id}' not found")
    return template


async def get_approved_template(
    db: AsyncSession, intake_type_id: str, intake_type_version: str
) -> FhirTemplate | None:
    """Return the single approved template for a given intake type + version."""
    return await db.scalar(
        select(FhirTemplate).where(
            FhirTemplate.intake_type_id == intake_type_id,
            FhirTemplate.intake_type_version == intake_type_version,
            FhirTemplate.status == TemplateStatus.APPROVED,
        )
    )


async def list_templates(
    db: AsyncSession,
    intake_type_id: str | None = None,
    intake_type_version: str | None = None,
    status: TemplateStatus | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[FhirTemplate]:
    q = select(FhirTemplate)
    if intake_type_id:
        q = q.where(FhirTemplate.intake_type_id == intake_type_id)
    if intake_type_version:
        q = q.where(FhirTemplate.intake_type_version == intake_type_version)
    if status:
        q = q.where(FhirTemplate.status == status)
    q = q.order_by(FhirTemplate.created_at.desc()).limit(limit).offset(offset)
    result = await db.scalars(q)
    return list(result.all())


async def approve_template(
    db: AsyncSession, template_id: uuid.UUID, approved_by: str
) -> FhirTemplate:
    template = await get_template(db, template_id)

    if template.status == TemplateStatus.APPROVED:
        raise TemplateConflict(f"Template '{template_id}' is already approved")
    if template.status == TemplateStatus.DEPRECATED:
        raise TemplateConflict(f"Template '{template_id}' is deprecated and cannot be approved")

    # Enforce at most one APPROVED template per (intake_type_id, intake_type_version).
    # get_approved_template() is non-deterministic when multiple rows match, so we
    # block the second approval here rather than relying on the DB partial index alone.
    existing = await get_approved_template(
        db, template.intake_type_id, template.intake_type_version
    )
    if existing is not None and existing.template_id != template_id:
        raise TemplateConflict(
            f"An approved template already exists for "
            f"({template.intake_type_id}, {template.intake_type_version}). "
            f"Deprecate template '{existing.template_id}' before approving a new one."
        )

    before = {"status": template.status.value}
    template.status = TemplateStatus.APPROVED
    template.approved_by = approved_by
    template.approved_at = datetime.now(timezone.utc)
    audit_write(
        db,
        actor_id=approved_by,
        action="template.approved",
        entity_type="fhir_template",
        entity_id=str(template_id),
        before_state=before,
        after_state={"status": TemplateStatus.APPROVED.value, "approved_by": approved_by},
    )
    await db.commit()
    await db.refresh(template)
    logger.info("Approved FHIR template template_id=%s by=%s", template_id, approved_by)
    return template


async def deprecate_template(
    db: AsyncSession, template_id: uuid.UUID, *, actor_id: str = "api"
) -> FhirTemplate:
    template = await get_template(db, template_id)
    if template.status == TemplateStatus.DEPRECATED:
        raise TemplateConflict(f"Template '{template_id}' is already deprecated")

    before = {"status": template.status.value}
    template.status = TemplateStatus.DEPRECATED
    audit_write(
        db,
        actor_id=actor_id,
        action="template.deprecated",
        entity_type="fhir_template",
        entity_id=str(template_id),
        before_state=before,
        after_state={"status": TemplateStatus.DEPRECATED.value},
    )
    await db.commit()
    await db.refresh(template)
    logger.info("Deprecated FHIR template template_id=%s", template_id)
    return template
