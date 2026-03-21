#!/usr/bin/env bash
# Arranca el pipeline (monitor M2+M3) y el front Django desde la raíz del repo.
# Uso: ver scripts/run_stack.sh --help
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
else
  PYTHON="python3"
fi

RUN_FRONT=1
RUN_PIPELINE=1
MONITOR_ARGS=()
DJANGO_PORT="${DJANGO_PORT:-8000}"

usage() {
  cat <<'EOF'
Uso: scripts/run_stack.sh [opciones] [-- args_extra_monitor...]

Desde la raíz del repo (o desde cualquier cwd): levanta el monitor operativo
(misma pasada que monitor_loop.py) y el dashboard Django.

Opciones:
  --front-only       Solo migrate + runserver (sin monitor)
  --pipeline-only    Solo monitor_loop en primer plano (sin Django)
  --dry-run          No envía a Telegram (se pasa al monitor)
  --demo             Modo demo Santiago (se pasa al monitor)
  --once             Un solo ciclo del monitor y termina el proceso del monitor
  --interval-sec N   Segundos entre ciclos del monitor
  --port N, -p N     Puerto de Django (default: 8000 o variable DJANGO_PORT)
  -h, --help         Esta ayuda

Si el puerto está ocupado, el script prueba el siguiente (8001, 8002, …) salvo que
definas RUN_STACK_STRICT_PORT=1 (entonces termina con error y debes liberar el puerto
o usar otro -p).

Cualquier argumento no reconocido se añade al final de monitor_loop.py
(p. ej. --force-send).

Ejemplos:
  scripts/run_stack.sh
  scripts/run_stack.sh --dry-run --interval-sec 300
  scripts/run_stack.sh --front-only
  scripts/run_stack.sh --pipeline-only --once --dry-run

Requisitos: pip install -r requirements.txt y .env configurado si envías a Telegram.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --front-only)
      RUN_PIPELINE=0
      shift
      ;;
    --pipeline-only)
      RUN_FRONT=0
      shift
      ;;
    --dry-run)
      MONITOR_ARGS+=(--dry-run)
      shift
      ;;
    --demo)
      MONITOR_ARGS+=(--demo)
      shift
      ;;
    --once)
      MONITOR_ARGS+=(--once)
      shift
      ;;
    --interval-sec)
      if [[ $# -lt 2 ]]; then
        echo "Falta valor para --interval-sec" >&2
        exit 1
      fi
      MONITOR_ARGS+=(--interval-sec "$2")
      shift 2
      ;;
    --port|-p)
      if [[ $# -lt 2 ]]; then
        echo "Falta valor para --port" >&2
        exit 1
      fi
      DJANGO_PORT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      MONITOR_ARGS+=("$@")
      break
      ;;
    *)
      MONITOR_ARGS+=("$1")
      shift
      ;;
  esac
done

# True si algo escucha en 127.0.0.1:puerto (TCP connect tiene éxito).
_port_ocupado() {
  local p=$1
  (echo >"/dev/tcp/127.0.0.1/${p}") &>/dev/null
}

# Deja DJANGO_PORT en el primer puerto libre desde el solicitado (máx. +30).
_resolver_puerto_django() {
  local base=$1
  local p=$1
  local max=$((base + 30))
  if [[ "${RUN_STACK_STRICT_PORT:-0}" == "1" ]]; then
    if _port_ocupado "${p}"; then
      echo "[run_stack] Puerto ${p} ya está en uso. Cierra el otro runserver o usa -p OTRO." >&2
      echo "[run_stack] Pista: ss -tlnp | grep ':${p} '   o   pkill -f 'manage.py runserver'" >&2
      exit 1
    fi
    return
  fi
  while [[ "${p}" -le "${max}" ]]; do
    if ! _port_ocupado "${p}"; then
      if [[ "${p}" -ne "${base}" ]]; then
        echo "[run_stack] Puerto ${base} ocupado → usando ${p}" >&2
      fi
      DJANGO_PORT=$p
      return
    fi
    p=$((p + 1))
  done
  echo "[run_stack] No hay puerto TCP libre entre ${base} y ${max}. Libera uno o usa -p." >&2
  exit 1
}

MONITOR_PID=""
cleanup() {
  if [[ -n "${MONITOR_PID}" ]] && kill -0 "${MONITOR_PID}" 2>/dev/null; then
    kill "${MONITOR_PID}" 2>/dev/null || true
    wait "${MONITOR_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

if [[ "${RUN_PIPELINE}" -eq 1 ]]; then
  if [[ "${RUN_FRONT}" -eq 1 ]]; then
    echo "[run_stack] Monitor en segundo plano → monitor_loop.py ${MONITOR_ARGS[*]}"
    "${PYTHON}" "${ROOT}/modulo3_agente_telegram/monitor_loop.py" "${MONITOR_ARGS[@]}" &
    MONITOR_PID=$!
  else
    exec "${PYTHON}" "${ROOT}/modulo3_agente_telegram/monitor_loop.py" "${MONITOR_ARGS[@]}"
  fi
fi

if [[ "${RUN_FRONT}" -eq 1 ]]; then
  _resolver_puerto_django "${DJANGO_PORT}"
  echo "[run_stack] Django → http://127.0.0.1:${DJANGO_PORT}/"
  cd "${ROOT}/django_viz"
  "${PYTHON}" manage.py migrate --noinput
  "${PYTHON}" manage.py runserver "127.0.0.1:${DJANGO_PORT}"
fi
