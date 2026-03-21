"""
Registro append-only para auditoría operativa: qué ocurrió, cuándo y por qué.

Escribe JSONL en ``modulo2_motor_alertas/.ops_audit.jsonl`` (no versionado).
Complementa ``.alert_events.jsonl`` (solo envíos a Telegram) y ``.monitor_ticks.jsonl``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

AUDIT_NAME = ".ops_audit.jsonl"


def audit_log_path(m2_root: Path) -> Path:
    return m2_root / AUDIT_NAME


def append_audit(m2_root: Path, event: str, **fields: Any) -> None:
    """
    Añade un evento con marca UTC. ``event`` es un nombre corto tipo:
    ``tick_start``, ``weather_zone_failed``, ``primary_zone``, ``debounced``, ``alert_sent``.
    """
    m2_root.mkdir(parents=True, exist_ok=True)
    rec: Dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **fields,
    }
    path = audit_log_path(m2_root)
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass
