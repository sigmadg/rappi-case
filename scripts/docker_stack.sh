#!/usr/bin/env bash
# Stack en Docker: app (Django + monitor + puente) + Prometheus + Grafana (sin n8n).
# Para incluir n8n: ./scripts/docker_full_stack.sh
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
echo "  App Django:     http://127.0.0.1:${H}/  (http, no https; si falla «localhost», usa 127.0.0.1)"
echo "  Puente /tick:   http://127.0.0.1:${B}/tick"
echo "  Métricas mon.:  http://127.0.0.1:${M}/metrics"
echo "  Prometheus:     http://127.0.0.1:${P}/"
echo "  Grafana:        http://127.0.0.1:${G}/  (admin/admin por defecto)"
echo "  n8n (opcional): docker compose --profile n8n up → http://127.0.0.1:${CASO_HOST_N8N:-15678}/"
echo "                  Workflow POST /tick: CASO_TICK_URL o http://caso-tecnico:8090/tick"
echo ""
if command -v ss >/dev/null 2>&1 && ss -tln 2>/dev/null | grep -qE ":${H}\\s"; then
  echo "[docker_stack] AVISO: algo ya escucha en el puerto host ${H}. Si Compose falla al publicar 8000, usa:" >&2
  echo "  CASO_HOST_HTTP=8001 CASO_HOST_BRIDGE=8091 CASO_HOST_METRICS=9109 ./scripts/docker_stack.sh" >&2
  echo "" >&2
fi

exec docker compose up --build "$@"
