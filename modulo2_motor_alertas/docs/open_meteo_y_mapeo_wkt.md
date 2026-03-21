# 2a — API de clima y mapeo con polígonos WKT

## Elección de API: Open-Meteo

Se usa **Open-Meteo** (`https://api.open-meteo.com/v1/forecast`) por:

1. **Sin API key** — encaja con el volumen del caso y evita gestión de secretos en el repositorio.
2. **Pronóstico horario** del campo `hourly=precipitation` (mm por hora en la respuesta), alineado con el uso de **mm/h** en el dataset y en el Módulo 1.
3. **Cobertura** global con parámetros `latitude`, `longitude` y `timezone=America/Monterrey`.
4. **Alternativas** (WeatherAPI.com, OpenWeatherMap) son válidas para producción; requieren registro, clave en variable de entorno y adaptar el parseo JSON en un cliente paralelo.

Implementación: `src/weather_client.py`.

## Alineación de hojas del Excel (M1 y M2)

La función `validate_excel_zone_consistency` en `zones.py` cruza **RAW_DATA**, **ZONE_INFO** y **ZONE_POLYGONS** (mismos nombres de zona; polígonos WKT válidos vs truncados). Se usa en **recalibración** (`export_calibration_from_m1.py`) y al arrancar **`run_alert_engine.py`**. El notebook M1 incluye la misma comprobación para documentar el vínculo geográfico con el panel.

## Uso de ZONE_POLYGONS (WKT) para mapear coordenadas → zona

El enunciado pide mapear **coordenadas del API** a la **zona operativa** usando los polígonos.

Flujo implementado:

1. Se cargan los polígonos desde la hoja `ZONE_POLYGONS` (`src/zones.py` → `load_zone_polygons`). El WKT se lee como texto; geometrías truncadas por el límite de Excel (~32k caracteres) se omiten.
2. Para cada una de las **14 zonas** en `ZONE_INFO`, se obtiene el par **(lat, lon)** que se enviará a Open-Meteo con `lat_lon_for_forecast_query`:
   - Si hay polígono válido para esa zona: se usa **`Geometry.representative_point()`** de Shapely (punto **dentro** del polígono) y se verifica con **`zone_for_lon_lat`** que ese punto pertenece a la zona esperada.
   - Si no hay polígono (p. ej. WKT truncado en el Excel empaquetado): **respaldo** con `LATITUDE_CENTER` y `LONGITUDE_CENTER` de `ZONE_INFO`.
3. La respuesta de precipitación horaria se asocia a **esa zona** porque la consulta se hizo con un punto ya validado contra el polígono cuando el WKT está disponible.

Para conjuntos de puntos arbitrarios (rejilla, múltiples celdas del modelo), usar `geo_pipeline.aggregate_points_to_zones_max_precip`: cada `(lon, lat, mm/h)` se clasifica con `zone_for_lon_lat` y se agrega por zona.

## Archivos relevantes

| Archivo | Rol |
|---------|-----|
| `src/weather_client.py` | Cliente Open-Meteo |
| `src/zones.py` | WKT, point-in-polygon, `lat_lon_for_forecast_query` |
| `src/geo_pipeline.py` | GeoPandas opcional; agregación punto → zona |
| `run_alert_engine.py` | Bucle 14 zonas → coordenadas WKT-aware → forecast → motor |
