"""
Configuración única del logging operativo (consola).

Nivel por variable de entorno ``OPS_LOG_LEVEL`` (DEBUG, INFO, WARNING, ERROR).
Los módulos usan loggers hijos de ``caso_tecnico`` para trazas coherentes en demo.
"""

from __future__ import annotations  # Anotaciones forward-compatible

import logging  # API estándar de Python para logs
import os  # Leer OPS_LOG_LEVEL del entorno
import sys  # stderr como destino del handler

# Evita registrar handlers duplicados si setup_ops_logging se llama varias veces
_CONFIGURED = False


def setup_ops_logging() -> None:
    """Idempotente: primera llamada instala el handler en stderr."""
    global _CONFIGURED
    # Salida temprana: ya hay configuración aplicada
    if _CONFIGURED:
        return
    _CONFIGURED = True
    # Nombre del nivel en mayúsculas; si no es válido, cae a INFO
    level_name = (os.environ.get("OPS_LOG_LEVEL") or "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    # Logger padre único para todo el caso técnico
    root_ops = logging.getLogger("caso_tecnico")
    root_ops.setLevel(level)
    # Solo añadir handler si aún no hay ninguno (evita duplicar líneas)
    if not root_ops.handlers:
        h = logging.StreamHandler(sys.stderr)  # Salida no bufferizada típica en contenedores
        h.setLevel(level)
        h.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s [%(name)s] %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )
        root_ops.addHandler(h)
    # No propagar al root de logging para no mezclar con otros handlers
    root_ops.propagate = False


def get_ops_logger(suffix: str) -> logging.Logger:
    """Logger bajo ``caso_tecnico.<suffix>`` (p. ej. ``weather``, ``pipeline``)."""
    setup_ops_logging()  # Garantiza handler antes de usar
    return logging.getLogger(f"caso_tecnico.{suffix}")
