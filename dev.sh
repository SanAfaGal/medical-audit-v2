#!/usr/bin/env bash
set -euo pipefail

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

# Check .env at startup
if [[ ! -f .env ]]; then
  echo -e "${YELLOW}[warn] .env not found — copy .env.example and fill in values${NC}"
fi

CMD="${1:-help}"
shift || true  # remaining args available as "$@"

case "$CMD" in
  up)
    echo -e "${GREEN}Starting services...${NC}"
    docker compose up -d
    ;;

  down)
    echo -e "${YELLOW}Stopping services...${NC}"
    docker compose down
    ;;

  restart)
    echo -e "${YELLOW}Restarting services...${NC}"
    docker compose restart "$@"
    ;;

  build)
    echo -e "${YELLOW}Building images (with cache)...${NC}"
    docker compose build && docker compose up -d
    echo -e "${GREEN}Build complete.${NC}"
    ;;

  rebuild)
    echo -e "${YELLOW}Rebuilding images (no cache)...${NC}"
    docker compose build --no-cache && docker compose up -d
    echo -e "${GREEN}Rebuild complete.${NC}"
    ;;

  logs)
    docker compose logs -f --tail=100 "${1:-}"
    ;;

  status)
    docker compose ps
    ;;

  migrate)
    echo -e "${CYAN}Running migrations...${NC}"
    docker compose exec backend alembic upgrade head
    echo -e "${GREEN}Migrations applied.${NC}"
    ;;

  migration)
    if [[ -z "${1:-}" ]]; then
      echo -e "${RED}[error] Usage: ./dev.sh migration <message>${NC}" >&2
      exit 1
    fi
    echo -e "${CYAN}Generating migration: $1${NC}"
    docker compose exec backend alembic revision --autogenerate -m "$1"
    ;;

  seed)
    echo -e "${CYAN}Seeding database...${NC}"
    docker compose exec backend python seeds/seed_data.py
    echo -e "${GREEN}Seed complete.${NC}"
    ;;

  test)
    echo -e "${CYAN}Running tests...${NC}"
    docker compose exec backend pytest "$@"
    ;;

  lint)
    echo -e "${CYAN}Linting...${NC}"
    uv run ruff check . && uv run ruff format --check .
    echo -e "${GREEN}Lint passed.${NC}"
    ;;

  format)
    echo -e "${CYAN}Formatting...${NC}"
    uv run ruff format .
    echo -e "${GREEN}Format complete.${NC}"
    ;;

  shell)
    echo -e "${CYAN}Opening shell in backend container...${NC}"
    docker compose exec backend sh
    ;;

  psql)
    # shellcheck disable=SC1091
    source .env 2>/dev/null || true
    echo -e "${CYAN}Connecting to PostgreSQL...${NC}"
    docker compose exec db psql -U "${POSTGRES_USER}" "${POSTGRES_DB}"
    ;;

  health)
    echo -e "${CYAN}Checking health...${NC}"
    curl -s http://localhost/health | python3 -m json.tool
    ;;

  backup)
    # shellcheck disable=SC1091
    source .env 2>/dev/null || true
    mkdir -p backups
    STAMP=$(date +%Y%m%d_%H%M%S)
    LABEL="${1:-seeds}"
    FILE="backups/${LABEL}_${STAMP}.sql"
    echo -e "${CYAN}Creando snapshot → $FILE${NC}"
    docker compose exec -T db pg_dump \
      -U "${POSTGRES_USER}" \
      --data-only \
      -t institutions \
      -t service_types -t doc_types -t folder_statuses \
      -t prefix_corrections \
      -t admins -t contracts -t services -t service_type_documents \
      "${POSTGRES_DB}" > "$FILE"
    echo -e "${GREEN}Snapshot guardado: $FILE${NC}"
    ;;

  restore)
    if [[ -z "${1:-}" ]]; then
      echo -e "${RED}[error] Uso: ./dev.sh restore <archivo.sql>${NC}" >&2
      exit 1
    fi
    # shellcheck disable=SC1091
    source .env 2>/dev/null || true
    echo -e "${YELLOW}Restaurando desde $1 ...${NC}"
    docker compose exec -T db psql -U "${POSTGRES_USER}" "${POSTGRES_DB}" < "$1"
    echo -e "${GREEN}Restauración completa.${NC}"
    ;;

  nuke)
    echo -e "${RED}${BOLD}WARNING: This will destroy ALL volumes including the database.${NC}"
    read -rp "Type 'yes' to confirm: " confirm
    if [[ "$confirm" == "yes" ]]; then
      docker compose down -v
      echo -e "${GREEN}Done. All volumes removed.${NC}"
    else
      echo "Aborted."
    fi
    ;;

  help|*)
    echo -e "${BOLD}Usage:${NC} ./dev.sh <command> [args]"
    echo ""
    echo -e "${BOLD}Available commands:${NC}"
    echo -e "  ${GREEN}up${NC}                   Start all services (docker compose up -d)"
    echo -e "  ${GREEN}down${NC}                 Stop all services"
    echo -e "  ${GREEN}restart${NC} [service]    Restart all or a specific service"
    echo -e "  ${GREEN}build${NC}                Build images (with cache) and restart"
  echo -e "  ${GREEN}rebuild${NC}              Rebuild images (no cache) and restart"
    echo -e "  ${GREEN}logs${NC} [service]       Follow logs (all services or one)"
    echo -e "  ${GREEN}status${NC}               Show container status"
    echo -e "  ${GREEN}migrate${NC}              Apply pending Alembic migrations"
    echo -e "  ${GREEN}migration${NC} <msg>      Generate a new Alembic migration"
    echo -e "  ${GREEN}seed${NC}                 Run database seed script"
    echo -e "  ${GREEN}test${NC} [args]          Run pytest (pass extra args if needed)"
    echo -e "  ${GREEN}lint${NC}                 Run ruff check + format check"
    echo -e "  ${GREEN}format${NC}               Auto-format code with ruff"
    echo -e "  ${GREEN}shell${NC}                Open an interactive shell in backend container"
    echo -e "  ${GREEN}psql${NC}                 Connect to PostgreSQL via psql"
    echo -e "  ${GREEN}health${NC}               Check /health endpoint"
    echo -e "  ${GREEN}backup${NC} [nombre]      Snapshot de tablas base → backups/<nombre>_TIMESTAMP.sql"
    echo -e "  ${GREEN}restore${NC} <archivo>    Restaurar tablas desde un snapshot SQL"
    echo -e "  ${RED}nuke${NC}                 Destroy all volumes (asks confirmation)"
    echo -e "  ${GREEN}help${NC}                 Show this help message"
    echo ""
    if [[ "$CMD" != "help" ]]; then
      echo -e "${RED}[error] Unknown command: $CMD${NC}" >&2
      exit 1
    fi
    ;;
esac
