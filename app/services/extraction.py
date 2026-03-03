"""
Extraction service — parsers for supported content formats.

JSON_FORM structure assumed:
  {
    "<section_path>": {
      "<raw_label>": "<raw_value>",
      ...
    },
    ...
  }

STRUCTURED_TEXT format (line-oriented plain text):
  Payload is a JSON object {"text": "<plain-text document>"}.
  Lines are processed with rules R1–R7 (see parse_structured_text docstring).

Shared rules:
  - Best-effort: fields that fail parsing are written with status=FAILED.
    The submission continues with the successfully extracted fields.
  - stable_field_id is computed using the frozen algorithm from stable_field_id.py.
  - extractor_version is pinned per implementation — bump when logic changes.
"""

import hashlib
import json
import logging
from dataclasses import dataclass

from app.services import stable_field_id as sfid
from app.models.enums import FieldStatus

logger = logging.getLogger(__name__)

EXTRACTOR_VERSION = "json-form-v1.0.0"
STRUCTURED_TEXT_EXTRACTOR_VERSION = "structured-text-v1.0.0"


@dataclass
class ExtractedFieldData:
    raw_label: str
    raw_value: str | None
    section_path: str
    provenance: dict
    stable_field_id: str
    extractor_version: str
    status: FieldStatus
    failure_reason: str | None


def parse_json_form(raw_bytes: bytes, expected_sha256: str) -> list[ExtractedFieldData]:
    """
    Parse a JSON_FORM artifact.

    Verifies SHA-256 integrity before parsing.
    Returns a list of ExtractedFieldData — one per question/answer pair.
    Fields that fail individually are returned with status=FAILED.
    """
    # ── Integrity check ───────────────────────────────────────────────────────
    actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError(
            f"SHA-256 mismatch: expected {expected_sha256}, got {actual_sha256}"
        )

    try:
        form: dict = json.loads(raw_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Invalid JSON payload: {exc}") from exc

    if not isinstance(form, dict):
        raise ValueError("JSON_FORM payload must be a JSON object at the top level")

    results: list[ExtractedFieldData] = []

    for section_path, section_content in form.items():
        if not isinstance(section_content, dict):
            results.append(
                ExtractedFieldData(
                    raw_label=str(section_path),
                    raw_value=None,
                    section_path=str(section_path),
                    provenance={"section": section_path, "question_index": 0},
                    stable_field_id=sfid.compute(str(section_path), str(section_path)),
                    extractor_version=EXTRACTOR_VERSION,
                    status=FieldStatus.FAILED,
                    failure_reason=f"Section value is not an object (got {type(section_content).__name__})",
                )
            )
            continue

        for q_index, (raw_label, raw_value) in enumerate(section_content.items()):
            try:
                if isinstance(raw_value, (dict, list)):
                    raise TypeError(
                        f"Field value must be a scalar, got {type(raw_value).__name__}"
                    )

                normalized_value = str(raw_value) if raw_value is not None else None
                stable_id = sfid.compute(section_path, raw_label)

                results.append(
                    ExtractedFieldData(
                        raw_label=raw_label,
                        raw_value=normalized_value,
                        section_path=section_path,
                        provenance={
                            "section": section_path,
                            "question_index": q_index,
                        },
                        stable_field_id=stable_id,
                        extractor_version=EXTRACTOR_VERSION,
                        status=FieldStatus.OK,
                        failure_reason=None,
                    )
                )

            except Exception as exc:
                logger.warning(
                    "Field extraction failed section=%r label=%r error=%s",
                    section_path, raw_label, exc,
                )
                results.append(
                    ExtractedFieldData(
                        raw_label=raw_label,
                        raw_value=None,
                        section_path=section_path,
                        provenance={
                            "section": section_path,
                            "question_index": q_index,
                        },
                        stable_field_id=sfid.compute(section_path, raw_label),
                        extractor_version=EXTRACTOR_VERSION,
                        status=FieldStatus.FAILED,
                        failure_reason=str(exc),
                    )
                )

    logger.info(
        "Extraction complete: total=%d ok=%d failed=%d",
        len(results),
        sum(1 for r in results if r.status == FieldStatus.OK),
        sum(1 for r in results if r.status == FieldStatus.FAILED),
    )
    return results


def _strip_quotes(value: str) -> str:
    """Apply Rule R4: strip surrounding double-quotes from a raw value."""
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value


def parse_structured_text(raw_bytes: bytes, expected_sha256: str) -> list[ExtractedFieldData]:
    """
    Parse a STRUCTURED_TEXT artifact.

    The payload is a JSON object with a single "text" key whose value is a
    UTF-8 plain-text document.  Lines are processed in order with these rules
    (applied after stripping leading/trailing whitespace from each line):

      R6  Empty or whitespace-only line       → skip, no field emitted
      R3  Line starting with '-'              → bullet; raw_label = current_section,
                                                raw_value = text after the dash.
                                                Takes precedence over R1.
      R2  No colon in line, or colon with     → section header; updates
          nothing after it                      current_section, no field emitted
      R1  Key: Value (non-empty value)        → key-value field
      R4  raw_value surrounded by "…"        → strip the outer quotes
      R5  raw_value == "[REDACTED]"           → stored as-is, status OK
      R7  Comma in value (e.g. "Unknown, …") → not split; single field

    Raises ValueError for SHA-256 mismatch or a missing/non-string "text" key.
    Returns a list of ExtractedFieldData, one per parsed line.
    """
    actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError(
            f"SHA-256 mismatch: expected {expected_sha256}, got {actual_sha256}"
        )

    try:
        envelope: dict = json.loads(raw_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Invalid JSON payload: {exc}") from exc

    if "text" not in envelope:
        raise ValueError(
            "STRUCTURED_TEXT payload missing required 'text' key. "
            "Submit as: {\"text\": \"<plain-text document>\"}"
        )
    text = envelope["text"]
    if not isinstance(text, str):
        raise ValueError(
            f"STRUCTURED_TEXT payload 'text' must be a string, "
            f"got {type(text).__name__}"
        )

    results: list[ExtractedFieldData] = []
    current_section: str = ""

    for line_number, raw_line in enumerate(text.split("\n"), start=1):
        line = raw_line.strip()

        if not line:
            continue

        try:
            if line.startswith("-"):
                raw_value = _strip_quotes(line[1:].strip())
                results.append(ExtractedFieldData(
                    raw_label=current_section,
                    raw_value=raw_value,
                    section_path=current_section,
                    provenance={"section": current_section, "line_number": line_number},
                    stable_field_id=sfid.compute(current_section, current_section),
                    extractor_version=STRUCTURED_TEXT_EXTRACTOR_VERSION,
                    status=FieldStatus.OK,
                    failure_reason=None,
                ))
                continue

            if ":" not in line:
                current_section = line
                continue

            key, _, value_part = line.partition(":")
            value = value_part.strip()

            if not value:
                current_section = key.strip()
                continue

            raw_label = key.strip()
            raw_value = _strip_quotes(value)
            results.append(ExtractedFieldData(
                raw_label=raw_label,
                raw_value=raw_value,
                section_path=current_section,
                provenance={"section": current_section, "line_number": line_number},
                stable_field_id=sfid.compute(current_section, raw_label),
                extractor_version=STRUCTURED_TEXT_EXTRACTOR_VERSION,
                status=FieldStatus.OK,
                failure_reason=None,
            ))

        except Exception as exc:
            logger.warning(
                "Structured text: line %d parse error: %s — line=%r",
                line_number, exc, line,
            )
            results.append(ExtractedFieldData(
                raw_label=line,
                raw_value=None,
                section_path=current_section,
                provenance={"section": current_section, "line_number": line_number},
                stable_field_id=sfid.compute(current_section, line),
                extractor_version=STRUCTURED_TEXT_EXTRACTOR_VERSION,
                status=FieldStatus.FAILED,
                failure_reason=str(exc),
            ))

    logger.info(
        "Structured text extraction complete: total=%d ok=%d failed=%d",
        len(results),
        sum(1 for r in results if r.status == FieldStatus.OK),
        sum(1 for r in results if r.status == FieldStatus.FAILED),
    )
    return results
