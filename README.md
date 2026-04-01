# FHIR Converter

Turn clinical intakes (JSON forms or structured text) into validated **FHIR R4** bundles and deliver them to AWS HealthLake (or a configured sink).

## Stack

- **FastAPI** — ingestion and authoring APIs  
- **Workers** — SQS-driven pipeline: extract → resolve/normalize → FHIR build → deliver  
- **Postgres, Redis, S3, SQS** — state, cache, artifacts, queues  

## Quick start

Configure `.env` (see your environment), then:

```bash
docker compose up --build
```

API defaults to `http://localhost:8000`. Run DB migrations and seed via the compose services (`migrate`, `seed`) before workers process traffic.

## Database sessions

FastAPI’s `get_db()` dependency **does not auto-commit**. Successful writes require an explicit `await db.commit()` in the route or service layer. On exceptions, the session rolls back. See `app/core/database.py`.

## Seed data (deploy-time)

JSON under **`seed/`** is loaded by **`scripts/load_seed.py`** after migrations. Shapes match **`app/schemas/authoring.py`** (`ConceptCreate`, `MappingCreate`, `TemplateCreate`). Order: concepts → mappings → optional templates. CI runs **`scripts/validate_seed.py`** (see **`app/services/seed_validation.py`**).

### Intake types in seed

These **`(intake_type_id, intake_type_version)`** pairs are defined in **`seed/mappings.json`** and **`seed/templates.json`**. Use them as the baseline for prod/staging when seed is applied. Ingestion also accepts any pair that has a **`FhirTemplate`** row in the database (see **`app/services/ingestion.py`**), so additional types can be onboarded without code changes.

| `intake_type_id` | `intake_type_version` |
|------------------|------------------------|
| `adult-behavioural-intake` | `v1` |
| `child-new-patient-history` | `v1` |
| `fast` | `v1` |
| `general-screening` | `v1` |
| `mas` | `v1` |
| `qabf` | `v1` |
| `tbi-intake` | `v1` |

## Further detail

Operational behavior is defined in **`scripts/load_seed.py`**, **`app/schemas/authoring.py`**, **`app/services/seed_validation.py`**, and **`docker-compose.yml`**.
