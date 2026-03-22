"""
Variables horarias adicionales desde Open-Meteo **Archive** (ERA5 land) para análisis M1.

Documentación: https://open-meteo.com/en/docs/historical-weather-api

Uso típico: un punto representativo (p. ej. centroide de ``Centro`` en ``ZONE_INFO``),
mismo rango de fechas que ``RAW_DATA``, y merge con el panel por ``(fecha, hora)``.

No sustituye a ``PRECIPITATION_MM`` del Excel; permite contrastar y añadir viento,
humedad, nubosidad y ``weather_code`` (eventos WMO).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict

import pandas as pd
import requests

# Endpoint REST del historial (ERA5 land u otro backend que exponga archive)
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"

# Lista de variables pedidas en una sola query (nombres exactos de la API hourly)
DEFAULT_HOURLY = (
    "temperature_2m,"
    "relative_humidity_2m,"
    "dew_point_2m,"
    "apparent_temperature,"
    "precipitation,"
    "rain,"
    "snowfall,"
    "cloud_cover,"
    "wind_speed_10m,"
    "wind_direction_10m,"
    "wind_gusts_10m,"
    "weather_code"
)


def fetch_archive_hourly_dataframe(
    latitude: float,
    longitude: float,
    start_d: date,
    end_d: date,
    *,
    hourly: str = DEFAULT_HOURLY,
    timezone: str = "America/Monterrey",
    timeout_sec: float = 90.0,
) -> pd.DataFrame:
    """
    Descarga serie horaria del archivo y devuelve un ``DataFrame`` con columna
    ``time`` (tz-aware según API) y una columna por variable pedida.
    """
    # Parámetros GET estándar de Open-Meteo archive
    params: Dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_d.isoformat(),
        "end_date": end_d.isoformat(),
        "hourly": hourly,
        "timezone": timezone,
    }
    r = requests.get(ARCHIVE, params=params, timeout=timeout_sec)
    r.raise_for_status()
    payload = r.json()
    block = payload.get("hourly")
    if not isinstance(block, dict) or "time" not in block:
        raise RuntimeError("Open-Meteo archive: respuesta sin hourly.time")
    times = block["time"]
    # Construimos columnas alineadas longitud = len(times)
    rows: Dict[str, Any] = {"time": pd.to_datetime(times)}
    for k, v in block.items():
        if k == "time":
            continue
        if isinstance(v, list) and len(v) == len(times):
            rows[k] = v
    df = pd.DataFrame(rows)
    return df


def merge_raw_with_om(
    raw: pd.DataFrame,
    om: pd.DataFrame,
    *,
    date_col: str = "DATE",
    hour_col: str = "HOUR",
    timezone: str = "America/Monterrey",
) -> pd.DataFrame:
    """
    Cruza ``raw`` con columnas Open-Meteo por fecha local + hora entera (0–23).
    ``om`` debe tener columna ``time`` (datetime).
    """
    out = raw.copy()
    out[date_col] = pd.to_datetime(out[date_col])
    om2 = om.copy()
    # Normalizamos a fecha/hora local del mismo huso que el panel (sin tz en merge)
    om2["_dt"] = pd.to_datetime(om2["time"])
    if om2["_dt"].dt.tz is not None:
        om2["_dt"] = om2["_dt"].dt.tz_convert(timezone).dt.tz_localize(None)
    om2["_date"] = om2["_dt"].dt.normalize()
    om2["_hour"] = om2["_dt"].dt.hour
    weather_cols = [c for c in om2.columns if c not in ("time", "_dt", "_date", "_hour")]
    # Una fila por (día, hora) para evitar duplicados en el merge
    slim = om2[["_date", "_hour"] + weather_cols].drop_duplicates(subset=["_date", "_hour"])
    out["_date"] = out[date_col].dt.normalize()
    out["_hour"] = out[hour_col].astype(int)
    merged = out.merge(slim, left_on=["_date", "_hour"], right_on=["_date", "_hour"], how="left")
    merged = merged.drop(columns=["_date", "_hour"], errors="ignore")
    return merged


def weather_code_label(code: float) -> str:
    """
    Etiqueta breve WMO (simplificada) para ``weather_code`` Open-Meteo.
    Ver tabla: https://open-meteo.com/en/docs#weathervariables
    """
    try:
        c = int(round(float(code)))
    except (TypeError, ValueError):
        return "desconocido"
    if c == 0:
        return "despejado"
    if c in (1, 2, 3):
        return "parcial_nublado"
    if c in (45, 48):
        return "niebla"
    if c in (51, 53, 55, 56, 57):
        return "llovizna"
    if c in (61, 63, 65, 66, 67, 80, 81, 82):
        return "lluvia"
    if c in (71, 73, 75, 77, 85, 86):
        return "nieve"
    if c in (95, 96, 99):
        return "tormenta"
    return "otro"


def thunderstorm_flag(series: pd.Series) -> pd.Series:
    """Devuelve una máscara booleana: True donde el código WMO es tormenta (95, 96, 99)."""
    return series.round().astype(float).isin([95, 96, 99])
