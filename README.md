# Medical Audit v2

Aplicación web de producción para automatizar la auditoría de documentos de facturación médica en instituciones de salud colombianas. Ingesta facturas desde SIHOS, valida carpetas físicas de documentos contra las reglas de documentación requerida por tipo de servicio, y lleva el estado de auditoría por periodo de facturación.

---

## Tabla de contenidos

- [Stack tecnológico](#stack-tecnológico)
- [Arquitectura](#arquitectura)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Primeros pasos](#primeros-pasos)
- [Variables de entorno](#variables-de-entorno)
- [Comandos de desarrollo](#comandos-de-desarrollo)
- [Migraciones](#migraciones)
- [Backups de configuración](#backups-de-configuración)
- [API Reference](#api-reference)
- [Pipeline de auditoría](#pipeline-de-auditoría)
- [Modelo de dominio](#modelo-de-dominio)
- [Testing](#testing)
- [Seguridad](#seguridad)
- [Monitoreo](#monitoreo)

---

## Stack tecnológico

| Capa | Tecnología |
|---|---|
| Lenguaje | Python 3.11+ |
| Framework web | FastAPI (async) |
| Base de datos | PostgreSQL 16 |
| ORM / Migraciones | SQLAlchemy 2.0 (asyncio) + Alembic |
| Frontend | Jinja2 (templates server-side) |
| Servidor de app | Uvicorn (2 workers, nativo en host) |
| Proxy inverso | Nginx 1.27 (rate limiting, gzip, SSE) |
| Contenedores | Docker + Docker Compose |
| PDF / OCR | PyMuPDF, pdfplumber, ocrmypdf, Tesseract |
| Automatización de browser | Playwright (descarga de facturas SIHOS) |
| Almacenamiento en nube | Google Drive API |
| Procesamiento de datos | pandas, openpyxl |
| Logs | structlog (estructurado) |
| Seguridad | cryptography (AES-256-GCM para credenciales almacenadas) |
| Métricas | prometheus-fastapi-instrumentator |
| Gestor de paquetes | uv |
| Testing | pytest + pytest-asyncio |

---

## Arquitectura

```
  Dispositivos LAN ──── :8000 ──► Uvicorn / FastAPI  (nativo en Windows)
                                          │
                          ┌───────────────┼───────────────┐
                          │               │               │
                   sistema de         Google         localhost:5432
                   archivos           Drive API           │
                   Windows                         ┌─────────────┐
                   (DRIVE/STAGE/AUDIT)              │   Docker    │
                                                    │ PostgreSQL  │
                                                    └─────────────┘
```

- **Backend** (FastAPI + Uvicorn) corre de forma nativa en el host Windows. Accede a los archivos de auditoría directamente desde el sistema de archivos local sin overhead de virtualización.
- **Base de datos** (PostgreSQL 16) corre en Docker con el puerto 5432 expuesto a `localhost`. Solo la base de datos está contenedorizada.
- **Logos de instituciones** se almacenan en la base de datos como `BYTEA` y se sirven vía `GET /api/institutions/{id}/logo` — sin volúmenes compartidos.
- El backend escucha en `0.0.0.0:8000`, por lo que cualquier dispositivo en la misma red LAN puede acceder a la app.

---

## Estructura del proyecto

```
medical-audit-v2/
├── app/
│   ├── main.py                    # Fábrica de FastAPI, lifespan, middleware, registro de routers
│   ├── config.py                  # Settings (pydantic-settings, lee desde .env)
│   ├── database.py                # Session factory async de SQLAlchemy
│   ├── crypto.py                  # Cifrado AES-256-GCM para credenciales
│   ├── paths.py                   # Conversión de rutas Windows ↔ contenedor
│   ├── models/
│   │   ├── base.py
│   │   ├── institution.py         # Institution, Administrator, Contract, Agreement, Service
│   │   ├── invoice.py             # Invoice
│   │   ├── period.py              # AuditPeriod
│   │   ├── finding.py             # MissingFile (hallazgos de auditoría)
│   │   ├── rules.py               # ServiceType, DocType, FolderStatus, PrefixCorrection, SystemSettings
│   │   └── __init__.py            # Importa todos los modelos para autogenerate de Alembic
│   ├── repositories/              # Capa de acceso a datos
│   │   ├── institution_repo.py
│   │   ├── invoice_repo.py
│   │   ├── finding_repo.py
│   │   └── rules_repo.py
│   ├── routers/
│   │   ├── pages.py               # Rutas Jinja2 (/, /audit, /settings)
│   │   └── api/
│   │       ├── hospitals.py       # /api/institutions
│   │       ├── periods.py         # /api/institutions/{id}/periods
│   │       ├── invoices.py        # /api/invoices
│   │       ├── findings.py        # /api/missing-files
│   │       ├── pipeline.py        # /api/pipeline (SSE streaming + task manager)
│   │       ├── settings.py        # /api/settings
│   │       └── explorer.py        # /api/explorer (explorador de archivos)
│   ├── services/
│   │   ├── billing.py             # Ingesta de Excel SIHOS + normalización
│   │   ├── pipeline_runner.py     # Pipeline de 20+ etapas (async generator)
│   │   └── task_manager.py        # Gestión de tareas pipeline en background
│   ├── schemas/                   # Modelos Pydantic de request/response
│   ├── static/                    # CSS y assets estáticos
│   └── templates/                 # Templates Jinja2 HTML
├── core/                          # Lógica de dominio y procesamiento de documentos
│   ├── scanner.py                 # Descubrimiento de archivos (glob/regex)
│   ├── reader.py                  # Extracción de texto PDF (PyMuPDF + pdfplumber)
│   ├── processor.py               # OCR (ocrmypdf + Tesseract)
│   ├── validator.py               # Validación de facturas (CUFE, código de factura)
│   ├── inspector.py               # Validación de estructura de carpetas
│   ├── organizer.py               # Operaciones de mover y renombrar archivos/carpetas
│   ├── standardizer.py            # Normalización de nombres de archivo
│   ├── downloader.py              # Descarga de facturas SIHOS vía Playwright
│   ├── drive.py                   # Sincronización con Google Drive
│   └── ops.py                     # Utilidades de operaciones de archivo
├── alembic/
│   └── versions/                  # Migraciones auto-generadas desde los modelos
├── seeds/
│   └── seed_data.py               # Script de datos iniciales
├── tests/
│   ├── app/
│   ├── core/
│   ├── load/
│   └── conftest.py                # Fixtures y markers de pytest
├── monitoring/
│   ├── prometheus.yml
│   └── grafana/                   # Dashboards de Grafana (solo dev)
├── nginx/
│   └── nginx.conf                 # Proxy inverso + rate limiting + SSE
├── docs/
│   └── DEPLOY.md                  # Guía de despliegue a producción
├── backups/                       # Snapshots de tablas de configuración (no en git)
├── docker-compose.yml             # Servicio PostgreSQL 16
├── docker-compose.override.yml    # Dev: Adminer, Prometheus, Grafana
├── Dockerfile                     # Multi-stage: builder + runtime
├── dev.sh                         # Script de desarrollo (./dev.sh help)
├── pyproject.toml                 # Dependencias, pytest, ruff, mypy
├── uv.lock                        # Dependencias congeladas (reproducible)
└── .env.example                   # Template de configuración
```

---

## Primeros pasos

### Prerrequisitos

- [Docker](https://docs.docker.com/get-docker/) y Docker Compose v2
- [uv](https://github.com/astral-sh/uv) para el entorno Python local

### Setup local

**1. Clonar y configurar el entorno**

```bash
git clone <repo-url>
cd medical-audit-v2
cp .env.example .env
```

Edita `.env` con tus valores locales. El `SECRET_KEY` se genera así:

```bash
python -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

**2. Iniciar la base de datos**

```bash
./dev.sh db
```

El `docker-compose.override.yml` se aplica automáticamente y levanta también Adminer en `http://localhost:8080`.

**3. Aplicar migraciones**

```bash
./dev.sh migrate
```

**4. Iniciar el backend**

```bash
./dev.sh serve
```

Uvicorn inicia con hot-reload en `0.0.0.0:8000`.

**5. Configurar la carpeta de auditoría**

La ruta base de auditoría se configura desde la interfaz: **Configuración → Sistema**.

**6. URLs de acceso**

| URL | Descripción |
|---|---|
| `http://localhost:8000` | Aplicación principal |
| `http://<ip-lan>:8000` | Acceso desde otros dispositivos en la red |
| `http://localhost:8000/docs` | Swagger UI (solo si `DOCS_ENABLED=true`) |
| `http://localhost:8080` | Adminer — UI de base de datos (solo dev) |
| `http://localhost:9090` | Prometheus (solo dev) |
| `http://localhost:3000` | Grafana (solo dev, usuario/clave: `admin`/`admin`) |

---

## Variables de entorno

Todas las variables son leídas por `app/config.py` vía pydantic-settings.

| Variable | Requerida | Default | Descripción |
|---|---|---|---|
| `DATABASE_URL` | Sí | — | Cadena de conexión asyncpg. Usar `localhost:5432` porque el backend corre nativamente. |
| `SECRET_KEY` | Sí | — | Clave de 32 bytes en base64 para cifrado AES de credenciales almacenadas. |
| `POSTGRES_USER` | Sí | — | Usuario PostgreSQL (usado por el contenedor Docker). |
| `POSTGRES_PASSWORD` | Sí | — | Contraseña PostgreSQL. |
| `POSTGRES_DB` | Sí | — | Nombre de la base de datos PostgreSQL. |
| `LOG_LEVEL` | No | `INFO` | Nivel de structlog: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `DOCS_ENABLED` | No | `false` | `true` para habilitar `/docs` y `/redoc`. Nunca activar en producción. |

> `.env` está en `.gitignore` y nunca debe commitearse. Usar `.env.example` como punto de partida.

---

## Comandos de desarrollo

El script `dev.sh` envuelve los comandos más comunes:

```bash
./dev.sh help                          # Listar todos los comandos
```

### Base de datos (Docker)

```bash
./dev.sh db                            # Iniciar PostgreSQL
./dev.sh db-down                       # Detener PostgreSQL
./dev.sh psql                          # Conectar vía psql
./dev.sh backup [nombre]               # Snapshot de tablas de config → backups/<nombre>_TIMESTAMP.sql
./dev.sh restore <archivo.sql>         # Restaurar desde snapshot
./dev.sh nuke                          # Destruir todos los volúmenes (pide confirmación)
```

### Backend (nativo)

```bash
./dev.sh start                         # Iniciar base de datos + backend juntos
./dev.sh serve                         # Iniciar uvicorn con hot-reload en 0.0.0.0:8000
./dev.sh migrate                       # Aplicar migraciones Alembic pendientes
./dev.sh migration "describe cambio"   # Generar nueva migración (auto-detecta cambios de schema)
./dev.sh seed                          # Poblar base de datos con datos iniciales
```

### Testing y calidad

```bash
./dev.sh test                          # Ejecutar pytest
./dev.sh test -k test_invoice -v       # Filtrar tests por nombre
./dev.sh test -m "not db and not slow" # Solo tests unitarios rápidos
./dev.sh test --cov=core,app           # Con reporte de cobertura
./dev.sh lint                          # ruff check + format check (seguro para CI)
./dev.sh format                        # Auto-corregir formato con ruff
./dev.sh health                        # Verificar endpoint /health
```

---

## Migraciones

El proyecto usa [Alembic](https://alembic.sqlalchemy.org/) para migraciones de schema.

```bash
# Aplicar todas las migraciones pendientes
./dev.sh migrate

# Crear una nueva migración (auto-detecta cambios en los modelos)
./dev.sh migration "descripción del cambio"

# Comandos directos de Alembic
uv run alembic current          # Ver revisión actual
uv run alembic history          # Ver historial de migraciones
uv run alembic downgrade -1     # Revertir una migración
```

---

## Backups de configuración

Las tablas de configuración (`institutions`, `service_types`, `doc_types`, `folder_statuses`, `prefix_corrections`, `admins`, `contracts`, `services`, `service_type_documents`) pueden llevar tiempo en reconstruirse. Los comandos `backup`/`restore` permiten hacer snapshots sin tocar datos operacionales (`audit_periods`, `invoices`, `missing_files`).

```bash
# Crear snapshot
./dev.sh backup configuracion_base
# → backups/configuracion_base_20260322_120000.sql

# Listar snapshots
ls -lh backups/

# Restaurar snapshot
./dev.sh restore backups/configuracion_base_20260322_120000.sql
```

Los archivos `backups/*.sql` están excluidos de git por defecto.

---

## API Reference

Todos los endpoints tienen el prefijo `/api`. Swagger UI disponible en `/docs` cuando `DOCS_ENABLED=true`.

### Instituciones — `/api/institutions`

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/institutions` | Listar todas las instituciones |
| `POST` | `/api/institutions` | Crear institución |
| `GET` | `/api/institutions/{id}` | Obtener institución por ID |
| `PATCH` | `/api/institutions/{id}` | Actualizar institución |
| `DELETE` | `/api/institutions/{id}` | Eliminar institución |
| `GET` | `/api/institutions/{id}/logo` | Servir logo (desde DB) |
| `POST` | `/api/institutions/{id}/logo` | Subir logo (PNG/JPEG/WebP/AVIF/GIF) |
| `POST` | `/api/institutions/{id}/drive-credentials` | Subir cuenta de servicio Google Drive (JSON) |
| `POST` | `/api/institutions/{id}/sihos-password` | Guardar contraseña SIHOS (cifrada en DB) |
| `GET` | `/api/institutions/{id}/admins` | Listar admins (`?pending_only=true` para sin mapear) |
| `POST` | `/api/institutions/{id}/admins` | Crear mapeo de admin |
| `PATCH` | `/api/institutions/admins/{admin_id}` | Actualizar mapeo de admin |
| `DELETE` | `/api/institutions/admins/{admin_id}` | Eliminar mapeo de admin |
| `GET` | `/api/institutions/{id}/contracts` | Listar contratos |
| `POST` | `/api/institutions/{id}/contracts` | Crear mapeo de contrato |
| `PATCH` | `/api/institutions/contracts/{contract_id}` | Actualizar mapeo de contrato |
| `DELETE` | `/api/institutions/contracts/{contract_id}` | Eliminar mapeo de contrato |
| `GET` | `/api/institutions/{id}/services` | Listar mapeos de servicio |
| `POST` | `/api/institutions/{id}/services` | Crear mapeo de servicio |
| `PATCH` | `/api/institutions/services/{service_id}` | Actualizar mapeo de servicio |
| `DELETE` | `/api/institutions/services/{service_id}` | Eliminar mapeo de servicio |
| `GET` | `/api/institutions/{id}/service-type-documents` | Listar documentos requeridos por tipo de servicio |
| `POST` | `/api/institutions/{id}/service-type-documents` | Agregar documento requerido a tipo de servicio |
| `DELETE` | `/api/institutions/{id}/service-type-documents/{st_id}/{dt_id}` | Quitar documento requerido |

### Periodos de auditoría — `/api/institutions/{id}/periods`

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/institutions/{id}/periods` | Listar periodos de la institución |
| `POST` | `/api/institutions/{id}/periods` | Crear periodo |
| `DELETE` | `/api/periods/{id}` | Eliminar periodo |

### Facturas — `/api/invoices`

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/invoices` | Listar facturas (filtros: periodo, estado, admin, contrato, servicio, búsqueda) |
| `GET` | `/api/invoices/ids` | IDs de facturas que coinciden con los filtros actuales |
| `GET` | `/api/invoices/stats` | Conteos por estado y total de hallazgos |
| `GET` | `/api/invoices/findings-summary` | Conteo de hallazgos sin resolver por tipo de documento |
| `GET` | `/api/invoices/export` | Exportar facturas del periodo a Excel (.xlsx) |
| `GET` | `/api/invoices/{id}` | Detalle de una factura |
| `POST` | `/api/invoices` | Crear factura |
| `PATCH` | `/api/invoices/{id}` | Actualizar factura (estado, tipo de servicio) |
| `POST` | `/api/invoices/ingest` | Ingestar Excel SIHOS (multipart) |
| `POST` | `/api/invoices/batch-status` | Actualización masiva de estados |
| `DELETE` | `/api/invoices/{id}` | Eliminar factura |
| `POST` | `/api/invoices/{id}/rename-surplus` | Renombrar archivo sobrante al prefijo correcto y resolver hallazgo |
| `POST` | `/api/invoices/{id}/delete-surplus` | Eliminar archivo sobrante del disco |

### Hallazgos — `/api/missing-files`

Registros de documentos requeridos faltantes por factura.

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/missing-files/{invoice_id}` | Obtener hallazgos de una factura |
| `POST` | `/api/missing-files` | Registrar hallazgo |
| `PATCH` | `/api/missing-files/{invoice_id}/{doc_type_id}/resolve` | Marcar hallazgo como resuelto |
| `DELETE` | `/api/missing-files/{invoice_id}/{doc_type_id}` | Eliminar hallazgo |
| `DELETE` | `/api/missing-files/{invoice_id}` | Eliminar todos los hallazgos de una factura |
| `POST` | `/api/missing-files/batch-delete` | Eliminación masiva de hallazgos |

### Pipeline — `/api/pipeline`

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/pipeline/run/{stage}` | Ejecutar etapa; retorna stream **Server-Sent Events** |
| `POST` | `/api/pipeline/run/{stage}` | Iniciar etapa en background (retorna `task_id`) |
| `GET` | `/api/pipeline/task/{task_id}` | Consultar estado de tarea en background |
| `GET` | `/api/pipeline/stream/{task_id}` | Stream de logs de tarea en background (SSE) |

### Configuración — `/api/settings`

| Método | Ruta | Descripción |
|---|---|---|
| `GET/POST` | `/api/settings/service-types` | Listar / crear tipos de servicio |
| `PATCH/DELETE` | `/api/settings/service-types/{id}` | Actualizar / eliminar tipo de servicio |
| `GET/POST` | `/api/settings/doc-types` | Listar / crear tipos de documento |
| `PATCH/DELETE` | `/api/settings/doc-types/{id}` | Actualizar / eliminar tipo de documento |
| `GET/POST` | `/api/settings/folder-statuses` | Listar / crear estados de carpeta |
| `PATCH/DELETE` | `/api/settings/folder-statuses/{id}` | Actualizar / eliminar estado de carpeta |
| `GET/POST` | `/api/settings/prefix-corrections` | Listar / crear reglas de corrección de prefijos |
| `PATCH/DELETE` | `/api/settings/prefix-corrections/{id}` | Actualizar / eliminar regla |
| `GET` | `/api/settings/system` | Obtener configuración global del sistema |
| `PATCH` | `/api/settings/system` | Actualizar ruta base de auditoría y otras opciones globales |

### Explorador de archivos — `/api/explorer`

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/explorer/list` | Listar archivos y carpetas en el sandbox |
| `POST` | `/api/explorer/mkdir` | Crear carpeta |
| `POST` | `/api/explorer/upload` | Subir archivo |
| `POST` | `/api/explorer/delete` | Eliminar archivo o carpeta |
| `POST` | `/api/explorer/rename` | Renombrar archivo o carpeta |
| `POST` | `/api/explorer/move` | Mover a otra carpeta |
| `POST` | `/api/explorer/copy` | Copiar archivo o carpeta |
| `POST` | `/api/explorer/merge` | Fusionar carpetas de factura |
| `POST` | `/api/explorer/split` | Dividir carpeta de factura |
| `POST` | `/api/explorer/reorder` | Reordenar archivos dentro de una carpeta |
| `POST` | `/api/explorer/batch-delete` | Eliminar múltiples ítems |
| `GET` | `/api/explorer/download` | Descargar archivos/carpetas como ZIP |

---

## Pipeline de auditoría

El pipeline está compuesto por etapas secuenciales. Cada etapa se activa individualmente vía `GET /api/pipeline/run/{NOMBRE_ETAPA}` y retorna líneas de log como Server-Sent Events (`[INFO]`, `[WARN]`, `[ERROR]`).

| # | Nombre de etapa | Descripción |
|---|---|---|
| 1 | `LOAD_AND_PROCESS` | Ingestar Excel SIHOS → upsert de facturas en DB. Para facturas con múltiples servicios, se aplica el tipo de servicio con **mayor prioridad configurada**. |
| 2 | `RECATEGORIZE_SERVICES` | Re-aplicar los mapeos de servicio actuales sin re-importar el Excel. |
| 3 | `RUN_STAGING` | Copiar carpetas hoja (que contienen archivos directamente) desde DRIVE a STAGE. |
| 4 | `CHECK_NESTED_FOLDERS` | Detectar carpetas en STAGE que contienen subcarpetas anidadas — requieren aplanamiento manual. |
| 5 | `REMOVE_NON_PDF` | Eliminar archivos no-PDF y PDFs corruptos de STAGE. |
| 6 | `NORMALIZE_FILES` | Aplicar reglas de `PrefixCorrection` + estandarización genérica de nombres de archivo. |
| 7 | `LIST_UNREADABLE_PDFS` | Identificar PDFs de factura sin capa de texto (candidatos a OCR). |
| 8 | `DELETE_UNREADABLE_PDFS` | Eliminar PDFs de factura que no se pueden leer ni siquiera con OCR. |
| 9 | `DOWNLOAD_INVOICES_FROM_SIHOS` | Descargar facturas faltantes desde SIHOS vía automatización Playwright. |
| 10 | `DOWNLOAD_MEDICATION_SHEETS` | Descargar hojas de medicamentos/servicios específicos desde SIHOS. |
| 11 | `CHECK_INVOICES` | Aplicar OCR (`ocrmypdf`, batch size 8) a PDFs escaneados. |
| 12 | `VERIFY_INVOICE_CODE` | Confirmar que cada PDF de factura contiene su propio número de factura en el texto extraído. |
| 13 | `CHECK_INVOICE_NUMBER_ON_FILES` | Verificar que los archivos dentro de cada carpeta corresponden al número de factura de esa carpeta. |
| 14 | `CHECK_FOLDERS_WITH_EXTRA_TEXT` | Detectar carpetas con texto adicional pegado al nombre canónico. |
| 15 | `NORMALIZE_DIR_NAMES` | Renombrar carpetas malformadas al ID canónico de factura. |
| 16 | `CHECK_DIRS` | Reconciliar facturas en DB vs. carpetas en disco; marcar faltantes como `FALTANTE`. |
| 17 | `MARK_UNKNOWN_DIRS` | Validar documentos requeridos por tipo de servicio; registrar hallazgos; marcar `PENDIENTE`. |
| 18 | `REVISAR_SOBRANTES` | Revisar archivos cuyos nombres no coinciden con ningún prefijo requerido. Para cada sobrante, sugiere el tipo de documento faltante más probable (1:1 → alta confianza; N:M vía similitud `difflib` → baja confianza). El panel interactivo permite confirmar o corregir la sugerencia para renombrar el archivo en disco y resolver el hallazgo, o eliminar el archivo. |
| 19 | `VERIFY_CUFE` | Verificar el código CUFE (64+ caracteres) de factura electrónica colombiana en los PDFs. |
| 20 | `ORGANIZE` | Mover facturas elegibles (`PRESENTE`, sin hallazgos) al destino de auditoría; marcar `AUDITADA`. |
| 21 | `DOWNLOAD_DRIVE` | Sincronizar carpetas `FALTANTE` desde Google Drive; actualizar estado a `PRESENTE`. |
| 22 | `DOWNLOAD_MISSING_DOCS` | Descargar documentos faltantes específicos desde Drive para facturas con hallazgos abiertos. |
| 23 | `COMPRESS_AUDIT` | Comprimir el directorio de auditoría en un archivo ZIP. |

---

## Modelo de dominio

### Estados de carpeta de factura

| Estado | Significado |
|---|---|
| `PRESENTE` | La carpeta existe en disco |
| `FALTANTE` | Carpeta no encontrada en disco ni en Drive |
| `AUDITADA` | Completamente validada y movida al destino de auditoría |
| `PENDIENTE` | Presente pero con hallazgos de documentos abiertos |
| `REVISAR` | Marcada para revisión manual |
| `ANULAR` | Marcada para anulación |

### Entidades principales

| Entidad | Descripción |
|---|---|
| **Institution** | Hospital/clínica con NIT, credenciales SIHOS (cifradas), credenciales Drive (cifradas), logo (`BYTEA`) |
| **AuditPeriod** | Periodo de facturación que agrupa un conjunto de facturas por institución |
| **Invoice** | Registro de factura importado desde SIHOS; vinculado a Admin, Contrato, ServiceType y FolderStatus |
| **Administrator** | Mapeo de string raw de SIHOS → nombre canónico de administrador por institución |
| **Contract** | Mapeo de string raw de SIHOS → nombre canónico de contrato por institución |
| **Agreement** | Vincula un par (Administrador, Contrato) a una institución |
| **Service** | Mapeo de servicio raw de SIHOS → ServiceType por institución |
| **ServiceType** | Categoría de servicio médico (hospitalización, ambulatorio, etc.); define qué documentos son requeridos vía `ServiceTypeDocument` |
| **DocType** | Tipo de documento requerido con prefijo canónico de nombre de archivo |
| **ServiceTypeDocument** | Entidad de unión que vincula un ServiceType con un DocType requerido por institución |
| **MissingFile** | Hallazgo: documento requerido faltante para una factura específica |
| **PrefixCorrection** | Mapeo de prefijo incorrecto → forma canónica correcta (ej. `OPD_` → `OPF_`) |
| **SystemSettings** | Configuración global del sistema (ruta raíz de auditoría, etc.) |

---

## Testing

### Framework

pytest + pytest-asyncio con cobertura mínima de 60% en `core/` y `app/`.

### Markers

```python
@pytest.mark.db       # Requiere PostgreSQL activo (lento, puede modificar DB)
@pytest.mark.slow     # Tests de larga duración (OCR, archivos grandes)
@pytest.mark.pdf      # Requiere fixtures PDF reales
```

### Comandos

```bash
./dev.sh test                                    # Todos los tests
./dev.sh test tests/core/test_scanner.py         # Archivo específico
./dev.sh test -k "test_validate"                 # Tests que coincidan con el patrón
./dev.sh test -m "not db and not slow"           # Solo tests unitarios rápidos
./dev.sh test --cov=core,app --cov-report=html   # Con reporte de cobertura HTML

# Type checking (sin wrapper en dev.sh)
uv run mypy app/
```

---

## Seguridad

- **`.env` nunca se commitea** — está en `.gitignore`. Usar `.env.example` como plantilla.
- **Variables requeridas son obligatorias** — `docker-compose.yml` usa sintaxis `:?` para `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`. Si alguna falta, Docker Compose aborta con error explícito.
- **Secretos cifrados en reposo** — contraseñas SIHOS y credenciales de Google Drive se almacenan en DB con cifrado AES-256-GCM vía `app/crypto.py`. La clave proviene de `SECRET_KEY`.
- **Logos almacenados en DB** — los logos de instituciones se guardan como `BYTEA` en PostgreSQL y se sirven vía API, sin volúmenes compartidos.
- **Contenedor sin root** — la imagen Docker corre como `appuser`, no como `root`.
- **Sin exposición directa de la DB** — PostgreSQL solo es accesible dentro de la red Docker.
- **Swagger deshabilitado por defecto** — `DOCS_ENABLED=false` en producción evita exponer la documentación de la API.
- **Rate limiting** — Nginx limita las peticiones API a 30 req/s por IP (burst de 20).
- **Historial git limpio** — ninguna credencial ni secreto ha sido commiteado al repositorio.

---

## Monitoreo

### Logs estructurados (structlog)

Todos los logs incluyen campos de contexto (`method`, `path`, `status`, `latency_ms`). Nivel configurable vía `LOG_LEVEL`. Las rutas `/health`, `/health/db`, `/metrics` y `/static` están excluidas del logging de requests.

### Métricas Prometheus

Disponibles en `/metrics`. Incluyen duración de requests HTTP, distribución de códigos de estado y conteo de requests. El endpoint es excluido del schema OpenAPI.

### Health checks

| Endpoint | Descripción |
|---|---|
| `GET /health` | Health básico (siempre 200 si el proceso está corriendo) |
| `GET /health/db` | Health con verificación de conexión a DB (503 si la DB no está disponible) |

### Dashboards de desarrollo

```bash
# Levantar stack de monitoreo (dev only)
docker compose up -d  # incluye Prometheus y Grafana vía docker-compose.override.yml
```

- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000` (usuario: `admin`, clave: `admin`)

> Para el despliegue a producción, ver **[docs/DEPLOY.md](docs/DEPLOY.md)**.
