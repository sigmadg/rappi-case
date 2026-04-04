#!/usr/bin/env bash
# App en un solo contenedor (sin plugin Compose). Uso: ./scripts/docker_up.sh
# Stack con Grafana + Prometheus: ./scripts/docker_up.sh stack   o   ./scripts/docker_stack.sh
#
# Si 8000/8090/9108 están ocupados, busca el siguiente trío libre (8001/8091/9109, …) hasta CASO_DOCKER_PORT_TRIES.
# Puertos base: CASO_DOCKER_PORT (8000), CASO_DOCKER_PORT_BRIDGE (8090), CASO_DOCKER_PORT_METRICS (9108).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Stack completo (Grafana + Prometheus): ./scripts/docker_up.sh stack  →  docker_stack.sh
if [[ "${1:-}" == "stack" ]]; then
  shift
  exec "${ROOT}/scripts/docker_stack.sh" "$@"
fi

echo "[docker_up] Solo contenedor de la app (sin Prometheus ni Grafana). Stack completo: ./scripts/docker_up.sh stack | ./scripts/docker_stack.sh | docker compose up --build" >&2

IMAGE="${CASO_DOCKER_IMAGE:-caso-tecnico}"
NAME="${CASO_DOCKER_NAME:-caso-tecnico-run}"
PORT_BASE="${CASO_DOCKER_PORT:-8000}"
BRIDGE_BASE="${CASO_DOCKER_PORT_BRIDGE:-8090}"
METRICS_BASE="${CASO_DOCKER_PORT_METRICS:-9108}"
MAX_TRY="${CASO_DOCKER_PORT_TRIES:-40}"
# Ollama en el host: URL que ve el *contenedor* (host.docker.internal gracias a --add-host).
CASO_OLLAMA_URL="${CASO_OLLAMA_URL:-http://host.docker.internal:11434}"

if ! command -v docker >/dev/null 2>&1; then
  echo "No está instalado 'docker' en el PATH." >&2
  exit 1
fi

# Devuelve 0 si el puerto TCP en 0.0.0.0 está libre para bind (sin instalar herramientas extra).
host_port_free() {
  python3 -c "import socket,sys
p=int(sys.argv[1])
s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
try:
 s.bind(('0.0.0.0',p))
 s.close()
 sys.exit(0)
except OSError:
 sys.exit(1)" "$1"
}

echo "[docker_up] build → ${IMAGE}"
docker build -t "${IMAGE}" .

docker rm -f "${NAME}" 2>/dev/null || true

ENV_ARGS=()
ENV_FILE_ARGS=()
if [[ -f "${ROOT}/.env" && ! -d "${ROOT}/.env" ]]; then
  ENV_ARGS+=( -v "${ROOT}/.env:/app/.env:ro" )
  # El entrypoint bash no hace source de /app/.env; inyecta MONITOR_DRY_RUN, etc.
  ENV_FILE_ARGS+=( --env-file "${ROOT}/.env" )
fi

H=""
B=""
M=""
for ((i = 0; i < MAX_TRY; i++)); do
  H=$((PORT_BASE + i))
  B=$((BRIDGE_BASE + i))
  M=$((METRICS_BASE + i))
  if host_port_free "$H" && host_port_free "$B" && host_port_free "$M"; then
    echo "[docker_up] run → ${NAME}"
    echo ""
    echo "  ════════════════════════════════════════════════════════════"
    echo "  FRONT (Django):  http://127.0.0.1:${H}/"
    echo "  ════════════════════════════════════════════════════════════"
    echo ""
    echo "[docker_up] Puente n8n:  http://127.0.0.1:${B}/tick"
    echo "[docker_up] Métricas monitor: http://127.0.0.1:${M}/metrics"
    echo "[docker_up] Ollama (LLM en el host): OLLAMA_BASE_URL=${CASO_OLLAMA_URL} — en el host suele hacer falta OLLAMA_HOST=0.0.0.0"
    echo "[docker_up] Si el navegador dice «Connection failed»: usa **http** (no https), **127.0.0.1** (no «localhost» si falla), y el puerto ${H} de arriba."
    echo "[docker_up] Comprueba: curl -sS -o /dev/null -w '%{http_code}\\n' http://127.0.0.1:${H}/"
    exec docker run --rm --name "${NAME}" \
      --add-host=host.docker.internal:host-gateway \
      -p "${H}:8000" \
      -p "${B}:8090" \
      -p "${M}:9108" \
      -v "${ROOT}/data:/app/data:ro" \
      "${ENV_ARGS[@]}" \
      "${ENV_FILE_ARGS[@]}" \
      -e "OLLAMA_BASE_URL=${CASO_OLLAMA_URL}" \
      -e "ENABLE_RECALIBRATE_ON_START=${ENABLE_RECALIBRATE_ON_START:-1}" \
      -e "DJANGO_ALLOWED_HOSTS=${DJANGO_ALLOWED_HOSTS:-localhost,127.0.0.1,testserver,[::1],*}" \
      "${IMAGE}"
  fi
done

echo "[docker_up] No hay puertos libres en el rango ${PORT_BASE}–$((PORT_BASE + MAX_TRY - 1)) (bridge ${BRIDGE_BASE}–…, métricas ${METRICS_BASE}–…)." >&2
echo "[docker_up] Libera 8000/8090/9108 u otro trío, o define CASO_DOCKER_PORT / CASO_DOCKER_PORT_BRIDGE / CASO_DOCKER_PORT_METRICS." >&2
exit 1
