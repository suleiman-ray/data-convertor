"""
Validate seed/*.json against authoring Pydantic models and optional template contracts.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from app.schemas.authoring import ConceptCreate, MappingCreate, TemplateCreate

_PLACEHOLDER_RE = re.compile(r"\{\{canonical:([^}]+)\}\}")


def canonical_ids_from_template_json(template_json: dict) -> set[str]:
    """All canonical_id strings referenced in {{canonical:...}} placeholders."""
    text = json.dumps(template_json, ensure_ascii=False)
    return set(_PLACEHOLDER_RE.findall(text))


def validate_seed_json_payloads(
    concepts_data: list[Any],
    mappings_data: list[Any],
    templates_data: list[Any] | None,
) -> list[str]:
    """
    Validate array shapes with Pydantic. Returns a list of error strings (empty if OK).
    """
    errors: list[str] = []
    for i, raw in enumerate(concepts_data):
        try:
            ConceptCreate.model_validate(raw)
        except Exception as e:
            errors.append(f"concepts[{i}]: {e}")
    for i, raw in enumerate(mappings_data):
        try:
            if isinstance(raw, dict):
                if "mapping_method" not in raw:
                    raw = {**raw, "mapping_method": "agent"}
                if "approved_by" not in raw:
                    raw = {**raw, "approved_by": "seed-load"}
            MappingCreate.model_validate(raw)
        except Exception as e:
            errors.append(f"mappings[{i}]: {e}")
    if templates_data is not None:
        for i, raw in enumerate(templates_data):
            if not isinstance(raw, dict):
                errors.append(f"templates[{i}]: must be a JSON object")
                continue
            payload = {k: v for k, v in raw.items() if k != "approved_by"}
            try:
                TemplateCreate.model_validate(payload)
            except Exception as e:
                errors.append(f"templates[{i}]: {e}")
    return errors


def validate_template_placeholder_contract(
    concepts_data: list[dict[str, Any]],
    mappings_data: list[dict[str, Any]],
    templates_data: list[dict[str, Any]],
) -> list[str]:
    """
    Every {{canonical:id}} in each template must have a concept and at least one
    mapping for that (intake_type_id, intake_type_version, canonical_id).
    """
    errors: list[str] = []
    concept_ids = {c.get("canonical_id") for c in concepts_data if isinstance(c, dict)}
    concept_ids.discard(None)

    for i, raw in enumerate(templates_data):
        if not isinstance(raw, dict):
            continue
        payload = {k: v for k, v in raw.items() if k != "approved_by"}
        try:
            data = TemplateCreate.model_validate(payload)
        except Exception:
            continue  # already reported in validate_seed_json_payloads
        pair = (data.intake_type_id, data.intake_type_version)
        placeholders = canonical_ids_from_template_json(data.template_json)
        mappings_for_pair = [
            m
            for m in mappings_data
            if isinstance(m, dict)
            and m.get("intake_type_id") == pair[0]
            and m.get("intake_type_version") == pair[1]
        ]
        canonicals_mapped = {m.get("canonical_id") for m in mappings_for_pair}
        canonicals_mapped.discard(None)

        for pid in sorted(placeholders):
            if pid not in concept_ids:
                errors.append(
                    f"templates[{i}] ({pair[0]}/{pair[1]}): placeholder "
                    f"{{{{canonical:{pid}}}}} has no matching concept in concepts.json"
                )
            if pid not in canonicals_mapped:
                errors.append(
                    f"templates[{i}] ({pair[0]}/{pair[1]}): placeholder "
                    f"{{{{canonical:{pid}}}}} has no mapping for this intake pair in mappings.json"
                )
    return errors


def load_seed_arrays(
    seed_dir: str,
) -> tuple[list[Any], list[Any], list[Any] | None, list[str]]:
    """
    Load seed JSON files. Returns (concepts, mappings, templates_or_none, errors).

    Missing **concepts.json** or **mappings.json** is an error (strict validation).
    Missing **templates.json** yields templates=None (optional file, same as load_seed.py).
    """
    errors: list[str] = []
    concepts_data: list[Any] = []
    mappings_data: list[Any] = []

    concepts_path = os.path.join(seed_dir, "concepts.json")
    mappings_path = os.path.join(seed_dir, "mappings.json")
    templates_path = os.path.join(seed_dir, "templates.json")

    if not os.path.isfile(concepts_path):
        errors.append(f"Missing file: {concepts_path}")
    else:
        with open(concepts_path, encoding="utf-8") as f:
            concepts_data = json.load(f)
        if not isinstance(concepts_data, list):
            errors.append("concepts.json must be a JSON array")
            concepts_data = []

    if not os.path.isfile(mappings_path):
        errors.append(f"Missing file: {mappings_path}")
    else:
        with open(mappings_path, encoding="utf-8") as f:
            mappings_data = json.load(f)
        if not isinstance(mappings_data, list):
            errors.append("mappings.json must be a JSON array")
            mappings_data = []

    templates_data: list[Any] | None = None
    if os.path.isfile(templates_path):
        with open(templates_path, encoding="utf-8") as f:
            templates_data = json.load(f)
        if not isinstance(templates_data, list):
            errors.append("templates.json must be a JSON array")
            templates_data = []

    return concepts_data, mappings_data, templates_data, errors
