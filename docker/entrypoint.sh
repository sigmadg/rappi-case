#!/usr/bin/env bash
# Arranca Django (8000), puente n8n (8090), bucle opcional M2 (run_alert_engine) y monitor M3.
set -euo pipefail
cd /app

# Ollama casi siempre corre en el *host*; el .env de desarrollo trae 127.0.0.1 y rompe dentro del contenedor.
# Exportar aquí hace que los procesos Python hereden la URL antes de load_dotenv (override=False no pisa env existente).
# Para Ollama en otro contenedor/servicio, define OLLAMA_BASE_URL explícita (p. ej. http://ollama:11434).
# OLLAMA_DOCKER_USE_LOOPBACK=1 desactiva el reemplazo automático de loopback → host.docker.internal.
if [[ "${OLLAMA_DOCKER_USE_LOOPBACK:-0}" != "1" ]]; then
  case "${OLLAMA_BASE_URL:-}" in
    ""|http://127.0.0.1:11434|http://127.0.0.1:11434/|http://localhost:11434|http://localhost:11434/)
      export OLLAMA_BASE_URL="http://host.docker.internal:11434"
      echo "[docker] OLLAMA_BASE_URL=${OLLAMA_BASE_URL} (Ollama en el host; en el host usa OLLAMA_HOST=0.0.0.0 si hace falta)"
      ;;
  esac
fi

export PYTHONPATH="/app/modulo3_agente_telegram/src:/app/modulo2_motor_alertas/src:${PYTHONPATH:-}"

python django_viz/manage.py migrate --noinput

# Regenera calibration.json desde RAW_DATA del Excel (misma lógica que M1 / run_alert_engine --recalibrate).
if [[ "${ENABLE_RECALIBRATE_ON_START:-1}" == "1" ]]; then
  echo "[docker] Recalibración: data/rappi_delivery_case_data.xlsx → modulo2_motor_alertas/calibration.json"
  python modulo2_motor_alertas/export_calibration_from_m1.py
fi

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

# Módulo 2: motor de alertas en consola/auditoría (estado debounce distinto al del monitor M3).
if [[ "${ENABLE_M2_ENGINE_LOOP:-1}" == "1" ]]; then
  (
    export ALERT_STATE_PATH="${ALERT_STATE_PATH_M2:-/app/modulo2_motor_alertas/.alert_state_m2_loop.json}"
    m2_interval="${M2_ENGINE_INTERVAL_SEC:-${MONITOR_INTERVAL_SEC:-600}}"
    echo "[docker] Módulo 2 — bucle run_alert_engine cada ${m2_interval}s (debounce: ${ALERT_STATE_PATH})"
    while true; do
      python modulo2_motor_alertas/run_alert_engine.py || true
      sleep "${m2_interval}"
    done
  ) &
  pids+=($!)
fi

if [[ "${ENABLE_MONITOR:-1}" == "1" ]]; then
  margs=( --interval-sec "${MONITOR_INTERVAL_SEC:-600}" )
  if [[ "${MONITOR_DRY_RUN:-1}" == "1" ]]; then
    margs+=(--dry-run)
  fi
  echo "[docker] Módulo 3 (Telegram) — monitor_loop.py ${margs[*]}"
  python modulo3_agente_telegram/monitor_loop.py "${margs[@]}" &
  pids+=($!)
fi

echo "[docker] Django → 0.0.0.0:8000"
python django_viz/manage.py runserver 0.0.0.0:8000 &
pids+=($!)

wait "${pids[-1]}"
