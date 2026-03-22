#!/usr/bin/env bash
# Instala el plugin "docker compose" (CLI v2) en ~/.docker/cli-plugins/
# sin usar apt (útil en Ubuntu Plucky u otros sistemas sin paquete docker-compose-plugin).
#
# Uso: ./scripts/install_docker_compose_plugin.sh
# Opcional: COMPOSE_VER=v2.29.7 ./scripts/install_docker_compose_plugin.sh
set -euo pipefail

COMPOSE_VER="${COMPOSE_VER:-v2.29.7}"
DEST="${HOME}/.docker/cli-plugins/docker-compose"

ARCH=$(uname -m)
case "$ARCH" in
  x86_64) DARCH="x86_64" ;;
  aarch64) DARCH="aarch64" ;;
  *)
    echo "Arquitectura no soportada: $ARCH (solo x86_64 y aarch64)." >&2
    exit 1
    ;;
esac

URL="https://github.com/docker/compose/releases/download/${COMPOSE_VER}/docker-compose-linux-${DARCH}"

if ! command -v docker >/dev/null 2>&1; then
  echo "No se encontró 'docker' en el PATH. Instala Docker primero." >&2
  exit 1
fi

DOCKER_PATH=$(command -v docker)
if [[ "$DOCKER_PATH" == *snap* ]]; then
  echo "Aviso: tu docker parece ser el del Snap ($DOCKER_PATH)." >&2
  echo "El plugin en ~/.docker/cli-plugins a veces NO lo carga el snap. Prueba ./scripts/docker_up.sh o instala Docker Engine desde:" >&2
  echo "  https://docs.docker.com/engine/install/ubuntu/" >&2
fi

echo "[install_compose] Descargando ${URL}"
mkdir -p "$(dirname "$DEST")"
curl -fsSL "$URL" -o "$DEST"
chmod +x "$DEST"

echo "[install_compose] Plugin en: $DEST"
if docker compose version; then
  echo "[install_compose] OK. Ya puedes: docker compose up --build"
else
  echo "[install_compose] 'docker compose version' falló. Si usas Snap, usa ./scripts/docker_up.sh en su lugar." >&2
  exit 1
fi
