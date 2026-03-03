import json
import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.models.enums import (
    ConceptStatus,
    MappingMethod,
    ProposalStatus,
    ProposalType,
    TemplateStatus,
    ValueType,
)

_PLACEHOLDER_RE = re.compile(r"\{\{canonical:([^}]+)\}\}")



class ConceptCreate(BaseModel):
    canonical_id: str = Field(..., min_length=1, examples=["dev.walked_alone_age"])
    description: str = Field(..., min_length=1)
    value_type: ValueType
    unit: str | None = None
    value_domain: dict | None = None
    fhir_data_type: str = Field(..., min_length=1, examples=["Quantity", "boolean", "CodeableConcept"])
    code_system: str | None = None
    version: str = "1.0"


class ConceptUpdate(BaseModel):
    description: str | None = None
    status: ConceptStatus | None = None
    unit: str | None = None
    value_domain: dict | None = None
    code_system: str | None = None


class ConceptResponse(BaseModel):
    canonical_id: str
    description: str
    value_type: ValueType
    unit: str | None
    value_domain: dict | None
    fhir_data_type: str
    code_system: str | None
    version: str
    status: ConceptStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}



class MappingCreate(BaseModel):
    intake_type_id: str = Field(..., min_length=1, examples=["child-new-patient-history"])
    intake_type_version: str = Field(..., min_length=1, examples=["v1"])
    stable_field_id: str = Field(..., min_length=1, examples=["sfid_d188da9b"])
    canonical_id: str = Field(..., min_length=1, examples=["dev.walked_alone_age"])
    mapping_method: MappingMethod = MappingMethod.HUMAN
    approved_by: str = Field(..., min_length=1, examples=["dr.smith", "agent-v1"])


class MappingResponse(BaseModel):
    id: uuid.UUID
    intake_type_id: str
    intake_type_version: str
    stable_field_id: str
    canonical_id: str
    mapping_method: MappingMethod
    approved_by: str | None
    active: bool
    created_at: datetime
    deactivated_at: datetime | None

    model_config = {"from_attributes": True}



class TemplateCreate(BaseModel):
    intake_type_id: str = Field(..., min_length=1)
    intake_type_version: str = Field(..., min_length=1)
    template_json: dict = Field(
        ...,
        description="FHIR R4 bundle/resource template with {{canonical:<id>}} placeholders",
    )
    placeholder_schema: dict = Field(
        default_factory=dict,
        description='Maps canonical_id → {"required": bool, "fhir_path": str}',
    )
    template_version: str = "1.0"

    @model_validator(mode="after")
    def validate_placeholder_consistency(self) -> "TemplateCreate":
        """
        Verify that every {{canonical:<id>}} in template_json is declared in
        placeholder_schema and that every placeholder_schema key has a
        corresponding placeholder in the template.

        Only enforced when placeholder_schema is non-empty so that templates
        submitted without a schema (e.g. early drafts) are still accepted.
        """
        if not self.placeholder_schema:
            return self

        template_str = json.dumps(self.template_json)
        found_in_template: set[str] = set(_PLACEHOLDER_RE.findall(template_str))
        declared_in_schema: set[str] = set(self.placeholder_schema.keys())

        undeclared = found_in_template - declared_in_schema
        if undeclared:
            raise ValueError(
                f"Template contains {{{{canonical:<id>}}}} placeholders not declared in "
                f"placeholder_schema: {sorted(undeclared)}"
            )

        missing_from_template = declared_in_schema - found_in_template
        if missing_from_template:
            raise ValueError(
                f"placeholder_schema declares canonical IDs not present in template_json: "
                f"{sorted(missing_from_template)}"
            )

        return self


class TemplateApprove(BaseModel):
    approved_by: str = Field(..., min_length=1)


class TemplateResponse(BaseModel):
    template_id: uuid.UUID
    intake_type_id: str
    intake_type_version: str
    fhir_version: str
    template_json: dict
    placeholder_schema: dict
    template_version: str
    status: TemplateStatus
    approved_by: str | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}



_FIELD_MAPPING_REQUIRED_KEYS = frozenset(
    {"stable_field_id", "canonical_id", "intake_type_id", "intake_type_version"}
)


class ProposalCreate(BaseModel):
    proposed_by: str = Field(..., min_length=1, examples=["agent-v1", "dr.smith"])
    proposal_type: ProposalType
    payload: dict = Field(
        ...,
        description=(
            "For FIELD_MAPPING proposals the payload must contain: "
            "stable_field_id, canonical_id, intake_type_id, intake_type_version, "
            "and optionally mapping_method."
        ),
    )
    confidence_score: float | None = Field(
        None, ge=0.0, le=1.0, description="AI confidence score (0–1); omit for human proposals."
    )

    @model_validator(mode="after")
    def validate_field_mapping_payload(self) -> "ProposalCreate":
        if self.proposal_type == ProposalType.FIELD_MAPPING:
            missing = _FIELD_MAPPING_REQUIRED_KEYS - self.payload.keys()
            if missing:
                raise ValueError(
                    f"FIELD_MAPPING proposals require these payload keys: "
                    f"{sorted(missing)}"
                )
        return self


class ProposalApprove(BaseModel):
    approved_by: str = Field(..., min_length=1, examples=["dr.jones"])


class ProposalReject(BaseModel):
    rejected_by: str = Field(..., min_length=1)
    rejection_reason: str = Field(..., min_length=1)


class ProposalResponse(BaseModel):
    proposal_id: uuid.UUID
    proposed_by: str
    proposal_type: ProposalType
    payload: dict
    confidence_score: float | None
    status: ProposalStatus
    clinical_approved_by: str | None
    clinical_approved_at: datetime | None
    product_approved_by: str | None
    product_approved_at: datetime | None
    rejection_reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
