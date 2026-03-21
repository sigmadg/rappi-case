# Macros Excel — validación frente al notebook

El notebook `modulo1_diagnostico/notebooks/01_diagnostico_operacional.ipynb` calcula:

- **ratio** = `ORDERS / CONNECTED_RT` (si `CONNECTED_RT` es 0, el ratio queda vacío, como `NaN` en pandas).
- **clasificación:** `saturacion` (>1.8), `sobre_oferta` (<0.5), `saludable` (0.9–1.2), `intermedio` (resto).

El módulo `VBA_RappiMacros.bas` replica esa lógica en la hoja **`RAW_DATA`** del archivo `data/rappi_delivery_case_data.xlsx`.

## Importante: `.xlsx` no guarda macros

1. Abre el libro con los datos (o copia `rappi_delivery_case_data.xlsx`).
2. **Guardar como** → tipo **Libro de Excel habilitado para macros (\*.xlsm)**.
3. `Alt + F11` → menú **Archivo** → **Importar archivo** → elige `VBA_RappiMacros.bas`.
4. `Ctrl + S` para guardar el módulo en el `.xlsm`.

En Excel en Windows: **Archivo → Opciones → Centro de confianza → Configuración del Centro de confianza → Configuración de macros →** habilitar macros firmadas o de confianza según tu política.

## Macros disponibles (Editor VBA o Asignar a botón)

| Macro | Qué hace |
|--------|-----------|
| `Rappi_FlujoCompleto` | Orden sugerido: columnas → ratio → resumen → P1 horas → agregación diaria → plantilla validación → copiar a columna B. |
| `Rappi_CalcularRatio` | Rellena `RATIO` y `CLASIFICACION` en `RAW_DATA` (tras `Rappi_AgregarColumnasMetricas` si faltan columnas). |
| `Rappi_GenerarResumen` | Crea **`RESUMEN_EXCEL`**: totales, % saturación, media de ratio (solo filas con ratio numérico), filas con ratio vacío, media de earnings. |
| `Rappi_P1_HorasSaturacion` | Crea **`P1_HORAS_SAT`**: conteo de filas en saturación por hora 0–23 (equivalente a `p1h` del notebook). |
| `Rappi_AgregacionDiaria` | Crea **`DAILY_AGG`**: por fecha, `earn_mean`, `sat_frac`, `ratio_mean` (como `daily.groupby("DATE").agg(...)`). |
| `Rappi_CrearPlantillaValidacion` | Hoja **`VALIDACION`**: pega en columna **C** los números que copies del notebook. |
| `Rappi_LlenarValidacionDesdeResumen` | Copia métricas de `RESUMEN_EXCEL` a la columna **B** de `VALIDACION`. |
| `Rappi_CompararConNotebook` | Calcula diferencia absoluta B vs C y marca **OK** si \|B−C\| ≤ tolerancia (0.0001). |

## Cómo comparar con el notebook

1. En Jupyter, imprime o anota los valores que quieras cotejar (por ejemplo los de `RESUMEN` o los de `describe`).
2. Ejecuta `Rappi_FlujoCompleto` o los pasos sueltos hasta tener **`RESUMEN_EXCEL`** y **`VALIDACION`** con la columna B rellenada.
3. En la columna **C** de `VALIDACION`, pega los valores del notebook **en el mismo orden** que las filas (`total_filas`, `filas_saturacion`, `pct_saturacion`, etc.).
4. **Porcentaje:** en el notebook suele mostrarse como fracción (p. ej. `0.1543`) o como porcentaje en texto; para la comparación usa **número decimal** (mismo criterio que Excel: si en Excel ves 15 %, pega `0.15`).

## Archivo de datos

El Excel debe incluir la hoja **`RAW_DATA`** con cabeceras en la fila 1: `COUNTRY`, `DATE`, `HOUR`, `CITY`, `ZONE`, `CONNECTED_RT`, `ORDERS`, `EARNINGS`, `PRECIPITATION_MM` (como en el caso Rappi).

Si solo tienes `.xlsx`, conviértelo a `.xlsm` antes de importar el `.bas`; no hace falta cambiar el nombre del fichero de datos si mantienes la misma estructura de hojas.
