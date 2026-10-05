# SLSEA Solar Generation API

This student-friendly FastAPI project implements the backend required for the
NB6007CEM Web API Development coursework. It receives readings from individual
solar installations and gives authorized SLSEA analysts operational and
historical views of the data.

The implementation is intentionally straightforward: synchronous SQLAlchemy,
small route modules, descriptive names, and comments around the logic that is
most important in the viva.

## What the project demonstrates

- The required hierarchy: Province -> District -> Grid Substation -> Solar
  Installation -> Generation Reading, plus User.
- The meter ID is an Installation attribute; there is no unnecessary Device
  entity.
- Readings are an append-only time series.
- Correct REST methods, 201 and Location on creation, JSON representations,
  ETag, Last-Modified, 304, and stale If-Match handling with 412.
- Pagination with total/next/previous, regional and time filters, and ascending
  or descending timestamp sorting.
- JWT bearer tokens, device-to-installation binding, and national/province/
  district analyst jurisdictions.
- Installation overview, last-known reading, and district generation summary.
- A consistent JSON error contract.
- A required-scale seed dataset and automated tests.

## Quick start with Python

Python 3.12 or newer is required.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
python scripts/seed.py
uvicorn slsea_api.main:app --reload
```

Open these URLs:

- Swagger UI: http://localhost:8000/docs
- OpenAPI JSON: http://localhost:8000/openapi.json
- Readiness: http://localhost:8000/api/v1/health/ready

The default local database is `solar_api.db`. Seeding is idempotent, so running
the command again does not duplicate records. `python scripts/seed.py --reset`
is the explicit destructive reset option.

## Demonstration credentials

| Actor | Username | Password or secret | Purpose |
|---|---|---|---|
| National analyst | `national.analyst@slsea.demo` | `AnalystCoursework!2026` | Read all regions |
| Western analyst | `western.analyst@slsea.demo` | `AnalystCoursework!2026` | Read one province |
| Colombo analyst | `colombo.analyst@slsea.demo` | `AnalystCoursework!2026` | Read one district |
| Catalog admin | `catalog.admin@slsea.demo` | `AdminCoursework!2026` | Read and maintain metadata |
| Example meter | `SL-COL-001` | `SolarDevice!SL-COL-001` | Submit only its own readings |

Use `POST /api/v1/auth/token` or Swagger's **Authorize** button. Every seeded
meter follows `SolarDevice!<meter-id>` so it is easy to demonstrate another
installation during the viva. These are coursework demo credentials and must
not be reused in a real system.

## Main resources

| Shape | Example |
|---|---|
| Collection | `GET /api/v1/provinces` |
| Scoped collection | `GET /api/v1/provinces/1/districts` |
| Atomic resource | `GET /api/v1/installations/1` |
| Composite resource | `GET /api/v1/installations/1/overview` |
| Derived operational resource | `GET /api/v1/installations/1/last-known-reading` |
| Historical collection | `GET /api/v1/installations/1/readings` |
| Cross-site analytical collection | `GET /api/v1/readings?district_id=1` |
| Processing resource | `GET /api/v1/districts/1/generation-summary` |

Catalog admins have POST/PUT/PATCH/DELETE routes for provinces, districts,
substations, and installations. Readings deliberately have POST and GET only:
changing or deleting a historical measurement would violate the append-only
model. A request to mutate one returns 405 with `Allow: GET`.

## Seed scale

The normal seed command creates:

- 9 provinces
- all 25 Sri Lankan districts
- 25 grid substations
- 200 solar installations
- 7 days of 15-minute readings: 134,400 rows
- 4 demonstration users

Power follows a commented sine-shaped daylight curve, is zero overnight, and
feeds a cumulative energy value. The fixed random seed keeps the shape
repeatable.

## Tests and code quality

```bash
pytest
ruff check src scripts tests
pytest --cov=slsea_api --cov-report=term-missing
```

The integration tests cover authentication, scope isolation, 201 and Location,
ETag/304, If-Match/412, pagination, filters, device ownership, append-only
history, composite/processing resources, content negotiation, and the error
contract.

## Docker and deployment

Local PostgreSQL parity:

```bash
docker compose up --build
```

`render.yaml` defines a Render web service and PostgreSQL database. In Render,
create a Blueprint from the repository, wait for the first seed to complete,
then verify `/docs`, `/openapi.json`, and `/api/v1/health/ready` over HTTPS.

Before submission, keep the deployed service awake if your plan sleeps,
re-run the smoke checks, and share the Git repository with the module leader.

## Where to study the important logic

- `models.py`: entity relationships and append-only protection.
- `security.py`: PBKDF2 hashing and JWT claims.
- `dependencies.py`: operation scopes and jurisdiction claims.
- `routers/catalog.py`: REST CRUD, Location, and If-Match.
- `routers/readings.py`: device binding, filters, pagination, derived resources,
  and district aggregation.
- `conditional.py`: ETag, Last-Modified, 304, and 412 behavior.
- `seed.py`: realistic dataset generation.

Use [docs/API_DESIGN_GUIDE.md](docs/API_DESIGN_GUIDE.md) while learning the
project. The report declaration requires the final report prose to be your own;
the documentation here is study and evidence material, not a submission-ready
report.
