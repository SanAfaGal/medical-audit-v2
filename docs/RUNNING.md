# Cómo ejecutar el proyecto

Hay dos modos de ejecución. Usa el que corresponda a tu situación.

---

## Prerrequisitos comunes

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) instalado y corriendo
- [uv](https://docs.astral.sh/uv/getting-started/installation/) instalado (solo para modo desarrollo)

---

## Modo desarrollo — nativo en Windows

El backend corre directamente en Windows con hot-reload. Solo la base de datos está en Docker.

### 1. Configurar el entorno

```bash
cp .env.example .env
```

Edita `.env`. El único valor que **debes generar** es `SECRET_KEY`:

```bash
python -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

Ejemplo de `.env` para desarrollo:

```env
DATABASE_URL=postgresql+asyncpg://audit:tu_password@localhost:5432/medical_audit
SECRET_KEY=<resultado del comando anterior>
POSTGRES_USER=audit
POSTGRES_PASSWORD=tu_password
POSTGRES_DB=medical_audit
LOG_LEVEL=INFO
DOCS_ENABLED=true
```

### 2. Instalar dependencias Python

```bash
uv sync
```

### 3. Iniciar la base de datos

```bash
./dev.sh db
```

Esto levanta el contenedor `medical-audit-dev-db` en el puerto `5432`.

### 4. Aplicar migraciones

```bash
./dev.sh migrate
```

### 5. (Opcional) Cargar datos iniciales

```bash
./dev.sh seed
```

### 6. Iniciar el backend

```bash
./dev.sh serve
```

### URLs disponibles

| URL | Descripción |
|---|---|
| `http://localhost:8000` | Aplicación principal |
| `http://localhost:8000/docs` | Swagger UI (`DOCS_ENABLED=true`) |
| `http://localhost:8080` | Adminer — UI de base de datos |
| `http://localhost:9090` | Prometheus |
| `http://localhost:3000` | Grafana (usuario: `admin` / clave: `admin`) |

### Detener

```bash
./dev.sh db-down   # detiene solo la base de datos
# Ctrl+C           # detiene el backend
```

---

## Modo producción — stack completo en Docker

Backend + base de datos + Nginx, todo en contenedores. Un solo comando para levantar todo.

### 1. Configurar el entorno

```bash
cp .env.example .env
```

Edita `.env` con valores de producción. `DOCS_ENABLED` debe ser `false`:

```env
DATABASE_URL=postgresql+asyncpg://audit:tu_password@localhost:5432/medical_audit
SECRET_KEY=<genera con el comando de arriba>
POSTGRES_USER=audit
POSTGRES_PASSWORD=tu_password_segura
POSTGRES_DB=medical_audit
LOG_LEVEL=INFO
DOCS_ENABLED=false
```

> `DATABASE_URL` en el archivo `.env` es para el backend nativo. En el compose de producción la URL se construye automáticamente desde las variables `POSTGRES_*` — no necesitas cambiarla.

### 2. Construir e iniciar

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

La primera vez el build tarda varios minutos (descarga `jbarlow83/ocrmypdf` + instala Playwright Chromium).

### 3. Aplicar migraciones

```bash
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head
```

### 4. Configurar la ruta de auditoría

Abre `http://localhost` → **Configuración → Sistema** y establece:

```
audit_data_root = /audit_data
```

Esta ruta apunta al volumen Docker donde se almacenan todos los archivos de auditoría.

### URLs disponibles

| URL | Descripción |
|---|---|
| `http://localhost` | Aplicación principal (via Nginx, puerto 80) |
| `http://localhost/health` | Health check básico |
| `http://localhost/health/db` | Health check con verificación de DB |

### Contenedores que se levantan

| Contenedor | Imagen | Descripción |
|---|---|---|
| `medical-audit-prod-db` | `postgres:16-alpine` | Base de datos PostgreSQL |
| `medical-audit-prod-backend` | `jbarlow83/ocrmypdf` + app | FastAPI + OCR + Playwright |
| `medical-audit-prod-nginx` | `nginx:1.27-alpine` | Proxy inverso, rate limiting, gzip |

### Comandos de gestión

```bash
# Ver estado de los contenedores
docker compose -f docker-compose.prod.yml ps

# Ver logs en tiempo real
docker compose -f docker-compose.prod.yml logs -f

# Ver logs solo del backend
docker compose -f docker-compose.prod.yml logs -f backend

# Detener sin borrar datos
docker compose -f docker-compose.prod.yml down

# Detener y borrar volúmenes (DESTRUYE todos los datos)
docker compose -f docker-compose.prod.yml down -v

# Reconstruir la imagen del backend (después de cambios en el código)
docker compose -f docker-compose.prod.yml up -d --build backend

# Abrir una shell dentro del backend
docker compose -f docker-compose.prod.yml exec backend bash

# Conectar a la base de datos
docker compose -f docker-compose.prod.yml exec db psql -U audit -d medical_audit
```

---

## Convivencia de ambos modos

Los dos stacks usan nombres de proyecto distintos y **no se interfieren**:

| | Desarrollo | Producción |
|---|---|---|
| Proyecto Docker | `medical-audit-dev` | `medical-audit-prod` |
| Contenedor DB | `medical-audit-dev-db` | `medical-audit-prod-db` |
| Puerto expuesto DB | `5432` | ninguno (solo red interna) |
| Puerto app | `8000` (directo) | `80` (via Nginx) |
| Volumen DB | `medical-audit-dev_pgdata` | `medical-audit-prod_pgdata` |

Puedes tener ambos corriendo al mismo tiempo sin conflictos.

---

## Comandos dev.sh (referencia rápida)

```bash
./dev.sh help                        # lista todos los comandos
./dev.sh db                          # iniciar PostgreSQL (dev)
./dev.sh db-down                     # detener PostgreSQL (dev)
./dev.sh serve                       # backend con hot-reload
./dev.sh migrate                     # aplicar migraciones
./dev.sh migration "describe cambio" # generar nueva migración
./dev.sh seed                        # cargar datos iniciales
./dev.sh test                        # ejecutar pytest
./dev.sh test -m "not db and not slow" # tests rápidos sin DB
./dev.sh lint                        # verificar estilo (ruff)
./dev.sh format                      # auto-formatear código
./dev.sh health                      # verificar /health
./dev.sh backup [nombre]             # snapshot de tablas de configuración
./dev.sh restore <archivo.sql>       # restaurar snapshot
```
