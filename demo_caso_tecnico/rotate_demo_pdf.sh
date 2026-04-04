#!/usr/bin/env bash
# Rota todas las páginas del PDF de la demo sin tocar el LaTeX.
#
# Uso:
#   ./rotate_demo_pdf.sh
#       → lee presentacion_demo.pdf y escribe presentacion_demo_rotado.pdf
#   ./rotate_demo_pdf.sh mi.pdf salida.pdf
#       → mismos archivos personalizados
#
# Con qpdf (si está instalado): +90° en sentido horario (típico para “poner de pie” un apaisado).
# Sin qpdf: se usa rotate_pdf_pages.py con -90° (antihorario), que suele coincidir visualmente con +90 horario.
#
# Ajuste manual con qpdf:
#   qpdf --rotate=-90:1-z entrada.pdf salida.pdf   # horario inverso
#
set -euo pipefail
cd "$(dirname "$0")"

SRC="${1:-presentacion_demo.pdf}"
OUT="${2:-presentacion_demo_rotado.pdf}"

if [[ ! -f "$SRC" ]]; then
  echo "No existe: $SRC" >&2
  exit 1
fi

if command -v qpdf >/dev/null 2>&1; then
  qpdf --rotate=+90:1-z "$SRC" "$OUT"
  echo "OK → $OUT  (qpdf --rotate=+90:1-z, ${SRC})"
  exit 0
fi

python3 "$(dirname "$0")/rotate_pdf_pages.py" "$SRC" "$OUT" -90
