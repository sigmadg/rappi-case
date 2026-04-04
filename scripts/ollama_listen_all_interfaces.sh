#!/usr/bin/env bash
# Hace persistente OLLAMA_HOST=0.0.0.0 para el servicio systemd de Ollama (Docker puede usar host.docker.internal:11434).
#
# Uso (requiere sudo):
#   sudo ./scripts/ollama_listen_all_interfaces.sh
#
# Crea /etc/systemd/system/ollama.service.d/override.conf y reinicia ollama.
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Ejecuta con sudo, por ejemplo:" >&2
  echo "  cd $(cd "$(dirname "$0")/.." && pwd) && sudo ./scripts/ollama_listen_all_interfaces.sh" >&2
  exit 1
fi

UNIT="ollama.service"
if ! systemctl cat "$UNIT" &>/dev/null; then
  echo "No se encontró $UNIT. ¿Ollama está instalado como servicio systemd?" >&2
  echo "Alternativa manual: para la sesión actual, OLLAMA_HOST=0.0.0.0 ollama serve" >&2
  exit 1
fi

DROP_IN_DIR="/etc/systemd/system/ollama.service.d"
mkdir -p "$DROP_IN_DIR"
CONF="$DROP_IN_DIR/override.conf"

# Sobrescribe solo nuestro fragmento (idempotente).
cat > "$CONF" << 'EOF'
# Persistente: Ollama escucha en todas las interfaces → accesible desde contenedores Docker (host.docker.internal).
[Service]
Environment="OLLAMA_HOST=0.0.0.0"
EOF

chmod 644 "$CONF"
systemctl daemon-reload
systemctl restart ollama

echo ""
echo "Archivo escrito: $CONF"
echo "Entorno efectivo del servicio (busca OLLAMA_HOST):"
systemctl show ollama -p Environment --no-pager | tr ' ' '\n' | grep -E 'OLLAMA|^Environment=' || true
echo ""
echo "Puerto 11434 (debe incluir 0.0.0.0:11434):"
ss -tlnp 2>/dev/null | grep 11434 || true
echo ""
echo "Listo. Si algo falla: journalctl -u ollama -n 30 --no-pager"
