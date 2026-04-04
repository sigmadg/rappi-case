#!/usr/bin/env python3
"""
Rota todas las páginas de un PDF (ángulo en grados, sentido antihorario, convención pypdf).

Ejemplos:
  python3 rotate_pdf_pages.py entrada.pdf salida.pdf 90
  python3 rotate_pdf_pages.py entrada.pdf salida.pdf -90
"""
from __future__ import annotations

import sys

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    from PyPDF2 import PdfReader, PdfWriter  # type: ignore


def main() -> None:
    if len(sys.argv) < 4:
        print(
            "Uso: python3 rotate_pdf_pages.py <entrada.pdf> <salida.pdf> <grados>\n"
            "  grados: antihorario (p. ej. 90 o -90). Prueba el signo si el visor sigue mal.",
            file=sys.stderr,
        )
        sys.exit(2)
    src, dst, deg_s = sys.argv[1], sys.argv[2], sys.argv[3]
    deg = int(deg_s)
    r = PdfReader(src)
    w = PdfWriter()
    for p in r.pages:
        p.rotate(deg)
        w.add_page(p)
    with open(dst, "wb") as f:
        w.write(f)
    print(f"OK → {dst} ({len(r.pages)} páginas, rotación {deg:+d}°)")


if __name__ == "__main__":
    main()
