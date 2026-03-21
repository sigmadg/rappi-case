# Diagnóstico Operacional (informe LaTeX)

- **Fuente principal:** `../notebooks/01_diagnostico_operacional.ipynb`
- **Figuras:** `../figures/*.png` (regenerar ejecutando el notebook o el script de exportación del repo)

## Compilar el PDF

Desde esta carpeta:

```bash
cd modulo1_diagnostico/Diagnóstico\ Operacional
pdflatex "Diagnóstico Operacional.tex"
```

Salida: `Diagnóstico Operacional.pdf`

El resumen cuantitativo del informe está calibrado con `data/rappi_delivery_case_data.xlsx` (panel 10 080 filas). Si cambias el dataset, vuelve a ejecutar el notebook y, si hace falta, actualiza las cifras en el `.tex`.
