"""
Anti alert fatigue (debounce) con escalada y deduplicación por **evento**:

- Misma zona y misma severidad dentro del TTL → no reenviar salvo **empeoramiento
  material** de la precipitación máxima en la ventana (mismo evento climático).
- Escalada de riesgo (p. ej. MEDIO → CRITICO) → siempre notificar.
- Opcional: ``ALERT_GLOBAL_MIN_INTERVAL_SEC`` limita el mínimo tiempo entre **cualquier**
  alerta emitida (todas las zonas), para no saturar a Ops.

Estado: ``.alert_state.json`` con claves por zona y ``__meta__`` para cooldown global.
"""

from __future__ import annotations  # Tipos como Dict[str, Any] sin import circular

import json  # Persistir estado en disco como JSON
import os  # Variables de entorno para TTL e intervalo global
import time  # Marca de tiempo unix para TTL y cooldown
from pathlib import Path  # Ubicación del archivo de estado
from typing import Any, Dict, Optional, Tuple  # Estado por zona es dict flexible

# Orden numérico para comparar severidad (mayor entero = riesgo más alto)
RISK_RANK: Dict[str, int] = {
    "BAJO": 1,
    "MEDIO": 2,
    "ALTO": 3,
    "CRITICO": 4,
    "CRÍTICO": 4,  # Variante con tilde por datos de entrada
}


def debounce_ttl_sec_from_env(default: int = 45 * 60) -> int:
    """
    Ventana anti-spam por zona (segundos), configurable con ALERT_DEBOUNCE_TTL_SEC en .env.
    Acotado entre 60 s y 7 días.
    """
    raw = (os.environ.get("ALERT_DEBOUNCE_TTL_SEC") or "").strip()  # Cadena vacía = usar default
    if not raw:
        return default  # 45 min por defecto si no hay variable
    try:
        v = int(raw)  # Parseo entero desde .env
        return max(60, min(v, 86400 * 7))  # Clamp: mínimo 1 min, máximo 7 días
    except ValueError:
        return default  # Texto ilegible: no romper, usar default


def global_min_interval_sec_from_env() -> int:
    """
    Mínimo tiempo entre alertas **cualquier zona** (0 = desactivado).
    ``ALERT_GLOBAL_MIN_INTERVAL_SEC`` en .env (p. ej. 600 = 10 min).
    """
    raw = (os.environ.get("ALERT_GLOBAL_MIN_INTERVAL_SEC") or "").strip()
    if not raw:
        return 0  # Desactivado: no hay cooldown entre zonas distintas
    try:
        v = int(raw)
        return max(0, min(v, 86400 * 7))  # 0 permitido; tope 7 días
    except ValueError:
        return 0


def _rank(risk: str) -> int:
    return RISK_RANK.get(risk.upper(), 0)  # 0 = etiqueta desconocida (tratar como mínimo)


def _load_state(path: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    if not path.exists():
        return {}, {}  # Estado virgen: sin zonas ni meta
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))  # Leer JSON completo
    except json.JSONDecodeError:
        return {}, {}  # Archivo corrupto: empezar de cero sin borrar (el caller puede sobrescribir)
    if not isinstance(raw, dict):
        return {}, {}  # Raíz debe ser objeto JSON
    meta = raw.pop("__meta__", None)  # Separar metadatos globales del dict de zonas
    if not isinstance(meta, dict):
        meta = {}  # Normalizar meta inválida
    return raw, meta  # raw = estado por clave de zona


def _write_state(
    path: Path,
    zones_state: Dict[str, Any],
    meta: Dict[str, Any],
) -> None:
    out = dict(zones_state)  # Copia superficial para no mutar el argumento
    if meta:
        out["__meta__"] = meta  # Reinyectar bloque meta en el JSON serializado
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")


def _material_precip_worsening(cur: float, prev: float) -> bool:
    """True si la precipitación empeora lo suficiente para tratarlo como evento distinto."""
    if prev < 0:
        return False  # Sin precipitación previa registrada: no comparar empeoramiento así
    # Umbral absoluto + relativo: nuevo pico claramente mayor que el anterior
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
    risk_label = risk_label.upper()  # Normalizar para coincidir con RISK_RANK
    now = time.time()  # Epoch float para comparaciones de TTL
    state, meta = _load_state(state_path)  # Estado previo por zona + meta global

    gmin = global_min_interval_sec_from_env()  # Segundos mínimos entre cualquier alerta
    last_any = float(meta.get("last_any_emit_ts") or 0.0)  # Última emisión global
    if gmin > 0 and last_any > 0 and (now - last_any) < gmin:
        return False, f"cooldown global ({gmin}s entre alertas, Ops)"  # Bloqueo cross-zona

    prev: Optional[Dict[str, Any]] = state.get(zone)  # Entrada previa de esta zona
    cur_r = _rank(risk_label)  # Rango numérico del riesgo actual

    if prev is None:
        # Primera vez que esta zona aparece en el estado: siempre persistir y emitir
        state[zone] = {
            "risk": risk_label,
            "ts": now,  # Inicio del TTL para esta zona
            "rank": cur_r,
            "last_precip": float(precip_mm_max) if precip_mm_max is not None else -1.0,  # -1 = sin dato
            "threshold_mm": float(threshold_mm) if threshold_mm is not None else None,
        }
        meta["last_any_emit_ts"] = now  # Actualizar cooldown global
        _write_state(state_path, state, meta)
        return True, "primera alerta en ventana"

    prev_r = int(prev.get("rank", _rank(str(prev.get("risk", "")))))  # Rank guardado o derivado del texto
    last_ts = float(prev.get("ts", 0))  # Última vez que se actualizó esta zona
    last_precip = float(prev.get("last_precip", -1.0))  # Pico de precip asociado al último envío

    if cur_r > prev_r:
        # Escalada MEDIO→CRITICO etc.: siempre notificar y refrescar estado
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
        return False, "debounce: bajada de riesgo dentro del TTL (no reenviar)"  # Evita ruido al mejorar clima

    if now - last_ts >= ttl_sec:
        # Ventana por zona expirada: nueva oportunidad de alertar con el mismo tier
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
            # Misma etiqueta de riesgo pero lluvia netamente peor → nuevo evento
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
