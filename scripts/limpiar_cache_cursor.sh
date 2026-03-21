#!/usr/bin/env bash
# Limpia cachés de Cursor/Chromium que suelen provocar fallos de webview / ServiceWorker.
# IMPORTANTE: cierra Cursor por completo antes de ejecutar.

set -euo pipefail
CURSOR_CONFIG="${HOME}/.config/Cursor"

if [[ ! -d "$CURSOR_CONFIG" ]]; then
  echo "No existe $CURSOR_CONFIG"
  exit 1
fi

echo ">>> Cierra TODAS las ventanas de Cursor y pulsa Enter para continuar..."
read -r

echo ">>> Eliminando cachés (Cache, Code Cache, GPU, Service Worker, Dawn*)..."
rm -rf \
  "$CURSOR_CONFIG/Cache" \
  "$CURSOR_CONFIG/Code Cache" \
  "$CURSOR_CONFIG/GPUCache" \
  "$CURSOR_CONFIG/Service Worker" \
  "$CURSOR_CONFIG/DawnGraphiteCache" \
  "$CURSOR_CONFIG/DawnWebGPUCache"

echo ">>> Hecho. Abre Cursor de nuevo y abre la carpeta caso_tecnico como workspace."
