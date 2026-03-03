import hashlib
import json

import pytest

from app.models.enums import FieldStatus
from app.services import stable_field_id as sfid
from app.services.extraction import parse_structured_text


"""
Rules under test:
  R1  Key: Value → key-value field
  R2  No colon, or colon with nothing after → section header
  R3  Line starting with '-' → bullet (takes precedence over R1)
  R4  raw_value surrounded by "…" → strip outer quotes
  R5  [REDACTED] stored as-is
  R6  Empty / whitespace-only line → skipped
  R7  Value containing comma → not split; single field
"""

def _make_payload(text: str) -> tuple[bytes, str]:
    """Build (raw_bytes, sha256_hex) for a STRUCTURED_TEXT submission."""
    raw = json.dumps({"text": text}).encode("utf-8")
    return raw, hashlib.sha256(raw).hexdigest()



def test_r1_key_value():
    raw, sha = _make_payload("Walked alone: 10 months")
    fields = parse_structured_text(raw, sha)
    assert len(fields) == 1
    f = fields[0]
    assert f.raw_label == "Walked alone"
    assert f.raw_value == "10 months"
    assert f.status == FieldStatus.OK



def test_r2_section_header_no_colon():
    """A line with no colon becomes the current section; the next K:V inherits it."""
    raw, sha = _make_payload("Developmental History\nWalked alone: 10 months")
    fields = parse_structured_text(raw, sha)
    assert len(fields) == 1
    assert fields[0].section_path == "Developmental History"



def test_r2_section_header_empty_colon():
    """A line whose value after the colon is empty is treated as a section header."""
    raw, sha = _make_payload("Delivery mode:\nWalked alone: 10 months")
    fields = parse_structured_text(raw, sha)
    assert len(fields) == 1
    assert fields[0].section_path == "Delivery mode"



def test_r3_bullet():
    """A '-' line emits one field with raw_label == current_section."""
    raw, sha = _make_payload("Symptoms\n- Morbid thoughts")
    fields = parse_structured_text(raw, sha)
    assert len(fields) == 1
    f = fields[0]
    assert f.raw_label == "Symptoms"
    assert f.raw_value == "Morbid thoughts"
    assert f.status == FieldStatus.OK


def test_r3_bullet_colon_precedence():
    """R3 takes precedence over R1: '- Key: Value' is a bullet, value is 'Key: Value'."""
    raw, sha = _make_payload("Symptoms\n- Key: Value")
    fields = parse_structured_text(raw, sha)
    assert len(fields) == 1
    f = fields[0]
    assert f.raw_label == "Symptoms"
    assert f.raw_value == "Key: Value"



def test_r4_quoted_value():
    """Surrounding double-quotes are stripped from the raw_value."""
    raw, sha = _make_payload('Gender: "test"')
    fields = parse_structured_text(raw, sha)
    assert len(fields) == 1
    assert fields[0].raw_value == "test"



def test_r5_redacted():
    """[REDACTED] is stored as-is with status OK — not dropped or transformed."""
    raw, sha = _make_payload("Notes: [REDACTED]")
    fields = parse_structured_text(raw, sha)
    assert len(fields) == 1
    assert fields[0].raw_value == "[REDACTED]"
    assert fields[0].status == FieldStatus.OK



def test_r6_empty_lines():
    """Blank lines before, between, and after content produce no extra fields."""
    raw, sha = _make_payload("\n\nWalked alone: 10 months\n\n")
    fields = parse_structured_text(raw, sha)
    assert len(fields) == 1



def test_r7_multi_value():
    """A comma-separated value is kept as a single field, not split."""
    raw, sha = _make_payload("Delivery: Unknown, Premature")
    fields = parse_structured_text(raw, sha)
    assert len(fields) == 1
    assert fields[0].raw_value == "Unknown, Premature"



def test_no_section_before_first_header():
    """Fields before the first section header have section_path == ''."""
    raw, sha = _make_payload("Walked alone: 10 months")
    fields = parse_structured_text(raw, sha)
    assert len(fields) == 1
    assert fields[0].section_path == ""



def test_sha256_mismatch():
    """A wrong expected_sha256 raises ValueError before any parsing occurs."""
    raw, _ = _make_payload("Walked alone: 10 months")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        parse_structured_text(raw, "deadbeef" * 8)



def test_missing_text_key():
    """A payload dict without a 'text' key raises ValueError mentioning 'text'."""
    raw = json.dumps({}).encode("utf-8")
    sha = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError, match="text"):
        parse_structured_text(raw, sha)



def test_r3_sfid_same_for_bullets_same_section():
    """
    Two bullets under the same section header produce identical stable_field_ids.

    This is intentional: both bullets map to the same repeating canonical
    concept; their instance_ids in extracted_fields distinguish them at the
    row level.
    """
    text = "Symptoms\n- Morbid thoughts\n- Anxiety"
    raw, sha = _make_payload(text)
    fields = parse_structured_text(raw, sha)
    assert len(fields) == 2
    assert fields[0].stable_field_id == fields[1].stable_field_id
    # Verify the sfid is what the frozen algorithm produces for (section, section)
    expected_sfid = sfid.compute("Symptoms", "Symptoms")
    assert fields[0].stable_field_id == expected_sfid
