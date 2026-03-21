"""
Cliente Open-Meteo (sin API key): precipitación horaria por coordenadas.

Resiliencia:
  - Reintentos con backoff ante timeout, errores de red y HTTP 429/5xx.
  - Variable ``WEATHER_HTTP_RETRIES`` (default 3), ``WEATHER_HTTP_TIMEOUT_SEC`` (30),
    ``WEATHER_HTTP_BACKOFF_SEC`` (0.7) en entorno.

Errores:
  - Tras agotar reintentos se lanza ``WeatherAPIError`` (o se devuelve error en
    ``try_fetch_hourly_precipitation`` para degradar por zona sin tumbar todo el tick).
"""

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import requests

from ops_logging import get_ops_logger

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"

_LOG = get_ops_logger("weather")

# Códigos HTTP donde tiene sentido reintentar (rate limit / origen caído)
_RETRYABLE_HTTP = {429, 500, 502, 503, 504}


class WeatherAPIError(RuntimeError):
    """Open-Meteo no entregó datos válidos tras reintentos."""


@dataclass
class HourlyPrecip:
    hours: List[str]
    precipitation_mm: List[float]


def _env_int(name: str, default: int, *, min_v: int = 1, max_v: int = 120) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
        return max(min_v, min(max_v, v))
    except ValueError:
        return default


def _env_float(name: str, default: float, *, min_v: float = 0.1, max_v: float = 120.0) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        v = float(raw)
        return max(min_v, min(max_v, v))
    except ValueError:
        return default


def _request_json(
    url: str,
    params: Dict[str, Any],
    *,
    context: str,
) -> Dict[str, Any]:
    """
    GET con reintentos: 429/5xx esperan y reintentan; 4xx otros fallan sin reintento.
    Al agotar intentos → ``WeatherAPIError`` (llamador o ``try_fetch`` lo traduce).
    """
    retries = _env_int("WEATHER_HTTP_RETRIES", 3, min_v=1, max_v=8)
    timeout = _env_float("WEATHER_HTTP_TIMEOUT_SEC", 30.0, min_v=2.0, max_v=120.0)
    backoff = _env_float("WEATHER_HTTP_BACKOFF_SEC", 0.7, min_v=0.1, max_v=10.0)

    last_exc: Optional[BaseException] = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            sc = r.status_code
            if sc in _RETRYABLE_HTTP:
                last_exc = RuntimeError(f"HTTP {sc}")
                _LOG.warning(
                    "%s HTTP %s intento %s/%s",
                    context,
                    sc,
                    attempt,
                    retries,
                )
            elif sc >= 400:
                raise WeatherAPIError(
                    f"{context}: HTTP {sc} body={r.text[:400]!r}"
                )
            else:
                try:
                    return r.json()
                except json.JSONDecodeError as e:
                    last_exc = e
                    _LOG.warning(
                        "%s JSON inválido intento %s/%s: %s",
                        context,
                        attempt,
                        retries,
                        e,
                    )
        except requests.Timeout as e:
            last_exc = e
            _LOG.warning(
                "%s timeout intento %s/%s (%ss)",
                context,
                attempt,
                retries,
                timeout,
            )
        except WeatherAPIError:
            raise
        except requests.RequestException as e:
            last_exc = e
            _LOG.warning(
                "%s error de red intento %s/%s: %s",
                context,
                attempt,
                retries,
                e,
            )

        if attempt < retries:
            sleep_s = backoff * (2 ** (attempt - 1)) + random.uniform(0, 0.25)
            time.sleep(sleep_s)

    raise WeatherAPIError(f"{context}: falló tras {retries} intentos: {last_exc}") from last_exc


def _hourly_precip_from_forecast_payload(data: Dict[str, Any], *, context: str) -> HourlyPrecip:
    h = data.get("hourly")
    if not isinstance(h, dict):
        raise WeatherAPIError(f"{context}: respuesta sin bloque hourly")
    times = h.get("time") or []
    precip = h.get("precipitation")
    if precip is None:
        precip = []
    if not isinstance(times, list):
        times = []
    if not isinstance(precip, list):
        precip = []
    out_mm = [float(x or 0) for x in precip]
    if not out_mm and times:
        _LOG.info("%s: hourly.precipitation vacío; se asume 0 mm", context)
        out_mm = [0.0] * len(times)
    return HourlyPrecip(hours=[str(t) for t in times], precipitation_mm=out_mm)


def fetch_hourly_precipitation(
    latitude: float, longitude: float, forecast_days: int = 3
) -> HourlyPrecip:
    """
    Precipitación horaria en mm (intensidad por hora) — compatible con el dataset.
    Lanza ``WeatherAPIError`` si Open-Meteo no responde de forma usable.
    """
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": "precipitation",
        "forecast_days": forecast_days,
        "timezone": "America/Monterrey",
    }
    ctx = f"forecast lat={latitude:.4f} lon={longitude:.4f}"
    data = _request_json(OPEN_METEO, params, context=ctx)
    return _hourly_precip_from_forecast_payload(data, context=ctx)


def try_fetch_hourly_precipitation(
    latitude: float,
    longitude: float,
    *,
    forecast_days: int = 3,
    zone: Optional[str] = None,
) -> Tuple[List[float], Optional[str]]:
    """
    Igual que ``fetch_hourly_precipitation`` pero **no lanza**: devuelve
    ``(serie_mm, None)`` o ``([], mensaje)`` para degradar una zona sin abortar todo el pipeline.
    """
    ztag = f" zone={zone}" if zone else ""
    try:
        hp = fetch_hourly_precipitation(latitude, longitude, forecast_days=forecast_days)
        return hp.precipitation_mm, None
    except WeatherAPIError as e:
        _LOG.error("Open-Meteo no disponible%s: %s", ztag, e)
        return [], str(e)


def max_precip_in_window(series: HourlyPrecip, start_idx: int, window_h: int) -> float:
    end = min(len(series.precipitation_mm), start_idx + window_h)
    if start_idx >= end:
        return 0.0
    return max(series.precipitation_mm[start_idx:end])


def fetch_archive_hourly_precipitation(
    latitude: float,
    longitude: float,
    start_d: date,
    end_d: date,
    *,
    timezone: str = "America/Monterrey",
    timeout: int = 30,
) -> HourlyPrecip:
    """Precipitación horaria del archivo (reanálisis) con los mismos reintentos que forecast."""
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_d.isoformat(),
        "end_date": end_d.isoformat(),
        "hourly": "precipitation",
        "timezone": timezone,
    }
    ctx = f"archive lat={latitude:.4f} lon={longitude:.4f} {start_d}..{end_d}"
    # timeout del requests lo toma _request_json desde env; el parámetro legacy se ignora en favor de env
    _ = timeout
    data = _request_json(OPEN_METEO_ARCHIVE, params, context=ctx)
    return _hourly_precip_from_forecast_payload(data, context=ctx)


def archive_daily_max_precip_mm_hr(
    latitude: float,
    longitude: float,
    day: date,
    *,
    timezone: str = "America/Monterrey",
) -> float:
    hp = fetch_archive_hourly_precipitation(
        latitude, longitude, day, day, timezone=timezone
    )
    if not hp.precipitation_mm:
        return 0.0
    return float(max(hp.precipitation_mm))
