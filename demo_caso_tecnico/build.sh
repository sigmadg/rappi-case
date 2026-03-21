#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
pdflatex -interaction=nonstopmode presentacion_demo.tex
pdflatex -interaction=nonstopmode presentacion_demo.tex
echo "OK → presentacion_demo.pdf"
