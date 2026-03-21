#!/usr/bin/env bash
# Ejecuta una pasada del monitor (mismo código que monitor_loop.py --once).
# Uso desde n8n nodo "Execute Command" con la ruta absoluta a este script.
# Opcional: variable N8N_TICK_ARGS (ej. "--once --demo --dry-run", por defecto --once --dry-run).

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "No se encuentra ${PY}. Crea el venv: python3 -m venv .venv && pip install -r requirements.txt" >&2
  exit 1
fi
ARGS=( "modulo3_agente_telegram/monitor_loop.py" )
if [[ -n "${N8N_TICK_ARGS:-}" ]]; then
  # shellcheck disable=SC2206
  ARGS+=(${N8N_TICK_ARGS})
else
  ARGS+=( --once --dry-run )
fi
exec "$PY" "${ARGS[@]}"
