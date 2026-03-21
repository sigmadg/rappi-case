"""
Configuración única del logging operativo (consola).

Nivel por variable de entorno ``OPS_LOG_LEVEL`` (DEBUG, INFO, WARNING, ERROR).
Los módulos usan loggers hijos de ``caso_tecnico`` para trazas coherentes en demo.
"""

from __future__ import annotations

import logging
import os
import sys

_CONFIGURED = False


def setup_ops_logging() -> None:
    """Idempotente: primera llamada instala el handler en stderr."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True
    level_name = (os.environ.get("OPS_LOG_LEVEL") or "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    root_ops = logging.getLogger("caso_tecnico")
    root_ops.setLevel(level)
    if not root_ops.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setLevel(level)
        h.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s [%(name)s] %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )
        root_ops.addHandler(h)
    root_ops.propagate = False


def get_ops_logger(suffix: str) -> logging.Logger:
    """Logger bajo ``caso_tecnico.<suffix>`` (p. ej. ``weather``, ``pipeline``)."""
    setup_ops_logging()
    return logging.getLogger(f"caso_tecnico.{suffix}")
