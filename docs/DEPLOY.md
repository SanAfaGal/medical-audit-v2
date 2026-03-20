# Deploy a producción

> **Entorno de referencia:** backend corre en Windows nativo (no en Docker), base de datos en Docker. Un solo servidor. Deploy siempre manual después de CI verde.

---

## Pre-requisitos

- CI verde en GitHub Actions (jobs `quality` y `test-unit` bloqueantes)
- Acceso al servidor (sesión Windows activa o RDP)
- Proceso uvicorn identificado (ver paso 6)

---

## Checklist paso a paso

### 1. Verificar que CI está verde

```
GitHub → Actions → último commit en master → todos los checks verdes
```

No hacer deploy si `quality` o `test-unit` están en rojo.

### 2. Bajar los cambios

```bash
cd C:\ruta\al\proyecto\medical-audit-v2
git pull origin master
```

### 3. Actualizar dependencias (solo si cambió `pyproject.toml`)

```bash
uv sync
```

Si no hubo cambios en dependencias, omitir este paso.

### 4. Aplicar migraciones (solo si hay migraciones nuevas)

```bash
./dev.sh migrate
```

Cómo saber si hay migraciones nuevas:

```bash
git log --oneline origin/master..HEAD -- alembic/versions/
# Si muestra líneas → hay migraciones que aplicar
```

> **Importante:** las migraciones son irreversibles en prod. Si la migración es destructiva (drop column, truncate), hacer backup primero:
> ```bash
> ./dev.sh backup pre-deploy
> ```

### 5. Reiniciar el proceso uvicorn

Localizar y terminar el proceso actual, luego volver a iniciar:

```bash
# Opción A — si está corriendo en una terminal, Ctrl+C y luego:
./dev.sh serve

# Opción B — si está corriendo en background (nohup / Task Scheduler):
# Buscar PID y terminarlo, luego relanzar con nohup
nohup uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 > logs/uvicorn.log 2>&1 &
```

### 6. Verificar que la app levantó correctamente

```bash
./dev.sh health
```

Salida esperada:

```
✔  /health        → 200 OK
✔  /health/db     → 200 OK  (DB latency: X ms)
```

Si `/health/db` falla → el contenedor de PostgreSQL puede no estar corriendo:

```bash
./dev.sh db   # levantar si estaba apagado
```

### 7. Verificar logs

```bash
# Si usaste nohup:
tail -f logs/uvicorn.log

# Buscar errores de startup:
grep -i "error\|exception" logs/uvicorn.log | head -20
```

---

## Rollback

Si algo falla después del deploy:

```bash
# 1. Volver al commit anterior
git log --oneline -5          # identificar commit previo
git checkout <commit-hash>    # o: git reset --hard HEAD~1

# 2. Si hubo migración: restaurar backup
./dev.sh restore backups/pre-deploy_TIMESTAMP.sql

# 3. Reiniciar uvicorn con el código anterior
./dev.sh serve
```

---

## Frecuencia esperada

| Acción | Frecuencia |
|--------|-----------|
| `git pull` + reiniciar uvicorn | Cada deploy |
| `uv sync` | Solo si cambió `pyproject.toml` |
| `./dev.sh migrate` | Solo si hay nuevas migraciones |
| `./dev.sh backup pre-deploy` | Antes de migraciones destructivas |

---

## Accesos post-deploy

| URL | Descripción |
|-----|-------------|
| `http://localhost:8000` | Aplicación principal |
| `http://localhost:8000/health` | Health check |
| `http://localhost:8000/health/db` | Health check con DB |
| `http://localhost:8000/metrics` | Métricas Prometheus |
| `http://localhost:3000` | Grafana (requiere `docker compose up -d`) |
