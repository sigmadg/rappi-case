"""
Anti alert fatigue (debounce) con escalado: se re-notifica si sube el riesgo
(p.ej. MEDIO → CRITICO) aunque no haya expirado el TTL; si el riesgo no sube,
se suprime hasta pasado el cooldown.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional


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

# Orden para comparar severidad (mayor = peor)
RISK_RANK: Dict[str, int] = {
    "BAJO": 1,
    "MEDIO": 2,
    "ALTO": 3,
    "CRITICO": 4,
    # alias por si el motor devolviera etiquetas en minúsculas mezcladas
    "CRÍTICO": 4,
}


def _rank(risk: str) -> int:
    return RISK_RANK.get(risk.upper(), 0)


def should_emit_alert(
    zone: str,
    risk_label: str,
    state_path: Path,
    *,
    ttl_sec: int = 45 * 60,
) -> tuple[bool, str]:
    """
    Returns (emit, reason).
    - Escalada: nuevo riesgo > último registrado → emitir siempre.
    - Misma o menor severidad dentro del TTL → no emitir.
    - TTL expirado → emitir si sigue habiendo condición de alerta (la capa superior decide).
    """
    risk_label = risk_label.upper()
    now = time.time()
    # Estado persistente: un dict JSON por zona con último riesgo y timestamp.
    state: Dict[str, Any] = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            state = {}

    key = zone
    prev: Optional[Dict[str, Any]] = state.get(key)
    cur_r = _rank(risk_label)

    if prev is None:
        state[key] = {"risk": risk_label, "ts": now, "rank": cur_r}
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        return True, "primera alerta en ventana"

    prev_r = int(prev.get("rank", _rank(str(prev.get("risk", "")))))
    last_ts = float(prev.get("ts", 0))

    # Escalada (p. ej. MEDIO → CRITICO): siempre notificar aunque no haya pasado el TTL.
    if cur_r > prev_r:
        state[key] = {"risk": risk_label, "ts": now, "rank": cur_r}
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        return True, f"escalada de riesgo ({prev.get('risk')} → {risk_label})"

    # Cooldown cumplido: permitir otro aviso aunque la severidad sea similar.
    if now - last_ts >= ttl_sec:
        state[key] = {"risk": risk_label, "ts": now, "rank": cur_r}
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        return True, "TTL expirado (cooldown)"

    # Misma o menor severidad y aún dentro del TTL → suprimir alerta principal (anti-fatiga).
    return False, "debounce: mismo o menor riesgo dentro del TTL"
