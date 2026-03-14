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
- [Database Backups](#database-backups)
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
| Web Server | Nginx 1.27 (reverse proxy + gzip + rate limiting) |
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
  LAN devices ─── :8000 ──► uvicorn / FastAPI (native on host)
                                    │
                                    ├──► audit files (native Windows filesystem)
                                    │
                                    └──► localhost:5432
                                              │
                                         ┌────────────┐
                                         │   Docker   │
                                         │ PostgreSQL │
                                         └────────────┘
```

- **backend** (FastAPI + Uvicorn) runs natively on the host machine. It accesses audit files directly from the Windows filesystem at native speed, with no virtualisation overhead.
- **db** (PostgreSQL) runs in Docker with port 5432 exposed to `localhost`. Only the database is containerised.
- **Institution logos** are stored in the database as `BYTEA` and served via `GET /api/institutions/{id}/logo` — no shared volumes required.
- **adminer** is available in development only (via `docker-compose.override.yml`).
- The app listens on `0.0.0.0:8000`, so any device on the same LAN can reach it at `http://<host-ip>:8000`.

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
│   ├── static/                 # CSS and other static assets (served by FastAPI)
│   └── templates/              # Jinja2 HTML templates
├── backups/                    # DB snapshots from ./dev.sh backup (not committed by default)
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
AUDIT_HOST_PATH=./audit_data
LOG_LEVEL=INFO
DOCS_ENABLED=true
```

> `.env` is listed in `.gitignore` and must never be committed. All three `POSTGRES_*` variables are **required** — Docker Compose will refuse to start if any are missing.

**2. Start the database**

```bash
./dev.sh db
```

`docker-compose.override.yml` is applied automatically, which starts Adminer (database UI at `http://localhost:8080`).

**3. Run migrations**

```bash
./dev.sh migrate
```

**4. Start the backend**

```bash
./dev.sh serve
```

Uvicorn starts with hot-reload on `0.0.0.0:8000`. Any device on your local network can access the app at `http://<your-ip>:8000`.

**5. Configure the audit folder**

Go to `http://localhost:8000` → **Configuración → Sistema** and set the path to the folder where your audit subfolders live (e.g. `C:\Users\tu_usuario\Desktop\Carpeta compartida`).

**6. Access the application**

| URL | Description |
|---|---|
| `http://localhost:8000` | Main application |
| `http://<your-lan-ip>:8000` | Access from other devices on the network |
| `http://localhost:8000/docs` | Swagger UI (dev only, `DOCS_ENABLED=true`) |
| `http://localhost:8080` | Adminer database UI (dev only) |

---

## Environment Variables

All variables are read by `app/config.py` via pydantic-settings.

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | Yes | — | Full asyncpg connection string. Use `localhost:5432` since the backend runs natively. |
| `SECRET_KEY` | Yes | — | 32-byte base64-encoded key for AES encryption of stored credentials. |
| `POSTGRES_USER` | Yes | — | PostgreSQL username (used by the `db` Docker service). |
| `POSTGRES_PASSWORD` | Yes | — | PostgreSQL password. |
| `POSTGRES_DB` | Yes | — | PostgreSQL database name. |
| `LOG_LEVEL` | No | `INFO` | Structlog level: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `DOCS_ENABLED` | No | `false` | Set `true` to enable `/docs` and `/redoc`. Never enable in production. |

> The audit folder path is configured from the UI (**Configuración → Sistema**) and stored in the database — not in `.env`.

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
uv run alembic current
uv run alembic downgrade -1
```

---

## Database Backups

Configuration tables (`institutions`, `service_types`, `doc_types`, `folder_statuses`, `prefix_corrections`, `admins`, `contracts`, `services`, `service_type_documents`) can take significant time to rebuild. The `backup` / `restore` commands let you snapshot and restore them without touching operational data (`audit_periods`, `invoices`, `missing_files`).

```bash
# Create a snapshot (label defaults to "seeds")
./dev.sh backup seeds_base
# → backups/seeds_base_20260314_120000.sql

# List snapshots
ls -lh backups/

# Restore from a snapshot
./dev.sh restore backups/seeds_base_20260314_120000.sql
```

Snapshot files (`backups/*.sql`) are excluded from git by default. Commit individual snapshots manually if you want to version them.

---

## API Reference

All API endpoints are prefixed with `/api`. Swagger UI is available at `/docs` when `DOCS_ENABLED=true`.

### Institutions — `/api/institutions`

Manages hospitals and clinics, including their mappings (admins, contracts, services) and logos stored in the database.

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/institutions` | List all institutions |
| `POST` | `/api/institutions` | Create institution |
| `GET` | `/api/institutions/{id}` | Get institution by ID |
| `PUT` | `/api/institutions/{id}` | Update institution |
| `DELETE` | `/api/institutions/{id}` | Delete institution |
| `GET` | `/api/institutions/{id}/logo` | Serve institution logo (from DB) |
| `POST` | `/api/institutions/{id}/logo` | Upload institution logo (PNG/JPEG/WebP/AVIF/GIF) |
| `GET` | `/api/institutions/{id}/admins` | List admins (`?pending_only=true` for unmapped) |
| `POST` | `/api/institutions/{id}/admins` | Create admin mapping |
| `PATCH` | `/api/institutions/admins/{admin_id}` | Set canonical admin and type |
| `DELETE` | `/api/institutions/admins/{admin_id}` | Delete admin mapping |
| `GET` | `/api/institutions/{id}/contracts` | List contracts (`?pending_only=true` for unmapped) |
| `POST` | `/api/institutions/{id}/contracts` | Create contract mapping |
| `PATCH` | `/api/institutions/contracts/{contract_id}` | Set canonical contract |
| `DELETE` | `/api/institutions/contracts/{contract_id}` | Delete contract mapping |
| `GET` | `/api/institutions/{id}/services` | List service mappings |
| `POST` | `/api/institutions/{id}/services` | Create service mapping |
| `PATCH` | `/api/institutions/services/{service_id}` | Set service type |
| `DELETE` | `/api/institutions/services/{service_id}` | Delete service mapping |
| `GET` | `/api/institutions/{id}/service-type-documents` | List required docs per service type |
| `POST` | `/api/institutions/{id}/service-type-documents` | Add required doc to service type |
| `DELETE` | `/api/institutions/{id}/service-type-documents/{st_id}/{dt_id}` | Remove required doc |

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
| `GET` | `/api/settings/service-types` | List service types |
| `POST` | `/api/settings/service-types` | Create service type |
| `PATCH` | `/api/settings/service-types/{id}` | Update service type |
| `DELETE` | `/api/settings/service-types/{id}` | Delete service type |
| `GET` | `/api/settings/doc-types` | List document types |
| `POST` | `/api/settings/doc-types` | Create document type |
| `PATCH` | `/api/settings/doc-types/{id}` | Update document type |
| `DELETE` | `/api/settings/doc-types/{id}` | Delete document type |
| `GET` | `/api/settings/folder-statuses` | List folder statuses |
| `POST` | `/api/settings/folder-statuses` | Create folder status |
| `PATCH` | `/api/settings/folder-statuses/{id}` | Update folder status |
| `DELETE` | `/api/settings/folder-statuses/{id}` | Delete folder status |
| `GET` | `/api/settings/prefix-corrections` | List prefix correction rules |
| `POST` | `/api/settings/prefix-corrections` | Create prefix correction rule |
| `PATCH` | `/api/settings/prefix-corrections/{id}` | Update prefix correction rule |
| `DELETE` | `/api/settings/prefix-corrections/{id}` | Delete prefix correction rule |

> The audit folder path is no longer a database setting — it is configured via `AUDIT_HOST_PATH` in `.env` and mounted at `/audit_data` inside the container.

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

- **Institution** — Hospital or clinic; stores NIT, invoice prefix, SIHOS credentials (AES-encrypted), Drive credentials (AES-encrypted), local base path, and logo image (`logo_bytes` BYTEA + `logo_content_type`).
- **AuditPeriod** — Billing period (month/year label) scoping a set of invoices.
- **Invoice** — Patient billing record imported from SIHOS; linked to an Admin, Contract, and ServiceType.
- **Admin** — Maps a raw administrator string from SIHOS to a canonical administrator name and type per institution.
- **Contract** — Maps a raw contract string from SIHOS to a canonical contract name per institution.
- **Service** — Maps a raw service string from SIHOS to a ServiceType per institution.
- **ServiceType** — Medical service category (e.g., hospitalization, outpatient); defines which document types are required via `ServiceTypeDocument`.
- **DocType** — A required document type with a canonical filename prefix.
- **ServiceTypeDocument** — Join entity linking a ServiceType to a required DocType for a specific institution.
- **Finding (MissingFile)** — Records a specific missing required document for an invoice.
- **PrefixCorrection** — Maps known incorrect filename prefixes to their correct canonical form (used in the `NORMALIZE_FILES` pipeline stage).

> **Audit folder path** — The base folder where institution subfolders live is set via `AUDIT_HOST_PATH` in `.env` (mounted at `/audit_data` inside the container). It is not stored in the database.

---

## Security

- **`.env` is never committed** — it is listed in `.gitignore`. Use `.env.example` as a template.
- **Required variables are enforced** — `docker-compose.yml` uses `:?` syntax for all credential variables (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`). If any are missing, Docker Compose aborts with an explicit error instead of silently falling back to weak defaults.
- **Secrets are encrypted at rest** — SIHOS passwords and Google Drive credentials are stored in the database using AES encryption via `app/crypto.py`. The encryption key is derived from `SECRET_KEY`.
- **Logos stored in DB** — Institution logos are stored as `BYTEA` in PostgreSQL and served via the API, eliminating any shared volume with sensitive data leakage risk.
- **Non-root container** — The Docker image runs as `appuser`, not `root`.
- **No direct database exposure** — PostgreSQL is only accessible within the Docker network.
- **Swagger disabled by default** — `DOCS_ENABLED=false` in production prevents API documentation exposure.
- **Rate limiting** — nginx limits API requests to 30 req/s per IP (burst of 20).
- **Git history is clean** — no credentials or secrets have ever been committed to the repository.

---

## Development

### Developer script

`dev.sh` wraps the most common commands:

```bash
./dev.sh help                          # list all commands

# Database (Docker)
./dev.sh db                            # start PostgreSQL container
./dev.sh db-down                       # stop PostgreSQL container
./dev.sh psql                          # connect to PostgreSQL via psql
./dev.sh backup [nombre]               # snapshot config tables → backups/<nombre>_TIMESTAMP.sql
./dev.sh restore <archivo.sql>         # restore config tables from snapshot
./dev.sh nuke                          # destroy all volumes (asks confirmation)

# Backend (native)
./dev.sh serve                         # start uvicorn with hot-reload on 0.0.0.0:8000
./dev.sh migrate                       # apply pending Alembic migrations
./dev.sh migration "describe change"   # generate new migration
./dev.sh seed                          # run database seed script
./dev.sh test                          # run pytest
./dev.sh lint                          # ruff check + format check
./dev.sh format                        # auto-fix formatting
./dev.sh health                        # check /health endpoint (localhost:8000)
```

### Running tests

```bash
./dev.sh test
# or with extra pytest args:
./dev.sh test -k test_invoice -v
# or directly:
uv run pytest
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
uv run python -c "from app.config import settings; print(settings.model_dump())"
```
