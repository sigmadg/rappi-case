# Módulo 2 — Motor de alertas tempranas (clima + reglas)

**Módulo 3 (Telegram)** está en la carpeta hermana `../modulo3_agente_telegram/`. Si tu terminal está aquí (`modulo2_motor_alertas/`), usa `python ../modulo3_agente_telegram/run_agent.py ...` o ejecuta desde la raíz del repo `python modulo3_agente_telegram/run_agent.py ...` (ver también `scripts/run_module3.sh`).

## Cumplimiento frente al enunciado

| Requisito | Implementación |
|-----------|----------------|
| **2a API + zonas** | **Open-Meteo** (`weather_client.py`). **WKT:** `lat_lon_for_forecast_query` en `zones.py` usa punto **dentro del polígono** (`representative_point` + `zone_for_lon_lat`); si el WKT falta o está truncado, respaldo `ZONE_INFO`. Detalle: **`docs/open_meteo_y_mapeo_wkt.md`**. Rejilla / muchos puntos: `geo_pipeline.aggregate_points_to_zones_max_precip`. |
| **2b Motor** | `decision_engine.py`: umbral **`alert_precip_mm_hr` distinto por zona** en `calibration.json` (histórico Módulo 1); proyección de ratio lineal local con `precip_coef`; riesgo BAJO→CRITICO; incentivo **numérico** `earnings_from` → `earnings_to` vía multiplicador acotado. **Horizonte:** 2 h por defecto (`HORIZON` en `run_alert_engine.py`) — trade-off documentado abajo. **Anti-duplicados:** `debounce.py` + `.alert_state.json` (TTL configurable con `ALERT_DEBOUNCE_TTL_SEC` en `caso_tecnico/.env`, por defecto 45 min; `run_alert_engine.py` carga ese `.env`). Permite escalada de severidad. |
| **2c Script** | `python run_alert_engine.py` (red en vivo) / `python run_alert_engine.py --demo` (sin red, evento en Santiago). Opcional: `--recalibrate` para regenerar `calibration.json` desde `RAW_DATA` del Excel **antes** de consultar la API y aplicar el motor (encadena export M1 + ejecución). |
| **Documento 1 página** | `latex/motor_reglas.tex` — compilar con `pdflatex motor_reglas.tex`. |

## Por qué Open-Meteo

Ver también **`docs/open_meteo_y_mapeo_wkt.md`** (justificación y flujo WKT).

- Sin API key ni registro, adecuado al volumen del caso.
- Pronóstico horario de **precipitación** en las mismas unidades que el dataset (mm acumulados por hora ≈ intensidad mm/h).
- Cobertura global incluyendo Monterrey.

(WeatherAPI / OWM son alternativas válidas; habría que inyectar key por variable de entorno y adaptar el parseo JSON.)

## Umbrales (`calibration.json`)

Generados a partir del panel histórico y regresiones por zona (Módulo 1): coeficiente marginal de precipitación, índice de sensibilidad, mm/h de orden de magnitud para mover el ratio en el tramo saludable→saturación, earnings base y una referencia de earnings recomendado por zona. El documento LaTeX resume la justificación.

### Regenerar desde el Excel (pipeline alineado al notebook M1)

El script **`export_calibration_from_m1.py`** reconstruye el JSON con las mismas definiciones que `modulo1_diagnostico/notebooks/01_diagnostico_operacional.ipynb`:

- `ratio` y `clasificacion` como en el notebook.
- Por zona: `ratio ~ PRECIPITATION_MM + C(HOUR)` → `precip_coef`; `0.6 / precip_coef` → `mm_precip_healthy_to_saturation_linear`; sensibilidad normalizada al máximo |coef|; mediana de `EARNINGS` → `base_earnings_mxn`.
- `alert_precip_mm_hr`: percentil 75 de precipitación en filas con saturación; si ese p75 es &lt; 0.5 mm/h (muchas horas saturadas sin lluvia fuerte en el panel), se usa **6.55 mm/h** como umbral de referencia del caso empaquetado.
- `recommended_earnings_mxn`: media histórica de `EARNINGS` cuando precipitación ≥ umbral de alerta (si hay ≥ 3 obs.); si no, 1.15 × mediana. **`decide_for_zone` no usa este campo**; el incentivo en vivo sale de `base_earnings_mxn` y las reglas del motor.

Con el venv activado, elige la ruta según **desde qué carpeta** ejecutes:

**Desde la raíz del repo** (`caso_tecnico/`):

```bash
python modulo2_motor_alertas/export_calibration_from_m1.py
python modulo2_motor_alertas/export_calibration_from_m1.py --dry-run   # solo imprime JSON
```

**Desde esta carpeta** (`modulo2_motor_alertas/`), el script está al lado tuyo — no repitas `modulo2_motor_alertas/` en la ruta:

```bash
python export_calibration_from_m1.py
python export_calibration_from_m1.py --dry-run
```

Por defecto lee `data/rappi_delivery_case_data.xlsx` (ruta relativa a la raíz del repo) y escribe `calibration.json` junto al script. Si ejecutas solo desde `modulo2_motor_alertas/`, sigue funcionando porque el script resuelve el Excel con `parent.parent / "data" / ...`. Requiere `statsmodels` (ya en `requirements.txt` del repo).

## Horizonte 1 h vs 2 h vs 3 h

Por defecto se usa **2 horas**: balance entre precisión del primer plazo y tiempo para reaccionar (la acción recomendada es **30 min**). Puedes cambiar `HORIZON` en `run_alert_engine.py`.

## Limitación WKT en el Excel incluido

Excel trunca celdas muy largas (~32 768 caracteres). En el dataset empaquetado, **dos polígonos** pueden venir truncados; `load_zone_polygons` omite WKT inválidos. El motor **no depende** de ello para el forecast: las llamadas Open-Meteo usan coordenadas de `ZONE_INFO`. Para asignación estricta punto→zona con rejilla, sustituir esos WKT por geometrías completas en la hoja o en GeoJSON.

## Resiliencia Open-Meteo, logging y auditoría

- **`weather_client.py`:** reintentos con backoff ante timeout / 429 / 5xx (`WEATHER_HTTP_RETRIES`, `WEATHER_HTTP_TIMEOUT_SEC`, `WEATHER_HTTP_BACKOFF_SEC` en `.env`). Por zona, `try_fetch_hourly_precipitation` evita tumbar todo el run: degrada a 0 mm/h y registra el fallo. Si **todas** las zonas fallan (modo no demo), `run_alert_engine` termina con **código de salida 2** y el agente M3 devuelve `status=weather_error`.
- **Logging:** logger `caso_tecnico.alert_engine` / `caso_tecnico.weather` en stderr; nivel `OPS_LOG_LEVEL`.
- **Auditoría:** append a `.ops_audit.jsonl` (eventos `weather_zone_failed`, `alert_engine_decision`, `debounce_blocked`, …). Mapa del repo: `docs/arquitectura_codigo.md`.

## Dependencias

`requests`, `pandas`, `openpyxl`, `shapely`. Opcional: `geopandas` para `geo_pipeline.load_zones_gdf`.
