import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import ContentFormat, SubmissionStatus


class SubmissionCreate(BaseModel):
    idempotency_key: str = Field(..., description="Caller-supplied unique key for deduplication")
    patient_id: str = Field(..., description="Patient identifier")
    intake_type_id: str = Field(..., description="Registered intake type (e.g. child-new-patient-history)")
    intake_type_version: str = Field(..., description="Version of the intake type (e.g. v1)")
    content_format: ContentFormat = Field(..., description="Format of the intake payload")
    payload: dict = Field(..., description="Raw intake content (JSON form fields)")
    submitted_by: str = Field(..., description="User or service submitting the intake")


class SubmissionResponse(BaseModel):
    submission_id: uuid.UUID
    idempotency_key: str
    patient_id: str
    intake_type_id: str
    intake_type_version: str
    content_format: ContentFormat
    status: SubmissionStatus
    raw_uri: str
    raw_sha256: str
    failure_reason: str | None
    received_at: datetime
    queued_at: datetime | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class SubmissionStatusResponse(BaseModel):
    submission_id: uuid.UUID
    status: SubmissionStatus
    failure_reason: str | None
    received_at: datetime
    queued_at: datetime | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class SubmissionSummary(BaseModel):
    """Lightweight view used in the list endpoint — omits S3 URIs and hashes."""

    submission_id: uuid.UUID
    patient_id: str
    intake_type_id: str
    intake_type_version: str
    content_format: ContentFormat
    status: SubmissionStatus
    failure_reason: str | None
    received_at: datetime
    queued_at: datetime | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class ExtractedFieldResponse(BaseModel):
    instance_id: uuid.UUID
    stable_field_id: str
    section_path: str
    raw_label: str
    raw_value: str | None
    provenance: dict[str, Any]
    extractor_version: str
    status: str
    failure_reason: str | None
    extracted_at: datetime

    model_config = {"from_attributes": True}


class BundleMetaResponse(BaseModel):
    bundle_id: uuid.UUID
    submission_id: uuid.UUID
    bundle_uri: str
    bundle_sha256: str
    fhir_version: str
    status: str
    delivery_status: str
    built_at: datetime | None
    created_at: datetime
    updated_at: datetime
    bundle: dict[str, Any] = Field(..., description="Parsed FHIR R4 Bundle document")

    model_config = {"from_attributes": True}
