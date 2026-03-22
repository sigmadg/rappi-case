#!/usr/bin/env bash
# Mismo stack que docker-compose.yml pero SIN plugin "docker compose" (solo docker build + run).
# Uso desde la raíz del repo: ./scripts/docker_up.sh
#
# Si 8000/8090 están ocupados, busca el siguiente par libre (8001/8091, …) hasta CASO_DOCKER_PORT_TRIES.
# Puertos base: CASO_DOCKER_PORT (default 8000), CASO_DOCKER_PORT_BRIDGE (default 8090).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

IMAGE="${CASO_DOCKER_IMAGE:-caso-tecnico}"
NAME="${CASO_DOCKER_NAME:-caso-tecnico-run}"
PORT_BASE="${CASO_DOCKER_PORT:-8000}"
BRIDGE_BASE="${CASO_DOCKER_PORT_BRIDGE:-8090}"
MAX_TRY="${CASO_DOCKER_PORT_TRIES:-40}"

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
for ((i = 0; i < MAX_TRY; i++)); do
  H=$((PORT_BASE + i))
  B=$((BRIDGE_BASE + i))
  if host_port_free "$H" && host_port_free "$B"; then
    echo "[docker_up] run → ${NAME}"
    echo "[docker_up] Dashboard: http://127.0.0.1:${H}/"
    echo "[docker_up] Puente n8n:  http://127.0.0.1:${B}/tick"
    exec docker run --rm --name "${NAME}" \
      -p "${H}:8000" \
      -p "${B}:8090" \
      -v "${ROOT}/data:/app/data:ro" \
      "${ENV_ARGS[@]}" \
      "${ENV_FILE_ARGS[@]}" \
      "${IMAGE}"
  fi
done

echo "[docker_up] No hay puertos libres en el rango ${PORT_BASE}–$((PORT_BASE + MAX_TRY - 1)) (y bridge ${BRIDGE_BASE}–…)." >&2
echo "[docker_up] Libera 8000/8090 u otro par, o define CASO_DOCKER_PORT / CASO_DOCKER_PORT_BRIDGE." >&2
exit 1
