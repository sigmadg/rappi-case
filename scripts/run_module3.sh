#!/usr/bin/env bash
# Ejecuta el agente Telegram (Módulo 3) desde la raíz del repo, sin importar el cwd.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python modulo3_agente_telegram/run_agent.py "$@"
else
  exec python3 modulo3_agente_telegram/run_agent.py "$@"
fi
