#!/usr/bin/env bash
# Levanta solo el puente HTTP POST /tick (FastAPI) para n8n u otros clientes.
# Uso desde la raíz del repo: ./scripts/run_n8n_bridge.sh
#
# N8N_BRIDGE_HOST:
#   127.0.0.1 (defecto) — solo conexiones desde la misma máquina.
#   0.0.0.0 — necesario si n8n va en Docker (Linux) y llega vía host.docker.internal al puerto publicado.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

HOST="${N8N_BRIDGE_HOST:-127.0.0.1}"
PORT="${N8N_BRIDGE_PORT:-8090}"

export PYTHONPATH="${ROOT}/modulo3_agente_telegram/src:${ROOT}/modulo2_motor_alertas/src:${PYTHONPATH:-}"

echo "[n8n_bridge] uvicorn n8n_bridge.app:app --host ${HOST} --port ${PORT}"
echo "[n8n_bridge] Health: curl -sS 'http://127.0.0.1:${PORT}/health'"
echo "[n8n_bridge] Tick:  curl -sS -X POST 'http://127.0.0.1:${PORT}/tick?dry_run=true' | head -c 400"
exec python3 -m uvicorn n8n_bridge.app:app --host "${HOST}" --port "${PORT}"
