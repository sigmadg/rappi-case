"""
Métricas Prometheus para ticks operativos (pipeline M2/M3).

- Proceso **monitor**: servidor HTTP en PROMETHEUS_MONITOR_METRICS_PORT (default 9108).
- Proceso **uvicorn** (n8n bridge): mismo registro en ese proceso; expuesto en /metrics del FastAPI.

Desactivar todo: PROMETHEUS_METRICS_DISABLE=1
"""

from __future__ import annotations  # Tipos Optional sin comillas

import os  # PROMETHEUS_* y puerto del servidor de métricas
import threading  # Lock para arranque único del start_http_server
import time  # Marca de tiempo del último tick (Gauge)
from typing import Optional  # duration_sec opcional al registrar tick

# True si el operador desactiva métricas por entorno (sin crear contadores)
_DISABLED = (os.environ.get("PROMETHEUS_METRICS_DISABLE") or "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

_metrics = None  # Tupla lazy (Counter, Histogram, Gauge, Counter errores) tras primera creación
_standalone_started = False  # Evita dos start_http_server en el mismo proceso monitor
_standalone_lock = threading.Lock()  # Serializa el primer arranque del puerto 9108


def _ensure_metrics():
    global _metrics
    if _DISABLED:
        return None  # No registrar familia Prometheus
    if _metrics is not None:
        return _metrics  # Ya construido
    from prometheus_client import Counter, Gauge, Histogram  # Import pesado solo al usar

    # Contador por etiqueta status (no_alert, sent, debounced, …)
    tick_total = Counter(
        "rappi_operational_tick_total",
        "Ticks operativos completados",
        ("status",),
    )
    chain_errors = Counter(
        "rappi_monitor_chain_errors_total",
        "Excepciones no capturadas en el bucle del monitor (LangChain)",
    )
    tick_duration = Histogram(
        "rappi_operational_tick_duration_seconds",
        "Duración de run_operational_tick",
        buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 15.0, 60.0, float("inf")),
    )
    last_ts = Gauge(
        "rappi_operational_tick_last_unixtime",
        "Unix time del último tick completado en este proceso",
    )
    # Series visibles en /metrics y en Prometheus aunque aún no haya ticks (evita gráficos vacíos).
    for st in (
        "no_data",
        "weather_error",
        "no_alert",
        "no_decision",
        "debounced",
        "validate",
        "sent",
        "unknown",
    ):
        tick_total.labels(st)  # Crea la serie con valor 0 hasta el primer inc()
    _metrics = (tick_total, tick_duration, last_ts, chain_errors)
    return _metrics


def record_operational_tick(status: str, duration_sec: Optional[float] = None) -> None:
    m = _ensure_metrics()
    if m is None:
        return
    tick_total, tick_duration, last_ts, _chain_err = m
    st = (status or "unknown").strip() or "unknown"  # Etiqueta limpia para Prometheus
    tick_total.labels(st).inc()  # Un tick completado con este estado
    if duration_sec is not None and duration_sec >= 0:
        tick_duration.observe(duration_sec)  # Histograma de latencia del pipeline
    last_ts.set(time.time())  # “Último éxito” de ciclo para paneles tipo “¿sigue vivo?”


def ensure_metrics_registered_for_scrape() -> None:
    """Fuerza registro de métricas rappi_* (p. ej. arranque del puente uvicorn antes del primer /tick)."""
    _ensure_metrics()


def record_monitor_chain_error() -> None:
    m = _ensure_metrics()
    if m is None:
        return
    m[3].inc()  # chain_errors


def ensure_monitor_metrics_server(port: Optional[int] = None) -> bool:
    """Arranca un HTTP /metrics en un hilo daemon (solo proceso monitor).

    Returns:
        True si el servidor quedó activo (nuevo o ya existente), False si métricas deshabilitadas.
    """
    global _standalone_started
    if _DISABLED:
        return False
    with _standalone_lock:
        if _standalone_started:
            return True  # Ya hay thread escuchando
        p = port if port is not None else int(os.environ.get("PROMETHEUS_MONITOR_METRICS_PORT", "9108"))
        from prometheus_client import start_http_server  # Servidor WSGI mínimo en otro hilo

        start_http_server(p)  # Expone el registro por defecto en 0.0.0.0:p
        _standalone_started = True
        return True
