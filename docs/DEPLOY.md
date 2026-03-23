# Despliegue a producción

Stack: `docker-compose.prod.yml` — tres contenedores orquestados, datos persistentes en volúmenes Docker nombrados, completamente aislado del entorno de desarrollo.

---

## Requisitos del servidor

| Requisito | Mínimo | Recomendado |
|---|---|---|
| OS | Windows 10 / Ubuntu 22.04 | Ubuntu 22.04 LTS |
| RAM | 2 GB | 4 GB |
| CPU | 2 núcleos | 4 núcleos |
| Disco | 20 GB libres | 50 GB libres |
| Docker | Desktop 4.x / Engine 24.x | Engine 24.x |
| Docker Compose | v2.20+ | v2.20+ |

> **En Windows:** Docker Desktop debe estar corriendo antes de ejecutar cualquier comando.

---

## Primer despliegue — paso a paso

### 1. Clonar el repositorio

```bash
git clone <repo-url>
cd medical-audit-v2
```

### 2. Configurar el entorno

```bash
cp .env.example .env
```

Editar `.env` con los valores de producción:

```env
# Base de datos — en producción Docker resuelve "db" internamente, este valor
# solo importa si alguna vez corres el backend fuera del compose
DATABASE_URL=postgresql+asyncpg://audit:PASSWORD_SEGURA@localhost:5432/medical_audit

# Clave de cifrado AES — generar con:
# python -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
SECRET_KEY=REEMPLAZAR_CON_CLAVE_GENERADA

# Credenciales de PostgreSQL (usadas por el contenedor db)
POSTGRES_USER=audit
POSTGRES_PASSWORD=PASSWORD_SEGURA
POSTGRES_DB=medical_audit

# Opcionales
LOG_LEVEL=INFO
DOCS_ENABLED=false
```

> Nunca commitear `.env`. Verificar que está en `.gitignore` antes de continuar.

### 3. Construir las imágenes

```bash
docker compose -f docker-compose.prod.yml build
```

La primera vez tarda 5-15 minutos: descarga la imagen base `jbarlow83/ocrmypdf`, instala el venv de Python, y descarga Playwright Chromium (~300 MB).

Progreso esperado:
```
[+] Building
 => [full 1/7] FROM jbarlow83/ocrmypdf
 => [full 2/7] COPY pyproject.toml uv.lock
 => [full 3/7] RUN uv sync ...
 => [full 4/7] COPY app/ core/ alembic/
 => [full 5/7] RUN playwright install chromium
 => [full 6/7] RUN useradd appuser
 => exporting to image
```

### 4. Iniciar los contenedores

```bash
docker compose -f docker-compose.prod.yml up -d
```

Verifica que los tres contenedores están corriendo:

```bash
docker compose -f docker-compose.prod.yml ps
```

Salida esperada:
```
NAME                          IMAGE                    STATUS
medical-audit-prod-db         postgres:16-alpine       running (healthy)
medical-audit-prod-backend    medical-audit-prod-...   running (healthy)
medical-audit-prod-nginx      nginx:1.27-alpine        running
```

> Si `medical-audit-prod-db` aparece como `starting` espera unos segundos — el healthcheck de PostgreSQL tarda hasta 50 segundos en pasar.

### 5. Aplicar migraciones de base de datos

```bash
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head
```

### 6. Verificar que la aplicación responde

```bash
# Desde el mismo servidor:
curl http://localhost/health
curl http://localhost/health/db

# Desde otro dispositivo en la red (reemplazar con la IP del servidor):
curl http://192.168.1.X/health
```

Respuesta esperada en ambos: `{"status": "ok"}`

### 7. Configurar la ruta de auditoría

Abrir la aplicación en el navegador → **Configuración → Sistema** → establecer:

```
audit_data_root = /audit_data
```

Esta ruta apunta al volumen Docker `medical-audit-prod_audit_data` donde se almacenan todos los archivos de auditoría (DRIVE, STAGE, AUDIT, exports).

---

## Arquitectura en producción

```
  Dispositivos LAN
        │
        ▼ :80
  ┌─────────────────────┐
  │  medical-audit-prod │  Docker network: medical-audit-prod_default
  │  ─────────────────  │
  │  nginx :80          │──► backend :8000 ──► db :5432
  │  (rate limit, gzip) │
  │  (SSE timeout 4h)   │
  └─────────────────────┘
        │                         │                    │
   puerto 80                 sin puerto           sin puerto
   expuesto                  al host              al host
   al host
```

- **nginx** es el único punto de entrada. Gestiona rate limiting (30 req/s), gzip, y timeouts especiales para SSE del pipeline.
- **backend** nunca es accesible directamente desde fuera del stack Docker.
- **db** solo es accesible desde `backend` dentro de la red Docker.

---

## Actualizar a una nueva versión

```bash
# 1. Verificar CI verde en GitHub Actions

# 2. Backup preventivo (obligatorio antes de cada deploy)
./scripts/backup-config.sh   # ver sección Backups

# 3. Bajar los cambios
git pull origin master

# 4. Reconstruir e iniciar (solo reconstruye lo que cambió)
docker compose -f docker-compose.prod.yml up -d --build

# 5. Aplicar migraciones si las hay
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head

# 6. Verificar
curl http://localhost/health
curl http://localhost/health/db
docker compose -f docker-compose.prod.yml logs --tail=30 backend
```

---

## Rollback

### Sin migraciones de base de datos

```bash
git checkout <commit-anterior>
docker compose -f docker-compose.prod.yml up -d --build backend
```

### Con migraciones de base de datos

```bash
# 1. Restaurar backup de configuración tomado antes del deploy
docker compose -f docker-compose.prod.yml exec -T db psql \
  -U audit medical_audit < backups/pre-deploy_TIMESTAMP.sql

# 2. Revertir la migración de Alembic
docker compose -f docker-compose.prod.yml exec backend alembic downgrade -1

# 3. Volver al código anterior
git checkout <commit-anterior>
docker compose -f docker-compose.prod.yml up -d --build backend
```

---

## Backups

Los datos críticos están en dos lugares: la base de datos PostgreSQL y el volumen `audit_data` (PDFs).

### Backup de tablas de configuración

Las tablas de configuración (instituciones, tipos de servicio, mapeos, reglas) son las más difíciles de reconstruir. Se recomienda hacer este backup antes de cada deploy y al terminar cada sesión de configuración.

```bash
mkdir -p backups

docker compose -f docker-compose.prod.yml exec -T db pg_dump \
  -U audit \
  --data-only \
  -t institutions \
  -t service_types -t doc_types -t folder_statuses \
  -t prefix_corrections \
  -t admins -t contracts -t services -t service_type_documents \
  medical_audit > backups/config_$(date +%Y%m%d_%H%M%S).sql

echo "Backup de configuración guardado en backups/"
```

### Backup completo de la base de datos

Incluye todo: configuración + periodos + facturas + hallazgos.

```bash
mkdir -p backups

docker compose -f docker-compose.prod.yml exec -T db pg_dump \
  -U audit \
  --format=custom \
  medical_audit > backups/full_$(date +%Y%m%d_%H%M%S).dump
```

> `--format=custom` genera un archivo binario comprimido. Para restaurarlo se usa `pg_restore`.

### Backup del volumen de auditoría (PDFs)

```bash
mkdir -p backups

docker run --rm \
  -v medical-audit-prod_audit_data:/data:ro \
  -v "$(pwd)/backups":/backups \
  alpine tar czf /backups/audit_data_$(date +%Y%m%d_%H%M%S).tar.gz -C /data .
```

---

### Restaurar tablas de configuración

```bash
docker compose -f docker-compose.prod.yml exec -T db psql \
  -U audit medical_audit < backups/config_TIMESTAMP.sql
```

### Restaurar base de datos completa

```bash
# Detener el backend para evitar escrituras durante la restauración
docker compose -f docker-compose.prod.yml stop backend

docker compose -f docker-compose.prod.yml exec -T db pg_restore \
  -U audit \
  --clean --if-exists \
  -d medical_audit < backups/full_TIMESTAMP.dump

docker compose -f docker-compose.prod.yml start backend
```

### Restaurar volumen de auditoría

```bash
docker run --rm \
  -v medical-audit-prod_audit_data:/data \
  -v "$(pwd)/backups":/backups \
  alpine tar xzf /backups/audit_data_TIMESTAMP.tar.gz -C /data
```

---

### Automatizar backups diarios

**En Linux (cron):**

```bash
crontab -e
```

Agregar:
```
0 2 * * * cd /ruta/al/proyecto && docker compose -f docker-compose.prod.yml exec -T db pg_dump -U audit --format=custom medical_audit > backups/full_$(date +\%Y\%m\%d).dump
```

**En Windows (Task Scheduler):**

Crear `scripts/backup-daily.bat`:
```bat
@echo off
cd /d C:\ruta\al\proyecto\medical-audit-v2
set STAMP=%date:~-4,4%%date:~-7,2%%date:~0,2%
mkdir backups 2>nul
docker compose -f docker-compose.prod.yml exec -T db pg_dump ^
  -U audit --format=custom medical_audit ^
  > backups\full_%STAMP%.dump
```

Programar en **Task Scheduler → Create Basic Task → Daily → 02:00**.

---

## Gestión de contenedores

```bash
# Ver estado de todos los contenedores
docker compose -f docker-compose.prod.yml ps

# Ver logs en tiempo real
docker compose -f docker-compose.prod.yml logs -f

# Ver logs solo del backend
docker compose -f docker-compose.prod.yml logs -f backend

# Reiniciar un servicio (sin reconstruir imagen)
docker compose -f docker-compose.prod.yml restart backend

# Abrir shell dentro del backend
docker compose -f docker-compose.prod.yml exec backend bash

# Conectar directamente a la base de datos
docker compose -f docker-compose.prod.yml exec db psql -U audit -d medical_audit

# Detener todos los contenedores (conserva volúmenes y datos)
docker compose -f docker-compose.prod.yml down

# Detener y borrar TODOS los datos — IRREVERSIBLE
docker compose -f docker-compose.prod.yml down -v
```

---

## Acceso desde la red LAN

La aplicación es accesible desde cualquier dispositivo en la misma red local.

```bash
# Obtener la IP del servidor (Windows)
ipconfig   # buscar "IPv4 Address"

# Obtener la IP del servidor (Linux)
ip addr show | grep "inet "
```

Si no responde desde otros dispositivos, abrir el puerto 80 en el firewall:

```powershell
# Windows — ejecutar como Administrador
New-NetFirewallRule -DisplayName "Medical Audit Prod" -Direction Inbound -Protocol TCP -LocalPort 80 -Action Allow
```

```bash
# Ubuntu/Debian
sudo ufw allow 80/tcp
```

---

## Referencia de contenedores y volúmenes

| Contenedor | Imagen | Rol |
|---|---|---|
| `medical-audit-prod-db` | `postgres:16-alpine` | Base de datos PostgreSQL |
| `medical-audit-prod-backend` | `jbarlow83/ocrmypdf` + app | FastAPI + OCR + Playwright |
| `medical-audit-prod-nginx` | `nginx:1.27-alpine` | Proxy inverso, rate limiting, gzip |

| Volumen | Contenido | Crítico |
|---|---|---|
| `medical-audit-prod_pgdata` | Datos de PostgreSQL | Sí — respaldar diariamente |
| `medical-audit-prod_audit_data` | PDFs auditados, ZIPs exportados | Medio — recuperables desde Drive |
