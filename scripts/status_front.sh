#!/usr/bin/env bash
# Diagnóstico rápido: ¿el contenedor de la app está Up y responde HTTP en el puerto mapeado?
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== Desde la raíz del repo: $ROOT ==="
echo ""

if docker compose ps --status running --services 2>/dev/null | grep -qx 'caso-tecnico'; then
  echo "[compose] Servicio caso-tecnico:"
  docker compose ps caso-tecnico
  H="${CASO_HOST_HTTP:-8000}"
  URL="http://127.0.0.1:${H}/"
  echo ""
  echo "Probando: curl -sS -o /dev/null -w 'HTTP %{http_code}\\n' ${URL}"
  if curl -sS -o /dev/null -w "HTTP %{http_code}\n" --connect-timeout 3 "${URL}"; then
    echo "OK: abre en el navegador: ${URL}"
  else
    echo "FALLA curl: revisa firewall o que el puerto ${H} sea el del mapeo (docker compose ps)."
  fi
  echo ""
  echo "Health (Compose): docker inspect \"\$(docker compose ps -q caso-tecnico)\" --format '{{json .State.Health}}' | head -c 500"
else
  echo "[compose] No hay caso-tecnico en estado Up en ESTE directorio."
  echo "  ¿Estás en ~/Documentos/caso_tecnico? ¿Ejecutaste: docker compose up -d --build ?"
  echo ""
  echo "Contenedores que contienen 'caso-tecnico' en el nombre:"
  docker ps -a --filter "name=caso-tecnico" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || true
  echo ""
  echo "Si usas solo ./scripts/docker_up.sh (sin Compose), el nombre suele ser caso-tecnico-run:"
  docker ps -a --filter "name=caso-tecnico-run" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || true
fi
