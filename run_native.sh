#!/usr/bin/env bash
#
# run_native.sh — start Athena the "native" way: only the infrastructure
#            (Postgres, Redis, Qdrant) runs in Docker; the API, Celery
#            workers, frontend and the local model server (llama-server
#            router) run as local processes on the host.
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
# Is any target (a pid, or -pgid for a whole process group) still alive?
any_alive() {
  for t in "$@"; do kill -0 -- "$t" 2>/dev/null && return 0; done
  return 1
}

# SIGTERM the targets, then SIGKILL whatever is left after a grace period. llama-server finishes the
# generation in flight before it exits on SIGTERM, which can take a minute, and holds the GPU until then.
terminate() {
  [ $# -gt 0 ] || return 0
  for t in "$@"; do kill -TERM -- "$t" 2>/dev/null || true; done
  for _ in $(seq 1 20); do
    any_alive "$@" || return 0
    sleep 0.5
  done
  echo "   still running after 10s; killing"
  for t in "$@"; do kill -KILL -- "$t" 2>/dev/null || true; done
}

stop_all() {
  echo ">> Stopping local processes..."
  local targets=()
  for svc in api worker beat summary evolution frontend llm llm-cpu; do
    pidfile="$RUN_DIR/$svc.pid"
    if [ -f "$pidfile" ]; then
      pid="$(cat "$pidfile")"
      # the process group, so child processes (vite, celery pool, model instances) die too
      if kill -0 -- -"$pid" 2>/dev/null; then
        targets+=("-$pid")
        echo "   stopping $svc (pid $pid)"
      fi
      rm -f "$pidfile"
    fi
  done
  terminate "${targets[@]}"
  # A model server whose pid file is gone (one that outlived an earlier --stop was adopted by the next
  # start without one) is found by its preset; its model instances are its children.
  targets=()
  for pid in $(pgrep -f '^[^ ]*llama-server .*--models-preset config/llama-router[a-z.]*\.ini'); do
    targets+=("$pid" $(pgrep -P "$pid"))
    echo "   stopping llm (pid $pid)"
  done
  terminate "${targets[@]}"
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
  echo "WARNING: .env not found. Copy .env.example to .env." >&2
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
# The model server: llama-server in router mode serves the chat and embedding models and swaps them on
# the GPU. Skipped when LLM_BASE_URL (env or .env) points elsewhere, or something already holds :8080.
# A server address saved in Settings is not visible here. Its presets come from the model registry
# (Settings -> Models and keys, athena/model_server), which starts from config/llama-router.ini; a second
# router on :8081 holds a model placed on the CPU beside the GPU one.
env_value() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2-; }
LLM_URL="${LLM_BASE_URL:-$(env_value LLM_BASE_URL)}"
LLAMA_BIN="${LLAMA_SERVER_BIN:-$(env_value LLAMA_SERVER_BIN)}"
LLAMA_BIN="${LLAMA_BIN:-llama-server}"
case "${LLM_URL:-http://127.0.0.1:8080/v1}" in
  http://127.0.0.1:8080*|http://localhost:8080*)
    if lsof -tiTCP:8080 -sTCP:LISTEN >/dev/null 2>&1; then
      echo "   a model server is already listening on :8080; using it"
    elif command -v "$LLAMA_BIN" >/dev/null 2>&1; then
      python3 -m athena.model_server.registry >"$RUN_DIR/presets.log" 2>&1 \
        || echo "   the registry's presets were not written (see $RUN_DIR/presets.log); using config/llama-router.ini"
      PRESET=config/llama-router.ini
      [ -s config/llama-router.generated.ini ] && PRESET=config/llama-router.generated.ini
      start_proc llm "$LLAMA_BIN" --models-preset "$PRESET" --models-max 1 --host 127.0.0.1 --port 8080
      if [ -s config/llama-router.cpu.ini ] && ! lsof -tiTCP:8081 -sTCP:LISTEN >/dev/null 2>&1; then
        start_proc llm-cpu "$LLAMA_BIN" --models-preset config/llama-router.cpu.ini --models-max 1 \
          --host 127.0.0.1 --port 8081
      fi
    else
      echo "WARNING: '$LLAMA_BIN' not found, so AI features have no model server (see config/llama-router.ini)." >&2
    fi ;;
  *) echo "   using the model server at $LLM_URL" ;;
esac
start_proc api      uvicorn athena.api.main:app --host 127.0.0.1 --port 8000 --reload
start_proc worker   celery -A athena.pipeline.tasks worker -l info --pool=threads
# The periodic tasks: beat in its own process, not embedded in the worker (-B). Embedded beat closes every file
# the worker had open, and a zipped egg on the host's sys.path that importlib.metadata keeps open then fails it.
start_proc beat     celery -A athena.pipeline.tasks beat -l info --schedule "$RUN_DIR/celerybeat-schedule"
# Summaries and cluster labels: their own queues, one at a time (the model server answers one request at a time).
start_proc summary  celery -A athena.pipeline.tasks worker -l info --pool=solo -c 1 -n "summary@%h" \
                      -Q summary_urgent,summary_standard,summary_lazy,summary_cluster
# Research-evolution topic builds: own queue, one at a time (later phases share a single GPU).
start_proc evolution celery -A athena.pipeline.tasks worker -l info -Q evolution -c 1 --pool=solo \
                      -n "evolution@%h"
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
# The API docs are off unless DOCS_ENABLED=true (athena/api/config.py); /docs is a 404 then.
if [ "$(printf '%s' "${DOCS_ENABLED:-$(env_value DOCS_ENABLED)}" | tr '[:upper:]' '[:lower:]')" = "true" ]; then
  echo "   API      : ${API_URL}        (docs: ${API_URL}/docs)"
else
  echo "   API      : ${API_URL}        (docs off: set DOCS_ENABLED=true in .env)"
fi
echo
echo "   Logs : ${RUN_DIR}/{api,worker,beat,summary,evolution,frontend,llm}.log"
echo "   Stop : ./run_native.sh --stop"
echo "==================================================================="
