"""
Registro append-only de alertas **realmente enviadas** a Telegram (no dry-run).

- Una línea JSON por envío (zona, riesgo, métricas del motor, timestamp UTC).
- ``load_events_for_local_date`` filtra por día en zona horaria operativa (resumen diario).
- Complementa ``.ops_audit.jsonl`` (más granular) y ``.monitor_ticks.jsonl`` (ciclos del bucle).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9 (no debería ocurrir en 3.11+)
    ZoneInfo = None  # type: ignore[misc, assignment]

LOG_NAME = ".alert_events.jsonl"
DEFAULT_TZ = "America/Monterrey"


def event_log_path(m2_root: Path) -> Path:
    return m2_root / LOG_NAME


def append_alert_event(m2_root: Path, payload: Dict[str, Any]) -> None:
    """Añade un evento con ``ts`` UTC; típicamente llamado desde ``pipeline_core`` tras ``send_message``."""
    path = event_log_path(m2_root)
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _local_date_of_ts(ts_iso: str, tz_name: str) -> date | None:
    try:
        raw = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if raw.tzinfo is None:
        raw = raw.replace(tzinfo=timezone.utc)
    if ZoneInfo is None:
        return raw.date()
    return raw.astimezone(ZoneInfo(tz_name)).date()


def load_events_for_local_date(
    m2_root: Path,
    target: date,
    *,
    tz_name: str = DEFAULT_TZ,
) -> List[Dict[str, Any]]:
    path = event_log_path(m2_root)
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = row.get("ts")
            if not isinstance(ts, str):
                continue
            ld = _local_date_of_ts(ts, tz_name)
            if ld == target:
                out.append(row)
    out.sort(key=lambda r: r.get("ts", ""))
    return out
