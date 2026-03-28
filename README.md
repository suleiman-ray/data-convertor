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

## Seed data (deploy-time)

JSON under **`seed/`** is loaded by **`scripts/load_seed.py`** after migrations. Shapes match **`app/schemas/authoring.py`** (`ConceptCreate`, `MappingCreate`, `TemplateCreate`). Order: concepts → mappings → optional templates. CI runs **`scripts/validate_seed.py`** (see **`app/services/seed_validation.py`**).

## Further detail

Operational behavior is defined in **`scripts/load_seed.py`**, **`app/schemas/authoring.py`**, **`app/services/seed_validation.py`**, and **`docker-compose.yml`**.
