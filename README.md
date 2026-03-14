# Medical Audit v2

A production-ready web application for automating the document audit process of medical billing in Colombian healthcare institutions. It ingests invoices from SIHOS, validates physical document folders against required documentation rules, and tracks audit status across billing periods.

---

## Table of Contents

- [Overview](#overview)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Local Development](#local-development)
  - [Production Deployment](#production-deployment)
- [Environment Variables](#environment-variables)
- [Database Migrations](#database-migrations)
- [API Reference](#api-reference)
- [Audit Pipeline](#audit-pipeline)
- [Domain Model](#domain-model)
- [Security](#security)
- [Development](#development)

---

## Overview

Medical Audit v2 automates the reconciliation between:

- **SIHOS billing records** — invoices exported as Excel files from the hospital information system
- **Physical document folders** — patient folders stored locally or on Google Drive, organized by invoice number

The application runs an 18-stage pipeline that ingests invoices, normalizes folder structures, runs OCR, validates required documents per service type, verifies Colombian e-invoice codes (CUFE), and organizes audited folders — producing a clear audit status for every invoice in a billing period.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Web Framework | FastAPI (async) |
| Database | PostgreSQL 16 |
| ORM / Migrations | SQLAlchemy 2.0 (asyncio) + Alembic |
| Frontend | Jinja2 server-side templates |
| Web Server | Nginx 1.27 (reverse proxy + static files) |
| App Server | Uvicorn (2 workers) |
| Containers | Docker (multi-stage build) + Docker Compose |
| PDF / OCR | PyMuPDF, pdfplumber, ocrmypdf, Tesseract |
| Browser Automation | Playwright (SIHOS invoice download) |
| Cloud | Google Drive API |
| Data Processing | pandas, openpyxl |
| Logging | structlog |
| Security | cryptography (AES encryption for stored credentials) |
| Package Manager | uv |
| Testing | pytest + pytest-asyncio |

---

## Architecture

```
                        ┌─────────────────────────────────┐
                        │          Docker Network          │
                        │                                  │
  Browser ──── :80 ───► │  nginx  ──► /api, /  ──► backend │
                        │          └─► /static  (volume)  │
                        │                    │             │
                        │              PostgreSQL 16       │
                        │                                  │
                        └─────────────────────────────────┘
```

- **nginx** is the only publicly exposed service (port 80). It handles rate limiting (30 req/s), gzip compression, and serves static files directly from a shared Docker volume — zero-copy, no FastAPI overhead.
- **backend** (FastAPI + Uvicorn) handles all API and page requests, never exposed directly to the internet.
- **db** (PostgreSQL) is only reachable from within the Docker network.
- **adminer** is available in development only (via `docker-compose.override.yml`).

---

## Project Structure

```
medical-audit-v2/
├── app/                        # FastAPI application
│   ├── main.py                 # App factory, lifespan, router registration
│   ├── config.py               # Settings (pydantic-settings, reads from .env)
│   ├── database.py             # Async SQLAlchemy session factory
│   ├── crypto.py               # AES encryption for stored credentials
│   ├── models/                 # SQLAlchemy ORM models
│   ├── repositories/           # Data access layer
│   ├── routers/
│   │   ├── pages.py            # Jinja2 page routes (/, /audit, /settings)
│   │   └── api/                # REST API routers
│   ├── schemas/                # Pydantic request/response schemas
│   ├── services/
│   │   ├── billing.py          # SIHOS Excel ingestion
│   │   └── pipeline_runner.py  # 18-stage audit pipeline
│   ├── static/                 # CSS, logos (served by nginx in production)
│   └── templates/              # Jinja2 HTML templates
├── core/                       # Domain logic & document processing
│   ├── scanner.py              # File discovery and validation
│   ├── reader.py               # PDF text extraction
│   ├── processor.py            # OCR processing (ocrmypdf)
│   ├── validator.py            # Invoice / CUFE validation
│   ├── inspector.py            # Folder structure inspection
│   ├── organizer.py            # Folder and invoice organization
│   ├── standardizer.py         # Filename normalization
│   ├── downloader.py           # Playwright-based SIHOS downloader
│   └── drive.py                # Google Drive sync
├── alembic/                    # Database migrations
│   └── versions/
├── nginx/
│   └── nginx.conf              # Reverse proxy + rate limiting + compression
├── seeds/                      # Seed data scripts
├── tests/
├── Dockerfile                  # Multi-stage: builder + runtime
├── docker-compose.yml          # Production services
├── docker-compose.override.yml # Dev overrides (auto-applied locally)
├── .env.example                # Production environment template
├── dev.sh                      # Developer convenience script (./dev.sh help)
└── pyproject.toml              # Dependencies and tooling config
```

---

## Getting Started

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose v2
- [uv](https://github.com/astral-sh/uv) (for local development without Docker)

### Local Development

**1. Clone and configure environment**

```bash
git clone <repo-url>
cd medical-audit-v2
cp .env.example .env
```

Edit `.env` with local development values (generate your own `SECRET_KEY` — see command below):

```dotenv
DATABASE_URL=postgresql+asyncpg://audit:audit@db:5432/medical_audit
SECRET_KEY=<generate with: python -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())">
POSTGRES_USER=audit
POSTGRES_PASSWORD=audit
POSTGRES_DB=medical_audit
LOG_LEVEL=INFO
DOCS_ENABLED=true
```

> `.env` is listed in `.gitignore` and must never be committed. All three `POSTGRES_*` variables are **required** — Docker Compose will refuse to start if any are missing.

**2. Start services**

```bash
./dev.sh up
```

`docker-compose.override.yml` is applied automatically, which:
- Sets `DOCS_ENABLED=true` (enables Swagger UI at `/docs`)
- Mounts `./app` and `./core` for hot-reload
- Starts Adminer (database UI at `http://localhost:8080`)

**3. Run migrations**

```bash
./dev.sh migrate
```

**4. Access the application**

| URL | Description |
|---|---|
| `http://localhost` | Main application |
| `http://localhost/docs` | Swagger UI (dev only) |
| `http://localhost:8080` | Adminer database UI (dev only) |

### Production Deployment

**1. Set up environment on the server**

```bash
git clone <repo-url>
cd medical-audit-v2
cp .env.example .env
nano .env   # Fill in real passwords and SECRET_KEY
```

Generate a secure `SECRET_KEY`:

```bash
python -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

**2. Deploy**

```bash
docker compose up -d
docker compose exec backend alembic upgrade head
```

> `docker-compose.override.yml` is only applied when it exists on the machine. On a production server where you don't copy it, only `docker-compose.yml` runs — Swagger is disabled, Adminer does not start.
> `dev.sh` is a local development convenience only — do not run it on the production server.

**3. Verify**

```bash
curl http://localhost/health
docker compose ps
docker compose logs backend --tail 50
```

---

## Environment Variables

All variables are read by `app/config.py` via pydantic-settings.

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | Yes | — | Full asyncpg connection string. Host must be `db` in Docker. |
| `SECRET_KEY` | Yes | — | 32-byte base64-encoded key for AES encryption of stored credentials. |
| `POSTGRES_USER` | Yes | — | PostgreSQL username (used by the `db` service). |
| `POSTGRES_PASSWORD` | Yes | — | PostgreSQL password. |
| `POSTGRES_DB` | Yes | — | PostgreSQL database name. |
| `LOG_LEVEL` | No | `INFO` | Structlog level: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `DOCS_ENABLED` | No | `false` | Set `true` to enable `/docs` and `/redoc`. Never enable in production. |

Copy `.env.example` as your starting point — it contains all variables with production-safe placeholder values.

---

## Database Migrations

This project uses [Alembic](https://alembic.sqlalchemy.org/) for schema migrations.

```bash
# Apply all pending migrations
./dev.sh migrate

# Create a new migration (auto-generate from model changes)
./dev.sh migration "describe your change"

# Check current revision / downgrade (raw commands)
docker compose exec backend alembic current
docker compose exec backend alembic downgrade -1
```

---

## API Reference

All API endpoints are prefixed with `/api`. Swagger UI is available at `/docs` when `DOCS_ENABLED=true`.

### Institutions — `/api/institutions`

Manages hospitals and clinics.

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/institutions` | List all institutions |
| `POST` | `/api/institutions` | Create institution |
| `GET` | `/api/institutions/{id}` | Get institution by ID |
| `PUT` | `/api/institutions/{id}` | Update institution |
| `DELETE` | `/api/institutions/{id}` | Delete institution |
| `POST` | `/api/institutions/{id}/admins` | Add admin contact |
| `POST` | `/api/institutions/{id}/contracts` | Add contract |
| `POST` | `/api/institutions/{id}/services` | Add service mapping |

### Audit Periods — `/api/periods`

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/periods` | List all periods |
| `POST` | `/api/periods` | Create period |
| `GET` | `/api/periods/{id}` | Get period by ID |
| `PUT` | `/api/periods/{id}` | Update period |
| `DELETE` | `/api/periods/{id}` | Delete period |

### Invoices — `/api/invoices`

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/invoices` | List invoices (filterable by period, status, institution) |
| `PATCH` | `/api/invoices/{id}` | Update invoice status |
| `POST` | `/api/invoices/batch-update` | Batch update statuses |
| `DELETE` | `/api/invoices/{id}` | Delete invoice |
| `POST` | `/api/invoices/ingest` | Ingest SIHOS Excel file (multipart) |

### Findings — `/api/missing-files`

Records of missing required documents per invoice.

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/missing-files/{invoice_id}` | Get findings for invoice |
| `POST` | `/api/missing-files` | Record a finding |
| `PATCH` | `/api/missing-files/{id}/resolve` | Mark finding as resolved |
| `DELETE` | `/api/missing-files/{id}` | Delete finding |

### Pipeline — `/api/pipeline`

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/pipeline/run/{stage}` | Execute a pipeline stage; returns **Server-Sent Events** stream |

### Settings — `/api/settings`

Business rules configuration.

| Method | Path | Description |
|---|---|---|
| `GET/POST` | `/api/settings/service-types` | List / create service types |
| `GET/PUT/DELETE` | `/api/settings/service-types/{id}` | Get / update / delete service type |
| `GET/POST` | `/api/settings/doc-types` | List / create document types |
| `GET/PUT/DELETE` | `/api/settings/doc-types/{id}` | Get / update / delete document type |
| `GET/POST` | `/api/settings/folder-statuses` | List / create folder statuses |
| `GET/POST` | `/api/settings/prefix-corrections` | List / create prefix correction rules |

---

## Audit Pipeline

The pipeline is composed of 18 sequential stages. Each stage is triggered individually via `GET /api/pipeline/run/{STAGE_NAME}` and streams log lines as Server-Sent Events (`[INFO]`, `[WARN]`, `[ERROR]`).

| # | Stage Name | Description |
|---|---|---|
| 1 | `LOAD_AND_PROCESS` | Ingest SIHOS Excel export → upsert invoices into the database |
| 2 | `RUN_STAGING` | Move leaf folders from Google Drive → local staging area |
| 3 | `REMOVE_NON_PDF` | Delete non-PDF files and corrupt PDFs from staging |
| 4 | `NORMALIZE_FILES` | Apply PrefixCorrection rules + filename standardization |
| 5 | `LIST_UNREADABLE_PDFS` | Report invoice PDFs without a text layer (OCR candidates) |
| 6 | `DELETE_UNREADABLE_PDFS` | Remove invoice PDFs that cannot be read even after OCR |
| 7 | `DOWNLOAD_INVOICES_FROM_SIHOS` | Download specific invoices from SIHOS via Playwright automation |
| 8 | `CHECK_INVOICES` | Apply OCR (`ocrmypdf`, batch size 8) to scanned PDFs |
| 9 | `VERIFY_INVOICE_CODE` | Confirm each invoice PDF contains its own invoice number in extracted text |
| 10 | `CHECK_INVOICE_NUMBER_ON_FILES` | Verify files inside each folder match the folder's invoice number |
| 11 | `CHECK_FOLDERS_WITH_EXTRA_TEXT` | Detect folders with extraneous text appended to the canonical name |
| 12 | `NORMALIZE_DIR_NAMES` | Rename malformed folder names to canonical invoice IDs |
| 13 | `CHECK_DIRS` | Reconcile DB invoices vs. disk folders; mark missing folders as `FALTANTE` |
| 14 | `CHECK_REQUIRED_DOCS` | Validate required documents per service type; record findings; mark `PENDIENTE` |
| 15 | `VERIFY_CUFE` | Verify the Colombian e-invoice code (CUFE) in PDFs; flag folders with missing CUFE |
| 16 | `ORGANIZE` | Move eligible invoices (`PRESENTE`, no findings) to the audit destination; mark `AUDITADA` |
| 17 | `DOWNLOAD_DRIVE` | Download `FALTANTE` folders from Google Drive; update status to `PRESENTE` |
| 18 | `DOWNLOAD_MISSING_DOCS` | Download specific missing documents from Drive for invoices with open findings |

---

## Domain Model

### Invoice Folder Statuses

| Status | Meaning |
|---|---|
| `PRESENTE` | Folder exists on disk |
| `FALTANTE` | Folder not found on disk or Drive |
| `AUDITADA` | Fully validated and moved to audit destination |
| `PENDIENTE` | Present but has open document findings |
| `REVISAR` | Flagged for manual review |
| `ANULAR` | Marked for cancellation |

### Key Entities

- **Institution** — Hospital or clinic; stores NIT, invoice prefix, SIHOS credentials (encrypted), Drive credentials (encrypted), and local base path.
- **AuditPeriod** — Billing period (month/year label) scoping a set of invoices.
- **Invoice** — Patient billing record imported from SIHOS; linked to an Admin, Contract, and ServiceType.
- **ServiceType** — Medical service category (e.g., hospitalization, outpatient); defines which document types are required.
- **DocType** — A required document type with a canonical filename prefix.
- **Finding (MissingFile)** — Records a specific missing required document for an invoice.
- **PrefixCorrection** — Maps known incorrect filename prefixes to their correct canonical form (used in normalization).

---

## Security

- **`.env` is never committed** — it is listed in `.gitignore`. Use `.env.example` as a template.
- **Required variables are enforced** — `docker-compose.yml` uses `:?` syntax for all credential variables (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`). If any are missing, Docker Compose aborts with an explicit error instead of silently falling back to weak defaults.
- **Secrets are encrypted at rest** — SIHOS passwords and Google Drive credentials are stored in the database using AES encryption via `app/crypto.py`. The encryption key is derived from `SECRET_KEY`.
- **Non-root container** — The Docker image runs as `appuser`, not `root`.
- **No direct database exposure** — PostgreSQL is only accessible within the Docker network.
- **Swagger disabled by default** — `DOCS_ENABLED=false` in production prevents API documentation exposure.
- **Rate limiting** — nginx limits API requests to 30 req/s per IP (burst of 20).
- **Git history is clean** — no credentials or secrets have ever been committed to the repository.

---

## Development

### Developer script

`dev.sh` wraps the most common commands so you don't have to type long `docker compose` lines:

```bash
./dev.sh help          # list all commands
./dev.sh up            # start services
./dev.sh logs backend  # follow backend logs
./dev.sh migrate       # apply pending migrations
./dev.sh test          # run pytest inside the container
./dev.sh lint          # ruff check + format check
./dev.sh shell         # interactive shell inside backend container
./dev.sh nuke          # destroy all volumes (asks confirmation)
```

### Running tests

```bash
./dev.sh test
# or with extra pytest args:
./dev.sh test -k test_invoice -v
```

### Linting and formatting

```bash
./dev.sh lint      # check only (CI-safe)
./dev.sh format    # auto-fix formatting
uv run mypy app/   # type checking (no dev.sh wrapper)
```

### Validating Docker Compose config

```bash
# With override (dev)
docker compose config

# Production only (no override)
docker compose -f docker-compose.yml config
```

### Confirming settings are loaded correctly

```bash
docker compose run --rm backend python -c "from app.config import settings; print(settings.model_dump())"
```
