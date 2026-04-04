"""
Persistencia de ciclos del monitor para dashboard / auditoría.

- ``record_monitor_cycle``: tras cada ``chain.invoke`` del monitor (éxito o estado debounced, etc.).
- ``record_monitor_error``: si la cadena lanza excepción (registro con status error).
- Archivos bajo ``modulo2_motor_alertas/``: ``.monitor_ticks.jsonl`` (historial) y
  ``.monitor_status.json`` (último ciclo, lectura rápida para Django ``/monitor/``).
"""

from __future__ import annotations  # Path | None

import json  # Serializar filas JSONL y snapshot de estado
from datetime import datetime, timezone  # Marca UTC ISO en cada tick
from pathlib import Path  # Rutas bajo modulo2_motor_alertas
from typing import Any, Dict  # Config y filas flexibles

TICKS_NAME = ".monitor_ticks.jsonl"  # Append-only, una línea por ciclo
STATUS_NAME = ".monitor_status.json"  # Último ciclo para API Django


def m2_root_default() -> Path:
    # .../caso_tecnico/modulo3_agente_telegram/src/ → caso_tecnico/modulo2_motor_alertas
    return Path(__file__).resolve().parents[2] / "modulo2_motor_alertas"


def record_monitor_cycle(cfg: Dict[str, Any], *, m2_root: Path | None = None) -> None:
    """
    Escribe una línea en ``.monitor_ticks.jsonl`` y sobrescribe ``.monitor_status.json``
    con el último ciclo (lee Django u otras herramientas sin seguir el proceso).
    """
    root = m2_root or m2_root_default()
    root.mkdir(parents=True, exist_ok=True)
    r = cfg.get("result")
    if not isinstance(r, dict):
        r = {}  # Normalizar salida del pipeline
    reason = r.get("reason")
    detail = r.get("detail")
    row: Dict[str, Any] = {
        "ts": cfg.get("tick_finished_at") or datetime.now(timezone.utc).isoformat(),
        "tick_started_at": cfg.get("tick_started_at"),
        "status": r.get("status"),
        "zone": r.get("zone"),
        "risk": r.get("risk"),
        "reason": (str(reason)[:500] if reason is not None else None),
        "detail": (str(detail)[:400] if detail is not None else None),
        "demo": bool(cfg.get("demo")),
        "dry_run": bool(cfg.get("dry_run")),
        "force_send": bool(cfg.get("force_send")),
        "log_line": cfg.get("log_line"),
    }
    path = root / TICKS_NAME
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    snap = {"last": row, "updated_at": row["ts"]}  # Formato esperado por api_monitor_json
    (root / STATUS_NAME).write_text(
        json.dumps(snap, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def record_monitor_error(
    m2_root: Path,
    message: str,
    *,
    demo: bool = False,
    dry_run: bool = False,
    force_send: bool = False,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    msg = str(message)[:2000]  # Evitar líneas JSONL gigantes
    record_monitor_cycle(
        {
            "tick_started_at": None,
            "tick_finished_at": now,
            "demo": demo,
            "dry_run": dry_run,
            "force_send": force_send,
            "result": {"status": "error", "detail": msg},
            "log_line": f"[monitor] error: {msg[:400]}",
        },
        m2_root=m2_root,
    )
