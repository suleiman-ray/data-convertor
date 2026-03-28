"""Unit tests for seed_validation (Pydantic validation + template placeholder contract)."""

import json
import os
import tempfile

from app.services.seed_validation import (
    canonical_ids_from_template_json,
    load_seed_arrays,
    validate_seed_json_payloads,
    validate_template_placeholder_contract,
)


def test_canonical_ids_from_template_json_finds_placeholders():
    tpl = {"x": '{{canonical:foo.bar}}', "nested": {"y": "{{canonical:baz}} "}}
    assert canonical_ids_from_template_json(tpl) == {"foo.bar", "baz"}


def test_validate_seed_json_payloads_empty_arrays():
    assert validate_seed_json_payloads([], [], None) == []


def test_validate_template_placeholder_contract_ok():
    concepts = [{"canonical_id": "c1", "description": "d", "value_type": "string", "fhir_data_type": "string"}]
    mappings = [
        {
            "intake_type_id": "t1",
            "intake_type_version": "v1",
            "stable_field_id": "sfid_aaaaaaaa",
            "canonical_id": "c1",
            "approved_by": "seed-load",
        }
    ]
    templates = [
        {
            "intake_type_id": "t1",
            "intake_type_version": "v1",
            "template_json": {"resourceType": "Bundle", "id": "{{canonical:c1}}"},
            "placeholder_schema": {},
            "template_version": "1.0",
        }
    ]
    assert validate_template_placeholder_contract(concepts, mappings, templates) == []


def test_validate_template_placeholder_contract_missing_mapping():
    concepts = [{"canonical_id": "c1", "description": "d", "value_type": "string", "fhir_data_type": "string"}]
    mappings: list[dict] = []
    templates = [
        {
            "intake_type_id": "t1",
            "intake_type_version": "v1",
            "template_json": {"x": "{{canonical:c1}}"},
            "placeholder_schema": {},
        }
    ]
    errs = validate_template_placeholder_contract(concepts, mappings, templates)
    assert len(errs) >= 1
    assert any("no mapping" in e.lower() for e in errs)


def test_validate_template_placeholder_contract_missing_concept():
    """Placeholder references a canonical_id not present in concepts.json."""
    concepts: list[dict] = []
    mappings = [
        {
            "intake_type_id": "t1",
            "intake_type_version": "v1",
            "stable_field_id": "sfid_aaaaaaaa",
            "canonical_id": "c1",
            "approved_by": "seed-load",
        }
    ]
    templates = [
        {
            "intake_type_id": "t1",
            "intake_type_version": "v1",
            "template_json": {"x": "{{canonical:c1}}"},
            "placeholder_schema": {},
        }
    ]
    errs = validate_template_placeholder_contract(concepts, mappings, templates)
    assert any("no matching concept" in e.lower() for e in errs)


def test_validate_template_placeholder_contract_wrong_intake_pair():
    """Concept and mapping exist for t2/v1 but template placeholders expect t1/v1."""
    concepts = [{"canonical_id": "c1", "description": "d", "value_type": "string", "fhir_data_type": "string"}]
    mappings = [
        {
            "intake_type_id": "t2",
            "intake_type_version": "v1",
            "stable_field_id": "sfid_aaaaaaaa",
            "canonical_id": "c1",
            "approved_by": "seed-load",
        }
    ]
    templates = [
        {
            "intake_type_id": "t1",
            "intake_type_version": "v1",
            "template_json": {"x": "{{canonical:c1}}"},
            "placeholder_schema": {},
        }
    ]
    errs = validate_template_placeholder_contract(concepts, mappings, templates)
    assert any("no mapping" in e.lower() for e in errs)


def test_canonical_ids_from_template_json_nested_and_quoted():
    tpl = {
        "entry": [
            {
                "resource": {
                    "valueString": '"{{canonical:a.b}}"',
                }
            }
        ]
    }
    # Serialized JSON still contains the placeholder substring
    ids = canonical_ids_from_template_json(tpl)
    assert "a.b" in ids


def test_validate_seed_json_payloads_with_templates_and_approved_by():
    """approved_by is stripped for TemplateCreate; seed defaults apply to mappings."""
    concepts = [{"canonical_id": "c1", "description": "d", "value_type": "string", "fhir_data_type": "string"}]
    mappings = [
        {
            "intake_type_id": "t1",
            "intake_type_version": "v1",
            "stable_field_id": "sfid_aaaaaaaa",
            "canonical_id": "c1",
        }
    ]
    templates = [
        {
            "intake_type_id": "t1",
            "intake_type_version": "v1",
            "approved_by": "ci-bot",
            "template_json": {"resourceType": "Bundle", "type": "collection"},
            "placeholder_schema": {},
        }
    ]
    assert validate_seed_json_payloads(concepts, mappings, templates) == []


def test_validate_seed_json_payloads_invalid_concept():
    errs = validate_seed_json_payloads(
        [{"canonical_id": "", "description": "x", "value_type": "string", "fhir_data_type": "string"}],
        [],
        None,
    )
    assert len(errs) == 1
    assert "concepts[0]" in errs[0]


def test_validate_seed_json_payloads_invalid_template_not_dict():
    errs = validate_seed_json_payloads([], [], [[]])  # type: ignore[arg-type]
    assert any("templates[0]" in e and "object" in e.lower() for e in errs)


def test_load_seed_arrays_reports_missing_required_files():
    with tempfile.TemporaryDirectory() as d:
        concepts, mappings, templates, errs = load_seed_arrays(d)
        assert concepts == []
        assert mappings == []
        assert templates is None
        assert len(errs) >= 2
        assert any("concepts.json" in e for e in errs)
        assert any("mappings.json" in e for e in errs)


def test_load_seed_arrays_reads_optional_templates():
    with tempfile.TemporaryDirectory() as d:
        minimal_concept = {
            "canonical_id": "x.y",
            "description": "d",
            "value_type": "string",
            "fhir_data_type": "string",
        }
        with open(os.path.join(d, "concepts.json"), "w", encoding="utf-8") as f:
            json.dump([minimal_concept], f)
        with open(os.path.join(d, "mappings.json"), "w", encoding="utf-8") as f:
            json.dump([], f)
        with open(os.path.join(d, "templates.json"), "w", encoding="utf-8") as f:
            json.dump(
                [
                    {
                        "intake_type_id": "t",
                        "intake_type_version": "v1",
                        "template_json": {"resourceType": "Bundle", "type": "collection"},
                        "placeholder_schema": {},
                    }
                ],
                f,
            )

        concepts, mappings, templates, errs = load_seed_arrays(d)
        assert errs == []
        assert len(concepts) == 1
        assert templates is not None and len(templates) == 1


def test_validate_template_placeholder_contract_skips_invalid_template():
    """Invalid TemplateCreate rows are skipped (errors come from validate_seed_json_payloads)."""
    concepts = [{"canonical_id": "c1", "description": "d", "value_type": "string", "fhir_data_type": "string"}]
    mappings: list[dict] = []
    templates = [
        {
            "intake_type_id": "t1",
            "intake_type_version": "v1",
            # missing template_json — TemplateCreate fails
            "placeholder_schema": {},
        }
    ]
    assert validate_template_placeholder_contract(concepts, mappings, templates) == []
