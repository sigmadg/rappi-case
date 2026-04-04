"""
Motor tipo sistema experto: reglas IF-THEN calibradas con el Módulo 1.

- Umbrales por zona (`alert_precip_mm_hr`, `precip_coef`, `sensitivity_index`).
- Objetivo de earnings en MXN: interpolación histórica entre `base_earnings_mxn` (mediana)
  y `recommended_earnings_mxn` (panel condicionado a lluvia ≥ umbral), según ratio
  proyectado entre healthy_max y saturación, con tope relativo global.
- Proyección lineal local del ratio (validada en notebook).
- Opcional: ``global.hour_risk_windows`` + ``local_timezone`` — en franjas (p. ej. comida/cena)
  se aplica un umbral de lluvia **efectivo** más bajo y un ``risk_rank_boost`` configurable.
"""

from __future__ import annotations  # AlertDecision y tipos anidados

import json  # Cargar calibration.json
from dataclasses import dataclass, field  # Estructura inmutable de la decisión
from datetime import datetime  # Hora local operativa con zona
from pathlib import Path  # Ruta al JSON de calibración
from typing import Any, Dict, List, Optional, Tuple, cast  # Tipos del motor


@dataclass
class AlertDecision:
    zone: str  # Zona primaria evaluada
    precip_mm_hr_max: float  # Máximo mm/h en la ventana de pronóstico
    horizon_hours: int  # Cuántas horas del forecast se consideran
    risk: str  # Etiqueta BAJO..CRITICO
    risk_rank: int  # Entero 1..4 coherente con risk
    projected_ratio: float  # Ratio operativo proyectado (M1 + precip)
    earnings_from: float  # MXN base (mediana histórica)
    earnings_to: float  # MXN objetivo tras blend y cap
    incentive_multiplier_pct: float  # (earnings_to/base - 1) en porcentaje
    sensitivity_index: float  # Sensibilidad de la zona a estrés
    mm_precip_healthy_to_saturation_linear: Optional[float]  # Nota mm/h del notebook M1
    action_minutes: int  # Ventana sugerida de acción (fija en demo)
    secondary_zones: List[str]  # Otras zonas a vigilar
    expert_context: Dict[str, Any] = field(default_factory=dict)  # Dict plano para logs/UI/Telegram


def load_calibration(path: Path) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)  # Estructura zones + global


def _operative_local_hour(calibration: Dict[str, Any]) -> int:
    g = calibration.get("global") or {}  # Bloque global del JSON
    tz_name = str(g.get("local_timezone") or "America/Monterrey")  # IANA timezone
    try:
        from zoneinfo import ZoneInfo  # Python 3.9+ (zona horaria real)

        return int(datetime.now(ZoneInfo(tz_name)).hour)  # 0..23 hora local
    except Exception:
        return int(datetime.now().hour)  # Fallback: hora del servidor sin TZ


def _hour_in_window(h: int, start_hour: int, end_hour: int) -> bool:
    if start_hour <= end_hour:
        return start_hour <= h <= end_hour  # Ventana normal mismo día
    return h >= start_hour or h <= end_hour  # Ventana que cruza medianoche (p. ej. 22–2)


def resolve_hour_risk_modifiers(calibration: Dict[str, Any]) -> Tuple[float, int, Dict[str, Any]]:
    """
    Según la hora local operativa, devuelve (threshold_factor, risk_rank_boost, meta).

    ``threshold_factor`` multiplica ``alert_precip_mm_hr`` (valores < 1 = alertar antes).
    ``risk_rank_boost`` suma escalones al rank de riesgo tras ``classify_risk_expert`` (tope 4).
    """
    g = calibration.get("global") or {}
    meta: Dict[str, Any] = {"local_hour": _operative_local_hour(calibration)}  # Hora actual para trazas
    if not g.get("hour_risk_enabled", True):
        meta["hour_weighting_applied"] = False
        meta["hour_weighting_reason"] = "disabled"
        return 1.0, 0, meta  # Sin modificación de umbral ni rank
    windows = g.get("hour_risk_windows")  # Lista de dicts con start_hour, end_hour, factores
    if not windows:
        meta["hour_weighting_applied"] = False
        meta["hour_weighting_reason"] = "no_windows"
        return 1.0, 0, meta
    h = cast(int, meta["local_hour"])  # Hora entera actual
    for w in windows:
        if not isinstance(w, dict):
            continue  # Ignorar entradas mal formadas
        sh = int(w.get("start_hour", -1))  # Inicio inclusive
        eh = int(w.get("end_hour", -1))  # Fin inclusive (puede cruzar medianoche)
        if sh < 0 or eh < 0:
            continue  # Ventana inválida
        if not _hour_in_window(h, sh, eh):
            continue  # Esta franja no aplica ahora
        raw_tf = float(w.get("threshold_factor", 1.0))  # Multiplicador de umbral de lluvia
        tf = max(0.25, min(1.5, raw_tf))  # Evitar valores extremos que rompan reglas
        boost = int(w.get("risk_rank_boost", 0))  # Suma al rank tras clasificar
        boost = max(0, min(3, boost))  # No subir más de 3 escalones de una vez
        meta["hour_weighting_applied"] = True
        meta["hour_window_label"] = w.get("label", "")  # Nombre legible (comida, cena, …)
        meta["hour_threshold_factor"] = tf
        meta["hour_risk_rank_boost"] = boost
        return tf, boost, meta  # Primera ventana que coincide gana
    meta["hour_weighting_applied"] = False
    meta["hour_weighting_reason"] = "no_match"
    return 1.0, 0, meta  # Ninguna franja activa


def _ratio_projection(precip_mm: float, coef: float, baseline: float = 1.05) -> float:
    return float(max(0.3, baseline + coef * precip_mm))  # Lineal en precip con piso de ratio


def classify_risk_expert(
    projected_ratio: float,
    saturation: float,
    healthy_max: float,
    precip_mm: float,
    precip_threshold: float,
) -> Tuple[str, int]:
    """
    Capas de riesgo alineadas a Operaciones:
    CRITICO / ALTO / MEDIO / BAJO (rank 4..1).
    """
    excess = precip_mm / max(precip_threshold, 0.1)  # Cuántas veces sobre el umbral efectivo
    if projected_ratio >= saturation + 0.35 or excess >= 2.0:
        return "CRITICO", 4  # Estrés extremo por ratio o por lluvia
    if projected_ratio >= saturation + 0.05 or excess >= 1.35:
        return "ALTO", 3
    if projected_ratio >= saturation - 0.2 or projected_ratio >= healthy_max + 0.25:
        return "MEDIO", 2
    return "BAJO", 1  # Por debajo de umbrales de alerta material


def _apply_risk_rank_boost(rank: int, boost: int) -> int:
    return int(max(1, min(4, rank + boost)))  # Clamp al rango de etiquetas válidas


def _incentive_pct(
    risk_rank: int,
    sensitivity_index: float,
    precip_excess: float,
    cap: float,
) -> float:
    """Multiplicador incremental (no genérico): sube con tier, sensibilidad y exceso de lluvia."""
    tier_boost = {1: 0.0, 2: 0.06, 3: 0.12, 4: 0.20}.get(risk_rank, 0.0)  # Por nivel de riesgo
    sens_part = 0.22 * float(sensitivity_index) * min(1.0, precip_excess)  # Zonas sensibles
    excess_part = 0.12 * min(1.5, max(0.0, precip_excess - 1.0))  # Solo si ya pasó el umbral base
    return float(min(cap, tier_boost + sens_part + excess_part))  # Nunca superar cap global


def earnings_mx_from_m1_projection(
    projected_ratio: float,
    base_mxn: float,
    recommended_mxn: float,
    healthy_max: float,
    saturation: float,
    risk_rank: int,
    incentive_cap_pct: float,
) -> Tuple[float, Dict[str, Any]]:
    """
    Traduce el ratio proyectado (coeficiente M1 + precip) en un **MXN objetivo** anclado al
    panel histórico: ``base_earnings_mxn`` (mediana por zona) y ``recommended_earnings_mxn``
    (media de EARNINGS cuando precip ≥ umbral de alerta de esa zona, export M1).

    En el tramo saludable→saturación se interpola linealmente; un pequeño refuerzo por tier
    de riesgo no puede superar ``base * (1 + incentive_cap_pct)``.
    """
    base = float(base_mxn)
    rec = float(recommended_mxn)
    if rec < base:
        rec = base * 1.05  # Recomendado debe estar al menos ligeramente sobre la mediana
    hi = float(healthy_max)  # Ratio “saludable” máximo
    sat = float(saturation)  # Ratio de saturación operativa
    span = max(sat - hi, 1e-6)  # Evitar división por cero en el tramo de estrés
    if projected_ratio <= hi:
        stress = 0.0  # Aún en régimen saludable
    elif projected_ratio >= sat:
        stress = 1.0  # Saturación completa
    else:
        stress = (float(projected_ratio) - hi) / span  # Interpolación 0..1 entre hi y sat
    stress = max(0.0, min(1.0, stress))  # Por si acaso
    blended = base + stress * (rec - base)  # MXN entre mediana y recomendado condicional
    tier_uplift = {1: 0.0, 2: 0.02, 3: 0.045, 4: 0.08}.get(int(risk_rank), 0.0)  # Pequeño plus por severidad
    boosted = blended * (1.0 + tier_uplift)
    cap_mult = 1.0 + float(incentive_cap_pct)  # Tope relativo al base
    earnings_to = min(boosted, base * cap_mult)  # No pasar del cap
    earnings_to = max(float(earnings_to), base)  # Nunca bajar de la mediana base
    meta = {
        "earnings_blend_stress": round(stress, 4),
        "earnings_anchor_recommended_mxn": round(rec, 3),
        "earnings_method": "m1_hist_blend_tier_cap",
    }
    return round(earnings_to, 1), meta


def decide_for_zone(
    zone: str,
    precip_next_hours: List[float],
    calibration: Dict[str, Any],
    horizon_hours: int = 2,
    secondary_top_n: int = 3,
) -> Optional[AlertDecision]:
    """
    Construye la decisión para **una** zona ya elegida como candidata.

    Pasos internos (útil al explicar en demo):
      (a) Leer umbrales globales y parámetros de la zona desde ``calibration``.
      (b) Tomar el máximo de precipitación en la ventana ``horizon_hours``; si no supera
          ``alert_precip_mm_hr``, no hay alerta (``None``).
      (c) Proyectar ratio operativo vía coeficiente M1 y clasificar riesgo en capas.
      (d) Calcular multiplicador de incentivo acotado y earnings sugeridos.
      (e) Listar ``secondary_zones`` (mayor sensibilidad) para el mensaje al operador.
    """
    zones: Dict[str, Any] = calibration["zones"]  # Todas las zonas calibradas
    g = calibration["global"]  # Umbrales y caps globales
    if zone not in zones:
        return None  # Zona desconocida en calibración
    z = zones[zone]  # Bloque de esta zona
    # --- (a) Parámetros por zona y globales (salieron del Módulo 1 / calibration.json)
    thr = float(z["alert_precip_mm_hr"])  # Umbral mm/h de alerta por zona
    coef = float(z["precip_coef"])  # Pendiente ratio–precip del M1
    base = float(z["base_earnings_mxn"])  # Mediana histórica
    recommended = float(z.get("recommended_earnings_mxn", base * 1.12))  # Panel condicionado a lluvia
    sens = float(z.get("sensitivity_index", 0.5))  # 0..1 típico
    mm_lin = z.get("mm_precip_healthy_to_saturation_linear")  # Metadata opcional del export
    cap = float(g.get("incentive_cap_pct", 0.35))  # Tope de incentivo heurístico
    sat_r = float(g.get("saturation_ratio", 1.8))  # Ratio de saturación global
    hi = float(g.get("healthy_ratio_max", 1.2))  # Tope del tramo “saludable”

    thr_factor, rank_boost, hw_meta = resolve_hour_risk_modifiers(calibration)  # Franjas horarias
    thr_eff = float(max(0.05, thr * thr_factor))  # Umbral efectivo (más bajo si factor < 1)

    # --- (b) Ventana de pronóstico y gate por umbral (efectivo si hay ponderación horaria)
    window = precip_next_hours[:horizon_hours]  # Solo las primeras H horas
    if not window:
        return None  # Sin datos de precip
    mx = max(window)  # Pico esperado en la ventana
    if mx < thr_eff:
        return None  # No amerita alerta: bajo umbral efectivo

    # --- (c) Riesgo experto a partir del ratio proyectado y exceso vs umbral efectivo
    projected = _ratio_projection(mx, coef)  # Ratio operativo sintético
    precip_excess = mx / max(thr_eff, 0.1)  # Para capas CRITICO/ALTO y heurística
    risk_label, risk_rank = classify_risk_expert(
        projected, sat_r, hi, mx, thr_eff
    )
    risk_rank = _apply_risk_rank_boost(risk_rank, rank_boost)  # Subir tier en franjas críticas
    risk_label = {1: "BAJO", 2: "MEDIO", 3: "ALTO", 4: "CRITICO"}.get(risk_rank, risk_label)  # Re-sincronizar texto
    # --- (d) MXN objetivo desde histórico M1 (mediana → recomendado condicional a lluvia)
    earnings_to, earn_meta = earnings_mx_from_m1_projection(
        projected, base, recommended, hi, sat_r, risk_rank, cap
    )
    pct_realized = (earnings_to / base) - 1.0 if base > 0 else 0.0  # Incentivo “real” del blend
    pct_heuristic = _incentive_pct(risk_rank, sens, precip_excess, cap)  # Comparación heurística

    # --- (e) Zonas secundarias para vigilancia cruzada
    sens_list = sorted(
        ((name, float(v.get("sensitivity_index", 0))) for name, v in zones.items() if name != zone),
        key=lambda x: -x[1],  # Mayor sensibilidad primero
    )
    secondary = [n for n, _ in sens_list[:secondary_top_n]]  # Top N excluyendo la primaria

    ctx = {
        "zone": zone,
        "forecast_precip_mm_hr": round(mx, 2),
        "threshold_precip_mm_hr": thr,
        "threshold_precip_mm_hr_effective": round(thr_eff, 4),
        "hour_risk_weighting": hw_meta,
        "projected_ratio": round(projected, 3),
        "risk": risk_label,
        "risk_rank": risk_rank,
        "sensitivity_index": sens,
        "mm_precip_healthy_to_saturation_linear": mm_lin,
        "incentive_multiplier_pct": round(100 * pct_realized, 2),
        "incentive_heuristic_pct": round(100 * pct_heuristic, 2),
        "recommended_earnings_mxn": round(recommended, 3),
        "earnings_from": round(base, 2),
        "earnings_to": earnings_to,
        "horizon_hours": horizon_hours,
        "action_minutes": 30,
        "secondary_zones": secondary,
        "saturation_ratio": sat_r,
        "healthy_ratio_max": hi,
        **earn_meta,
    }

    return AlertDecision(
        zone=zone,
        precip_mm_hr_max=mx,
        horizon_hours=horizon_hours,
        risk=risk_label,
        risk_rank=risk_rank,
        projected_ratio=round(projected, 2),
        earnings_from=round(base, 1),
        earnings_to=earnings_to,
        incentive_multiplier_pct=round(100 * pct_realized, 2),
        sensitivity_index=sens,
        mm_precip_healthy_to_saturation_linear=float(mm_lin) if mm_lin is not None else None,
        action_minutes=30,
        secondary_zones=secondary,
        expert_context=ctx,
    )


def pick_primary_zone(
    zone_precip: List[Tuple[str, float]],
    calibration: Dict[str, Any],
) -> Optional[str]:
    """
    Elige la zona con **mayor exceso** de precipitación máxima (ventana ya agregada
    por el llamador) sobre su umbral ``alert_precip_mm_hr`` **efectivo** (misma
    ponderación horaria que ``decide_for_zone``). Empate → gana la primera
    en orden de iteración (estable).
    """
    thr_factor, _, _ = resolve_hour_risk_modifiers(calibration)  # Mismo factor horario para todas las zonas
    zones = calibration["zones"]
    best: Optional[Tuple[float, str]] = None  # (exceso, nombre) del mejor candidato
    for name, mx in zone_precip:  # mx ya es el máximo por zona en la ventana del caller
        if name not in zones:
            continue  # Ignorar zonas sin calibración
        thr = float(zones[name]["alert_precip_mm_hr"])
        thr_eff = max(0.05, thr * thr_factor)  # Coherente con decide_for_zone
        excess = mx - thr_eff  # Cuánto “sobra” por encima del umbral efectivo
        if excess <= 0:
            continue  # Esta zona no está en alerta por lluvia
        if best is None or excess > best[0]:
            best = (excess, name)  # Actualizar si es el mayor exceso visto
    return best[1] if best else None  # None si ninguna zona supera su umbral
