# Seed data (`seed/`)

Deploy-time JSON loaded by `scripts/load_seed.py` after **migrations** and before the **API and workers** (see `docker-compose.yml`: `migrate` → `seed` → `api` / workers).

## Files

| File | `load_seed.py` | `validate_seed.py` (CI) |
|------|----------------|-------------------------|
| `concepts.json` | Optional — missing → warning, empty array | **Required** — file must exist (may be `[]`). Enforced by `scripts/validate_seed.py` / CI. |
| `mappings.json` | Optional — missing → warning, empty array | **Required** — file must exist (may be `[]`). |
| `templates.json` | Optional — missing → info log, skipped | Optional — absent = skip template checks; present = validate + placeholder contract if non-empty. |

Purpose: **`concepts.json`** / **`mappings.json`** are arrays of objects valid for **`ConceptCreate`** / **`MappingCreate`** (loader defaults `mapping_method` / `approved_by` when omitted). **`templates.json`** is for automated FHIR build per intake type/version.

Order inside the loader: **concepts → mappings → templates**. Templates do not FK to concepts in the DB, but this order matches the mental model (concepts and mappings must exist before placeholders resolve).

## `templates.json` — when you need automated FHIR build

Add a JSON **array** of objects that pass **`TemplateCreate`**:

- `intake_type_id`, `intake_type_version`, `template_json`, `placeholder_schema`, `template_version`
- Optional **`approved_by`** (default `seed-load` if omitted)

Placeholders in `template_json` must use `{{canonical:<id>}}` where `<id>` matches **`canonical_id`** values for concepts you seeded and mapped for that intake version.

If `placeholder_schema` is non-empty, it must match the placeholders in `template_json` (enforced by `TemplateCreate` validation — same as the API).

## Keeping concepts, mappings, and templates aligned

For each `(intake_type_id, intake_type_version)` you care about:

1. **Concepts** exist for every canonical id you reference.
2. **Mappings** cover every `stable_field_id` the extractor emits for that intake version.
3. The template’s **placeholder set** matches what you intend (and your `placeholder_schema`, if any).

## Governance: auto-approve vs manual

The loader calls **`create_template`** then **`approve_template`** so environments work **without** a manual approve step after deploy.

If policy requires **human-only** approval:

- Do **not** commit `templates.json`, and create/approve templates via the **API**, or
- Change the loader to create **DRAFT** only (product/code change — not the default).

## Updating an already-approved template

The loader **skips** a seed row when an **APPROVED** `FhirTemplate` already exists for that `(intake_type_id, intake_type_version)`.

Shipping a **new** template bundle requires **deprecating** the old template (API/ops) or another agreed process; **seed alone will not replace** an approved row.

## Operational edge case: create succeeded, approve failed

The loader uses **two steps** (create, then approve). If **`approve_template`** fails (crash, DB error, race), you can be left with a **DRAFT** row. A re-run may create **another DRAFT** because there is still no APPROVED template for that pair.

**Mitigation:** Approve or delete the stray DRAFT manually (API or SQL) before re-running seed, or fix the underlying error and re-run once the DB is consistent.

## CI / quality

Implemented in **`scripts/validate_seed.py`** (also run by **`.github/workflows/ci.yml`**):

- **`concepts.json`** and **`mappings.json`** must exist under **`seed/`** (empty **`[]`** is valid). If your branch omits `seed/`, adjust **`.github/workflows/ci.yml`** so the validate step is skipped or add stub files.
- Optional **`templates.json`** → Pydantic **`TemplateCreate`** when present.
- If **`templates.json`** exists and is non-empty: **placeholder contract** — every `{{canonical:id}}` must have a matching concept and at least one mapping row for that intake pair (`app/services/seed_validation.py`).

Optional extras: pre-commit hook calling the same script; JSON Schema export from Pydantic if you want non-Python linters.

## Related tooling

- **`demo/build_seed_from_data.py`** — builds `concepts.json` and `mappings.json` from `demo/data.json` using the same extraction rules as the pipeline. It does **not** emit `templates.json`; if you extend it, write objects in the **same shape** `load_seed.py` expects (see above).

## Implementation reference

See `scripts/load_seed.py` for idempotency rules, error handling, and exit codes.
