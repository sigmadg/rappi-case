# Cómo ver el análisis (si VS Code no muestra bien el `.ipynb`)

## Opción A — HTML ya “compilado” (recomendado)

En la misma carpeta se puede generar un **HTML** con tablas y gráficos embebidos:

```bash
cd modulo1_diagnostico/notebooks
../../.venv/bin/jupyter nbconvert --to html --embed-images 01_diagnostico_operacional.ipynb
```

Abre **`01_diagnostico_operacional.html`** con el navegador (doble clic o):

```bash
xdg-open 01_diagnostico_operacional.html   # Linux
open 01_diagnostico_operacional.html        # macOS
start 01_diagnostico_operacional.html         # Windows (cmd)
```

*(Si acabas de ejecutar todas las celdas en Jupyter, el HTML refleja esas salidas.)*

## Opción B — Jupyter en el navegador (interactivo)

```bash
cd /ruta/a/caso_tecnico
source .venv/bin/activate
jupyter lab
```

Abre el `.ipynb` desde la interfaz web: suele verse **igual o mejor** que en VS Code.

## Opción C — VS Code

1. **Confiar en la carpeta del workspace** (popup “Trust” si aparece).
2. Extensión **Jupyter** (Microsoft) actualizada.
3. Kernel: **Python 3.13.x** de `.venv`.
4. `Ctrl+Shift+P` → **Reload Window** si la vista del notebook queda en blanco.

## Lista de 5 hallazgos cuantificados (rúbrica)

Ver **`../HALLAZGOS_M1.md`** (raíz de `modulo1_diagnostico/`) — enlaza celdas del notebook y valores de `calibration.json`.
