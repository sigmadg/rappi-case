# Demo — Presentación del caso técnico Rappi

Carpeta de **material para la demo oral**: presentación LaTeX (Beamer) que resume los **tres módulos** del proyecto en `caso_tecnico/`.

*(Nombre de carpeta sin espacio: `demo_caso_tecnico`, para rutinas y git; equivale a “demo caso técnico”.)*

## Compilar la presentación

Requisitos: LaTeX con **Beamer** (p. ej. TeX Live).

```bash
cd demo_caso_tecnico
pdflatex -interaction=nonstopmode presentacion_demo.tex
pdflatex -interaction=nonstopmode presentacion_demo.tex
```

Salida: `presentacion_demo.pdf`.

Opcional (Linux):

```bash
chmod +x build.sh && ./build.sh
```

## Contenido

- Visión general y arquitectura (M1 → M2 → M3).
- **Módulo 1:** diagnóstico operacional, notebook, dataset Excel, calibración exportable.
- **Módulo 2:** Open-Meteo, zonas WKT, motor experto, `calibration.json`, debounce.
- **Módulo 3:** RAG-lite, LLM / plantilla, Telegram, registro y resumen diario.
- Comandos sugeridos para la demo en vivo.

Las figuras del Módulo 1 se referencian por ruta relativa a `../modulo1_diagnostico/figures/` si quieres incluir alguna en futuras versiones; la presentación base **no depende** de ellas para compilar.
