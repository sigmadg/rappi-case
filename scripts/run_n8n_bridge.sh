#!/usr/bin/env bash
# Levanta el puente FastAPI POST /tick para n8n (ver n8n/README.md).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# 127.0.0.1: solo procesos en el mismo SO (n8n vía npm en el host).
# 0.0.0.0: necesario si n8n corre en Docker y llama a host.docker.internal:8090 (Linux/Mac).
HOST="${N8N_BRIDGE_HOST:-127.0.0.1}"
PORT="${N8N_BRIDGE_PORT:-8090}"

if [[ -x "$ROOT/.venv/bin/uvicorn" ]]; then
  UV="$ROOT/.venv/bin/uvicorn"
elif command -v uvicorn >/dev/null 2>&1; then
  UV="uvicorn"
else
  echo "Instala dependencias: pip install -r n8n_bridge/requirements.txt" >&2
  exit 1
fi

echo "[n8n_bridge] http://${HOST}:${PORT}  (health: /health  tick: POST /tick)"
exec "$UV" n8n_bridge.app:app --host "$HOST" --port "$PORT"
