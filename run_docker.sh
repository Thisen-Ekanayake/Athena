#!/usr/bin/env bash
#
# run_docker.sh — start the Athena stack (Postgres, Redis, Qdrant, API, worker, frontend)
#          via Docker Compose, wait until it is healthy, and seed sources if needed.
#
# Usage:
#   ./run_docker.sh            Start using the pre-built GHCR images (docker-compose.release.yml)
#   ./run_docker.sh --build    Build the images locally instead (docker-compose.yml)
#   ./run_docker.sh --down     Stop and remove the stack
#   ./run_docker.sh --logs     Follow the worker logs after starting
#   ./run_docker.sh --help     Show this help
#
set -euo pipefail

# --- resolve repo root (directory containing this script) -------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RELEASE_COMPOSE="docker/docker-compose.release.yml"
DEV_COMPOSE="docker/docker-compose.yml"
COMPOSE_FILE="$RELEASE_COMPOSE"
FOLLOW_LOGS=0

API_URL="http://127.0.0.1:8000"
FRONTEND_URL="http://localhost:5173"

# --- arg parsing ------------------------------------------------------------
for arg in "$@"; do
  case "$arg" in
    --build|--dev) COMPOSE_FILE="$DEV_COMPOSE" ;;
    --logs)        FOLLOW_LOGS=1 ;;
    --down)
      echo "Stopping Athena stack..."
      docker compose -f "$RELEASE_COMPOSE" down 2>/dev/null || true
      docker compose -f "$DEV_COMPOSE" down 2>/dev/null || true
      echo "Stopped."
      exit 0
      ;;
    --help|-h)
      sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown option: $arg (try --help)"; exit 1 ;;
  esac
done

# --- preflight checks -------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker is not installed or not on PATH." >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "ERROR: the Docker daemon is not running. Start Docker and retry." >&2
  exit 1
fi
if [ ! -f .env ]; then
  echo "WARNING: .env not found. Copy .env.example to .env and set OPENAI_API_KEY." >&2
  echo "         Continuing — the stack may fail without it." >&2
fi

# --- start the stack --------------------------------------------------------
echo ">> Starting stack from ${COMPOSE_FILE}"
docker compose -f "$COMPOSE_FILE" up -d

# --- wait for a URL to return HTTP 200 --------------------------------------
wait_for_http() {
  local name="$1" url="$2" tries="${3:-60}"
  printf ">> Waiting for %s (%s) " "$name" "$url"
  for _ in $(seq 1 "$tries"); do
    if [ "$(curl -s -o /dev/null -w '%{http_code}' "$url" 2>/dev/null)" = "200" ]; then
      echo " ready."
      return 0
    fi
    printf "."
    sleep 1
  done
  echo " TIMEOUT."
  return 1
}

wait_for_http "API"      "${API_URL}/health" 90 || {
  echo "API did not become healthy. Recent web logs:" >&2
  docker compose -f "$COMPOSE_FILE" logs --tail=30 web >&2 || true
  exit 1
}
wait_for_http "frontend" "${FRONTEND_URL}/" 60 || true

# --- seed sources on a fresh database ---------------------------------------
# The API creates the schema on startup, but the initial sources are seeded by
# scripts/setup_project.py. If the sources table is empty, run it in the web container.
sources_json="$(curl -s "${API_URL}/api/v1/sources" 2>/dev/null || echo '[]')"
if printf '%s' "$sources_json" | grep -q '"id"'; then
  echo ">> Sources already present — skipping seed."
else
  echo ">> No sources found — seeding via setup_project.py (in web container)..."
  docker compose -f "$COMPOSE_FILE" exec -T web python3 scripts/setup_project.py \
    || echo "   (seed step failed — run 'docker compose -f ${COMPOSE_FILE} exec web python3 scripts/setup_project.py' manually)"
fi

# --- summary ----------------------------------------------------------------
echo
echo "==================================================================="
echo " Athena is running"
echo "   Frontend : ${FRONTEND_URL}"
echo "   API      : ${API_URL}        (docs: ${API_URL}/docs)"
echo
echo "   Logs : docker compose -f ${COMPOSE_FILE} logs -f"
echo "   Stop : ./run_docker.sh --down"
echo "==================================================================="

docker compose -f "$COMPOSE_FILE" ps

if [ "$FOLLOW_LOGS" = "1" ]; then
  echo
  echo ">> Following worker logs (Ctrl-C to stop following; containers keep running)"
  docker compose -f "$COMPOSE_FILE" logs -f worker
fi
