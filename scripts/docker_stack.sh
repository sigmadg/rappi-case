#!/usr/bin/env bash
# Stack completo en Docker: app (Django + monitor + puente) + Prometheus + Grafana.
# Requiere plugin Compose v2. Uso desde la raíz: ./scripts/docker_stack.sh
# Argumentos extra se pasan a "docker compose up" (p. ej. -d para segundo plano).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! docker compose version >/dev/null 2>&1; then
  echo "[docker_stack] ERROR: hace falta Docker Compose v2 (prueba: docker compose version)." >&2
  echo "[docker_stack] Alternativa sin Compose: ./scripts/docker_up.sh (solo la app, sin Grafana/Prometheus)." >&2
  exit 1
fi

H="${CASO_HOST_HTTP:-8000}"
B="${CASO_HOST_BRIDGE:-8090}"
M="${CASO_HOST_METRICS:-9108}"
P="${CASO_HOST_PROMETHEUS:-9090}"
G="${CASO_HOST_GRAFANA:-3000}"

echo "[docker_stack] docker compose up --build $*"
echo "[docker_stack] URLs previstas (mapeo por defecto):"
echo "  App Django:     http://127.0.0.1:${H}/"
echo "  Puente /tick:   http://127.0.0.1:${B}/tick"
echo "  Métricas mon.:  http://127.0.0.1:${M}/metrics"
echo "  Prometheus:     http://127.0.0.1:${P}/"
echo "  Grafana:        http://127.0.0.1:${G}/  (admin/admin por defecto)"
echo ""

exec docker compose up --build "$@"
