#!/usr/bin/env bash
#
# run_native.sh — start Athena the "native" way: only the infrastructure
#            (Postgres, Redis, Qdrant) runs in Docker; the API, Celery
#            worker, and frontend run as local processes on the host.
#
# Usage:
#   ./run_native.sh          Start infra (docker) + API + worker + frontend (local)
#   ./run_native.sh --stop   Stop the local processes and the infra containers
#   ./run_native.sh --help   Show this help
#
# Logs and PIDs are written to: ${TMPDIR:-/tmp}/athena-local/
#
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

INFRA_COMPOSE="docker/docker-compose.yml"
RUN_DIR="${TMPDIR:-/tmp}/athena-local"
mkdir -p "$RUN_DIR"

API_URL="http://127.0.0.1:8000"
FRONTEND_URL="http://localhost:5173"

# ---------------------------------------------------------------------------
stop_all() {
  echo ">> Stopping local processes..."
  for svc in api worker frontend; do
    pidfile="$RUN_DIR/$svc.pid"
    if [ -f "$pidfile" ]; then
      pid="$(cat "$pidfile")"
      # kill the process group so child processes (vite, celery pool) die too
      if kill -0 "$pid" 2>/dev/null; then
        kill -- -"$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
        echo "   stopped $svc (pid $pid)"
      fi
      rm -f "$pidfile"
    fi
  done
  echo ">> Stopping infra containers..."
  docker compose -f "$INFRA_COMPOSE" stop db redis qdrant 2>/dev/null || true
  echo "Stopped."
}

case "${1:-}" in
  --stop) stop_all; exit 0 ;;
  --help|-h) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  "" ) ;;
  * ) echo "Unknown option: $1 (try --help)"; exit 1 ;;
esac

# --- preflight --------------------------------------------------------------
need() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: '$1' not found on PATH." >&2; exit 1; }; }
need docker; need python3; need uvicorn; need celery; need npm; need curl

if ! docker info >/dev/null 2>&1; then
  echo "ERROR: the Docker daemon is not running (needed for infra)." >&2
  exit 1
fi
if [ ! -f .env ]; then
  echo "WARNING: .env not found. Copy .env.example to .env and set OPENAI_API_KEY." >&2
fi

# Refuse to fight the containerised app stack (run_docker.sh) for ports 8000 / 5173.
for c in docker-web-1 docker-worker-1 docker-frontend-1; do
  if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$c"; then
    echo "ERROR: the containerised app stack is running ($c)." >&2
    echo "       Stop it first with:  ./run_docker.sh --down" >&2
    exit 1
  fi
done
# And refuse if something else already holds the ports.
for p in 8000 5173; do
  if lsof -tiTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "ERROR: port $p is already in use. Free it (or ./run_native.sh --stop) and retry." >&2
    exit 1
  fi
done

# --- 1. infra in docker -----------------------------------------------------
echo ">> Starting infra (Postgres, Redis, Qdrant) in Docker..."
docker compose -f "$INFRA_COMPOSE" up -d db redis qdrant

printf ">> Waiting for Postgres "
for _ in $(seq 1 60); do
  if docker compose -f "$INFRA_COMPOSE" exec -T db pg_isready -U athena -d athena_db >/dev/null 2>&1; then
    echo "ready."; break
  fi
  printf "."; sleep 1
done
printf ">> Waiting for Qdrant "
for _ in $(seq 1 30); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:6333/healthz 2>/dev/null)" = "200" ] && { echo "ready."; break; }
  printf "."; sleep 1
done

# --- 2. DB schema + seed (host can reach localhost:5432; seed is idempotent) -
echo ">> Initialising DB schema and seeding sources..."
python3 scripts/setup_project.py || echo "   (setup_project.py failed — check DB connectivity / .env)"

# --- 3. frontend deps -------------------------------------------------------
if [ ! -d frontend/node_modules ]; then
  echo ">> Installing frontend dependencies (npm install)..."
  ( cd frontend && npm install )
fi

# --- helper: launch a process in its own session, record pid + log ----------
start_proc() {
  local name="$1"; shift
  local log="$RUN_DIR/$name.log"
  : > "$log"
  # setsid -> new process group so --stop can kill the whole tree
  setsid "$@" >"$log" 2>&1 &
  echo $! > "$RUN_DIR/$name.pid"
  echo "   started $name (pid $(cat "$RUN_DIR/$name.pid"))  ->  $log"
}

wait_for_http() {
  local name="$1" url="$2" tries="${3:-60}"
  printf ">> Waiting for %s " "$name"
  for _ in $(seq 1 "$tries"); do
    [ "$(curl -s -o /dev/null -w '%{http_code}' "$url" 2>/dev/null)" = "200" ] && { echo "ready."; return 0; }
    printf "."; sleep 1
  done
  echo "TIMEOUT."; return 1
}

# --- 4. local services ------------------------------------------------------
echo ">> Starting local services..."
start_proc api      uvicorn athena.api.main:app --host 127.0.0.1 --port 8000 --reload
start_proc worker   celery -A athena.pipeline.tasks worker -l info --pool=threads \
                      -B --schedule "$RUN_DIR/celerybeat-schedule"
( cd frontend && start_proc frontend npm run dev )

wait_for_http "API"      "${API_URL}/health" 90 || {
  echo "API failed to start. Last lines of log:" >&2
  tail -n 25 "$RUN_DIR/api.log" >&2
  exit 1
}
wait_for_http "frontend" "${FRONTEND_URL}/" 60 || true

# --- summary ----------------------------------------------------------------
echo
echo "==================================================================="
echo " Athena is running (native services, dockerised infra)"
echo "   Frontend : ${FRONTEND_URL}"
echo "   API      : ${API_URL}        (docs: ${API_URL}/docs)"
echo
echo "   Logs : ${RUN_DIR}/{api,worker,frontend}.log"
echo "   Stop : ./run_native.sh --stop"
echo "==================================================================="
