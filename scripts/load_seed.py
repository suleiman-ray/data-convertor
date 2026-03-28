"""
Load seed data (canonical concepts, field mappings, optional FHIR templates) at deploy time.

Reads seed/concepts.json, seed/mappings.json, and optionally seed/templates.json from the
project root.

Idempotent: skips concepts that already exist (409), skips mappings that already exist
(409), skips template seed rows when an APPROVED template already exists for the same
(intake_type_id, intake_type_version).

Exits 0 on full success; exits 1 if validation fails or if a mapping references a
missing concept.

templates.json format: JSON array of objects valid for TemplateCreate (intake_type_id,
intake_type_version, template_json, placeholder_schema, template_version) plus optional
approved_by (default seed-load). After create, each new template is approved so
ingestion/build can run without a separate API approve step.

Usage:
  python scripts/load_seed.py

Expects DATABASE_URL in the environment (same as the API).

Payload shapes match **ConceptCreate**, **MappingCreate**, and **TemplateCreate** in
**app/schemas/authoring.py**. For CI validation rules see **app/services/seed_validation.py**.
"""

import asyncio
import json
import logging
import os
import sys

# Project root = parent of scripts/; ensure app is importable
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
SEED_DIR = os.path.join(PROJECT_ROOT, "seed")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("load_seed")


async def main() -> int:
    from app.core.database import AsyncSessionLocal
    from app.schemas.authoring import ConceptCreate, MappingCreate, TemplateCreate
    from app.services.authoring_concepts import ConceptAlreadyExists, create_concept
    from app.services.authoring_mappings import (
        MappingConflict,
        MappingReferenceError,
        create_mapping,
    )
    from app.services.authoring_templates import (
        approve_template,
        create_template,
        get_approved_template,
        TemplateConflict,
    )

    concepts_path = os.path.join(SEED_DIR, "concepts.json")
    mappings_path = os.path.join(SEED_DIR, "mappings.json")

    if not os.path.isfile(concepts_path):
        logger.warning("Seed file not found: %s (skipping concepts)", concepts_path)
        concepts_data = []
    else:
        with open(concepts_path, encoding="utf-8") as f:
            concepts_data = json.load(f)
        if not isinstance(concepts_data, list):
            logger.error("concepts.json must be a JSON array")
            return 1

    if not os.path.isfile(mappings_path):
        logger.warning("Seed file not found: %s (skipping mappings)", mappings_path)
        mappings_data = []
    else:
        with open(mappings_path, encoding="utf-8") as f:
            mappings_data = json.load(f)
        if not isinstance(mappings_data, list):
            logger.error("mappings.json must be a JSON array")
            return 1

    templates_path = os.path.join(SEED_DIR, "templates.json")
    if not os.path.isfile(templates_path):
        logger.info(
            "Optional seed file not present: %s (skipping FHIR template seed)",
            templates_path,
        )
        templates_data = []
    else:
        with open(templates_path, encoding="utf-8") as f:
            templates_data = json.load(f)
        if not isinstance(templates_data, list):
            logger.error("templates.json must be a JSON array")
            return 1

    concepts_created = 0
    concepts_skipped = 0
    mappings_created = 0
    mappings_skipped = 0
    templates_created = 0
    templates_skipped = 0
    errors = []

    async with AsyncSessionLocal() as db:
        for i, raw in enumerate(concepts_data):
            try:
                data = ConceptCreate.model_validate(raw)
            except Exception as e:
                errors.append(f"concepts[{i}]: {e}")
                continue
            try:
                await create_concept(db, data)
                concepts_created += 1
                logger.info("Created concept: %s", data.canonical_id)
            except ConceptAlreadyExists:
                concepts_skipped += 1
                logger.debug("Concept already exists: %s", data.canonical_id)
            except Exception as e:
                errors.append(f"concept {data.canonical_id}: {e}")

        for i, raw in enumerate(mappings_data):
            try:
                # Ensure mapping_method and approved_by have defaults for seed
                if "mapping_method" not in raw:
                    raw["mapping_method"] = "agent"
                if "approved_by" not in raw:
                    raw["approved_by"] = "seed-load"
                data = MappingCreate.model_validate(raw)
            except Exception as e:
                errors.append(f"mappings[{i}]: {e}")
                continue
            try:
                await create_mapping(db, data)
                mappings_created += 1
                logger.info(
                    "Created mapping: %s/%s %s -> %s",
                    data.intake_type_id,
                    data.intake_type_version,
                    data.stable_field_id,
                    data.canonical_id,
                )
            except MappingConflict:
                mappings_skipped += 1
                logger.debug("Mapping already exists for %s", data.stable_field_id)
            except MappingReferenceError as e:
                errors.append(
                    f"mapping {data.stable_field_id} -> {data.canonical_id}: {e}"
                )
            except Exception as e:
                errors.append(f"mapping {data.stable_field_id}: {e}")

        for i, raw in enumerate(templates_data):
            if not isinstance(raw, dict):
                errors.append(f"templates[{i}]: must be a JSON object")
                continue
            approved_by = raw.get("approved_by") or "seed-load"
            payload = {k: v for k, v in raw.items() if k != "approved_by"}
            try:
                data = TemplateCreate.model_validate(payload)
            except Exception as e:
                errors.append(f"templates[{i}]: {e}")
                continue
            try:
                existing = await get_approved_template(
                    db, data.intake_type_id, data.intake_type_version
                )
                if existing is not None:
                    templates_skipped += 1
                    logger.debug(
                        "Approved template already exists for %s/%s, skipping",
                        data.intake_type_id,
                        data.intake_type_version,
                    )
                    continue
                created = await create_template(db, data)
                await approve_template(db, created.template_id, approved_by)
                templates_created += 1
                logger.info(
                    "Created and approved template for %s/%s template_id=%s",
                    data.intake_type_id,
                    data.intake_type_version,
                    created.template_id,
                )
            except TemplateConflict as e:
                errors.append(
                    f"template {data.intake_type_id}/{data.intake_type_version}: {e}"
                )
            except Exception as e:
                errors.append(
                    f"template {data.intake_type_id}/{data.intake_type_version}: {e}"
                )

    logger.info(
        "Seed load complete: concepts created=%s skipped=%s; mappings created=%s skipped=%s; "
        "templates created=%s skipped=%s",
        concepts_created,
        concepts_skipped,
        mappings_created,
        mappings_skipped,
        templates_created,
        templates_skipped,
    )
    if errors:
        for err in errors:
            logger.error("%s", err)
        return 1
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
