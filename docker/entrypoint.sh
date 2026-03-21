#!/usr/bin/env bash
# Arranca Django (8000), puente n8n (8090) y monitor M3 en un solo contenedor.
set -euo pipefail
cd /app

export PYTHONPATH="/app/modulo3_agente_telegram/src:/app/modulo2_motor_alertas/src:${PYTHONPATH:-}"

python django_viz/manage.py migrate --noinput

pids=()
cleanup() {
  local pid
  for pid in "${pids[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

if [[ "${ENABLE_N8N_BRIDGE:-1}" == "1" ]]; then
  echo "[docker] Puente n8n → 0.0.0.0:8090 (POST /tick)"
  python -m uvicorn n8n_bridge.app:app --host 0.0.0.0 --port 8090 &
  pids+=($!)
fi

if [[ "${ENABLE_MONITOR:-1}" == "1" ]]; then
  margs=( --interval-sec "${MONITOR_INTERVAL_SEC:-600}" )
  if [[ "${MONITOR_DRY_RUN:-1}" == "1" ]]; then
    margs+=(--dry-run)
  fi
  echo "[docker] Monitor → modulo3_agente_telegram/monitor_loop.py ${margs[*]}"
  python modulo3_agente_telegram/monitor_loop.py "${margs[@]}" &
  pids+=($!)
fi

echo "[docker] Django → 0.0.0.0:8000"
python django_viz/manage.py runserver 0.0.0.0:8000 &
pids+=($!)

wait "${pids[-1]}"
