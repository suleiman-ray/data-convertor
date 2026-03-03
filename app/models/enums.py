import enum


class SubmissionStatus(str, enum.Enum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    BUILDING_FHIR = "BUILDING_FHIR"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class ContentFormat(str, enum.Enum):
    JSON_FORM = "JSON_FORM"
    PDF_DIGITAL = "PDF_DIGITAL"
    PDF_SCANNED = "PDF_SCANNED"
    HL7 = "HL7"
    STRUCTURED_TEXT = "STRUCTURED_TEXT"


class ValueType(str, enum.Enum):
    QUANTITY = "quantity"
    BOOLEAN = "boolean"
    CODED = "coded"
    STRING = "string"
    DATE = "date"


class ConceptStatus(str, enum.Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class MappingMethod(str, enum.Enum):
    HUMAN = "human"
    AGENT = "agent"


class FieldStatus(str, enum.Enum):
    OK = "OK"
    FAILED = "FAILED"


class UnmappedStatus(str, enum.Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    MAPPING_CREATED = "MAPPING_CREATED"
    IGNORED = "IGNORED"


class CanonicalValueState(str, enum.Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    LOCKED = "LOCKED"
    NORMALIZATION_FAILED = "NORMALIZATION_FAILED"


class TemplateStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    DEPRECATED = "DEPRECATED"


class BundleStatus(str, enum.Enum):
    BUILDING = "BUILDING"
    BUILT = "BUILT"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    SENT = "SENT"
    DELIVERY_FAILED = "DELIVERY_FAILED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class DeliveryStatus(str, enum.Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class ProposalType(str, enum.Enum):
    CANONICAL_CONCEPT = "canonical_concept"
    FIELD_MAPPING = "field_mapping"
    FHIR_TEMPLATE = "fhir_template"


class ProposalStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
