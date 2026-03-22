"""
Anti alert fatigue (debounce) con escalada y deduplicación por **evento**:

- Misma zona y misma severidad dentro del TTL → no reenviar salvo **empeoramiento
  material** de la precipitación máxima en la ventana (mismo evento climático).
- Escalada de riesgo (p. ej. MEDIO → CRITICO) → siempre notificar.
- Opcional: ``ALERT_GLOBAL_MIN_INTERVAL_SEC`` limita el mínimo tiempo entre **cualquier**
  alerta emitida (todas las zonas), para no saturar a Ops.

Estado: ``.alert_state.json`` con claves por zona y ``__meta__`` para cooldown global.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Orden para comparar severidad (mayor = peor)
RISK_RANK: Dict[str, int] = {
    "BAJO": 1,
    "MEDIO": 2,
    "ALTO": 3,
    "CRITICO": 4,
    "CRÍTICO": 4,
}


def debounce_ttl_sec_from_env(default: int = 45 * 60) -> int:
    """
    Ventana anti-spam por zona (segundos), configurable con ALERT_DEBOUNCE_TTL_SEC en .env.
    Acotado entre 60 s y 7 días.
    """
    raw = (os.environ.get("ALERT_DEBOUNCE_TTL_SEC") or "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
        return max(60, min(v, 86400 * 7))
    except ValueError:
        return default


def global_min_interval_sec_from_env() -> int:
    """
    Mínimo tiempo entre alertas **cualquier zona** (0 = desactivado).
    ``ALERT_GLOBAL_MIN_INTERVAL_SEC`` en .env (p. ej. 600 = 10 min).
    """
    raw = (os.environ.get("ALERT_GLOBAL_MIN_INTERVAL_SEC") or "").strip()
    if not raw:
        return 0
    try:
        v = int(raw)
        return max(0, min(v, 86400 * 7))
    except ValueError:
        return 0


def _rank(risk: str) -> int:
    return RISK_RANK.get(risk.upper(), 0)


def _load_state(path: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    if not path.exists():
        return {}, {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}, {}
    if not isinstance(raw, dict):
        return {}, {}
    meta = raw.pop("__meta__", None)
    if not isinstance(meta, dict):
        meta = {}
    return raw, meta


def _write_state(
    path: Path,
    zones_state: Dict[str, Any],
    meta: Dict[str, Any],
) -> None:
    out = dict(zones_state)
    if meta:
        out["__meta__"] = meta
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")


def _material_precip_worsening(cur: float, prev: float) -> bool:
    """True si la precipitación empeora lo suficiente para tratarlo como evento distinto."""
    if prev < 0:
        return False
    return cur >= prev + 0.5 or cur >= prev * 1.12 + 1e-9


def should_emit_alert(
    zone: str,
    risk_label: str,
    state_path: Path,
    *,
    ttl_sec: int = 45 * 60,
    precip_mm_max: Optional[float] = None,
    threshold_mm: Optional[float] = None,
) -> tuple[bool, str]:
    """
    Returns (emit, reason).

    - Escalada: nuevo riesgo > último registrado → emitir.
    - Cooldown global (si está configurado): demasiado pronto desde la última alerta
      en **cualquier** zona → suprimir.
    - Misma severidad dentro del TTL: suprimir salvo empeoramiento material de
      ``precip_mm_max`` vs último valor guardado (deduplicación por evento).
    - TTL expirado → emitir si sigue habiendo condición de alerta.
    """
    risk_label = risk_label.upper()
    now = time.time()
    state, meta = _load_state(state_path)

    gmin = global_min_interval_sec_from_env()
    last_any = float(meta.get("last_any_emit_ts") or 0.0)
    if gmin > 0 and last_any > 0 and (now - last_any) < gmin:
        return False, f"cooldown global ({gmin}s entre alertas, Ops)"

    prev: Optional[Dict[str, Any]] = state.get(zone)
    cur_r = _rank(risk_label)

    if prev is None:
        state[zone] = {
            "risk": risk_label,
            "ts": now,
            "rank": cur_r,
            "last_precip": float(precip_mm_max) if precip_mm_max is not None else -1.0,
            "threshold_mm": float(threshold_mm) if threshold_mm is not None else None,
        }
        meta["last_any_emit_ts"] = now
        _write_state(state_path, state, meta)
        return True, "primera alerta en ventana"

    prev_r = int(prev.get("rank", _rank(str(prev.get("risk", "")))))
    last_ts = float(prev.get("ts", 0))
    last_precip = float(prev.get("last_precip", -1.0))

    if cur_r > prev_r:
        state[zone] = {
            "risk": risk_label,
            "ts": now,
            "rank": cur_r,
            "last_precip": float(precip_mm_max) if precip_mm_max is not None else last_precip,
            "threshold_mm": float(threshold_mm) if threshold_mm is not None else prev.get("threshold_mm"),
        }
        meta["last_any_emit_ts"] = now
        _write_state(state_path, state, meta)
        return True, f"escalada de riesgo ({prev.get('risk')} → {risk_label})"

    if cur_r < prev_r and (now - last_ts) < ttl_sec:
        return False, "debounce: bajada de riesgo dentro del TTL (no reenviar)"

    if now - last_ts >= ttl_sec:
        state[zone] = {
            "risk": risk_label,
            "ts": now,
            "rank": cur_r,
            "last_precip": float(precip_mm_max) if precip_mm_max is not None else last_precip,
            "threshold_mm": float(threshold_mm) if threshold_mm is not None else prev.get("threshold_mm"),
        }
        meta["last_any_emit_ts"] = now
        _write_state(state_path, state, meta)
        return True, "TTL expirado (cooldown)"

    if cur_r == prev_r and precip_mm_max is not None and last_precip >= 0:
        if _material_precip_worsening(float(precip_mm_max), last_precip):
            state[zone] = {
                "risk": risk_label,
                "ts": now,
                "rank": cur_r,
                "last_precip": float(precip_mm_max),
                "threshold_mm": float(threshold_mm) if threshold_mm is not None else prev.get("threshold_mm"),
            }
            meta["last_any_emit_ts"] = now
            _write_state(state_path, state, meta)
            return True, "misma severidad pero precipitación empeora (evento distinto)"

    return False, "debounce: mismo riesgo y mismo evento de precipitación dentro del TTL"
