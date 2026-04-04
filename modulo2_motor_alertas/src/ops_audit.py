"""
Registro append-only para auditoría operativa: qué ocurrió, cuándo y por qué.

Escribe JSONL en ``modulo2_motor_alertas/.ops_audit.jsonl`` (no versionado).
Complementa ``.alert_events.jsonl`` (solo envíos a Telegram) y ``.monitor_ticks.jsonl``.
"""

from __future__ import annotations  # Permite anotar tipos con nombres aún no definidos

import json  # Serializar cada línea del log como JSON
from datetime import datetime, timezone  # Marca de tiempo UTC ISO para cada evento
from pathlib import Path  # Rutas al archivo de auditoría bajo la raíz M2
from typing import Any, Dict  # Campos extra del evento son arbitrarios pero tipados como dict

# Nombre fijo del archivo JSONL en el directorio del módulo 2
AUDIT_NAME = ".ops_audit.jsonl"


def audit_log_path(m2_root: Path) -> Path:
    # Ruta absoluta: carpeta del módulo + nombre del log
    return m2_root / AUDIT_NAME


def append_audit(m2_root: Path, event: str, **fields: Any) -> None:
    """
    Añade un evento con marca UTC. ``event`` es un nombre corto tipo:
    ``tick_start``, ``weather_zone_failed``, ``primary_zone``, ``debounced``, ``alert_sent``.
    """
    # Asegura que exista el directorio antes de abrir en modo append
    m2_root.mkdir(parents=True, exist_ok=True)
    # Registro mínimo: instante, tipo de evento y kwargs adicionales
    rec: Dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),  # ISO 8601 con Z implícito vía +00:00
        "event": event,  # Identificador corto del paso en el pipeline
        **fields,  # Metadatos (zona, riesgo, razón de debounce, etc.)
    }
    path = audit_log_path(m2_root)
    try:
        # Una línea JSON por evento (formato JSONL estándar)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except OSError:
        # Si disco lleno o permisos: no tumbar el motor por fallo de auditoría
        pass
