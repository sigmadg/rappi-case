#!/usr/bin/env bash
# Levanta **todos** los servicios definidos en docker-compose.yml de la raíz:
#   - caso-tecnico: Django (front), monitor M3, bucle M2, puente POST /tick
#   - Prometheus + Grafana
#   - n8n (perfil n8n)
#
# El LLM (Ollama) no va en este compose: debe estar en el host u otro servicio
# (ver docker/README.md: OLLAMA_HOST=0.0.0.0 ollama serve).
#
# Uso desde la raíz del repo:
#   ./scripts/docker_full_stack.sh          # primer plano
#   ./scripts/docker_full_stack.sh -d       # segundo plano
# Puertos ocupados (p. ej. 8000): ver comentarios en docker-compose.yml y CASO_HOST_*.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! docker compose version >/dev/null 2>&1; then
  echo "[docker_full_stack] ERROR: hace falta Docker Compose v2." >&2
  exit 1
fi

H="${CASO_HOST_HTTP:-8000}"
B="${CASO_HOST_BRIDGE:-8090}"
M="${CASO_HOST_METRICS:-9108}"
P="${CASO_HOST_PROMETHEUS:-9090}"
G="${CASO_HOST_GRAFANA:-3000}"
N="${CASO_HOST_N8N:-15678}"

echo "[docker_full_stack] docker compose --profile n8n up --build $*"
echo "[docker_full_stack] Servicios: app + Prometheus + Grafana + n8n"
echo ""
echo "  Front (Django):    http://127.0.0.1:${H}/"
echo "  Puente n8n/tick:   http://127.0.0.1:${B}/tick"
echo "  Métricas monitor:  http://127.0.0.1:${M}/metrics"
echo "  Prometheus:      http://127.0.0.1:${P}/"
echo "  Grafana:           http://127.0.0.1:${G}/  (admin/admin por defecto)"
echo "  n8n (UI):          http://127.0.0.1:${N}/"
echo ""
echo "  LLM (Ollama): fuera de Compose — en el host: OLLAMA_HOST=0.0.0.0 ollama serve"
echo "                La app usa OLLAMA_BASE_URL=http://host.docker.internal:11434"
echo ""

exec docker compose --profile n8n up --build "$@"
