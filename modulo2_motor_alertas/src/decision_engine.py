"""
Motor tipo sistema experto: reglas IF-THEN calibradas con el Módulo 1.

- Umbrales por zona (`alert_precip_mm_hr`, `precip_coef`, `sensitivity_index`).
- Multiplicador de incentivo: función del tier de riesgo, sensibilidad y exceso de precip.
- Proyección lineal local del ratio (validada en notebook).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class AlertDecision:
    zone: str
    precip_mm_hr_max: float
    horizon_hours: int
    risk: str
    risk_rank: int
    projected_ratio: float
    earnings_from: float
    earnings_to: float
    incentive_multiplier_pct: float
    sensitivity_index: float
    mm_precip_healthy_to_saturation_linear: Optional[float]
    action_minutes: int
    secondary_zones: List[str]
    expert_context: Dict[str, Any] = field(default_factory=dict)


def load_calibration(path: Path) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _ratio_projection(precip_mm: float, coef: float, baseline: float = 1.05) -> float:
    return float(max(0.3, baseline + coef * precip_mm))


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
    excess = precip_mm / max(precip_threshold, 0.1)
    if projected_ratio >= saturation + 0.35 or excess >= 2.0:
        return "CRITICO", 4
    if projected_ratio >= saturation + 0.05 or excess >= 1.35:
        return "ALTO", 3
    if projected_ratio >= saturation - 0.2 or projected_ratio >= healthy_max + 0.25:
        return "MEDIO", 2
    return "BAJO", 1


def _incentive_pct(
    risk_rank: int,
    sensitivity_index: float,
    precip_excess: float,
    cap: float,
) -> float:
    """Multiplicador incremental (no genérico): sube con tier, sensibilidad y exceso de lluvia."""
    tier_boost = {1: 0.0, 2: 0.06, 3: 0.12, 4: 0.20}.get(risk_rank, 0.0)
    sens_part = 0.22 * float(sensitivity_index) * min(1.0, precip_excess)
    excess_part = 0.12 * min(1.5, max(0.0, precip_excess - 1.0))
    return float(min(cap, tier_boost + sens_part + excess_part))


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
    zones: Dict[str, Any] = calibration["zones"]
    g = calibration["global"]
    if zone not in zones:
        return None
    z = zones[zone]
    # --- (a) Parámetros por zona y globales (salieron del Módulo 1 / calibration.json)
    thr = float(z["alert_precip_mm_hr"])
    coef = float(z["precip_coef"])
    base = float(z["base_earnings_mxn"])
    sens = float(z.get("sensitivity_index", 0.5))
    mm_lin = z.get("mm_precip_healthy_to_saturation_linear")
    cap = float(g.get("incentive_cap_pct", 0.35))
    sat_r = float(g.get("saturation_ratio", 1.8))
    hi = float(g.get("healthy_ratio_max", 1.2))

    # --- (b) Ventana de pronóstico y gate por umbral
    window = precip_next_hours[:horizon_hours]
    if not window:
        return None
    mx = max(window)
    if mx < thr:
        return None

    # --- (c) Riesgo experto a partir del ratio proyectado y exceso vs umbral
    projected = _ratio_projection(mx, coef)
    precip_excess = mx / max(thr, 0.1)
    risk_label, risk_rank = classify_risk_expert(
        projected, sat_r, hi, mx, thr
    )
    # --- (d) Incentivo numérico
    pct = _incentive_pct(risk_rank, sens, precip_excess, cap)
    earnings_to = round(base * (1.0 + pct), 1)

    # --- (e) Zonas secundarias para vigilancia cruzada
    sens_list = sorted(
        ((name, float(v.get("sensitivity_index", 0))) for name, v in zones.items() if name != zone),
        key=lambda x: -x[1],
    )
    secondary = [n for n, _ in sens_list[:secondary_top_n]]

    ctx = {
        "zone": zone,
        "forecast_precip_mm_hr": round(mx, 2),
        "threshold_precip_mm_hr": thr,
        "projected_ratio": round(projected, 3),
        "risk": risk_label,
        "risk_rank": risk_rank,
        "sensitivity_index": sens,
        "mm_precip_healthy_to_saturation_linear": mm_lin,
        "incentive_multiplier_pct": round(100 * pct, 2),
        "earnings_from": round(base, 2),
        "earnings_to": earnings_to,
        "horizon_hours": horizon_hours,
        "action_minutes": 30,
        "secondary_zones": secondary,
        "saturation_ratio": sat_r,
        "healthy_ratio_max": hi,
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
        incentive_multiplier_pct=round(100 * pct, 2),
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
    por el llamador) sobre su umbral ``alert_precip_mm_hr``. Empate → gana la primera
    en orden de iteración (estable).
    """
    zones = calibration["zones"]
    best: Optional[Tuple[float, str]] = None
    for name, mx in zone_precip:
        if name not in zones:
            continue
        thr = float(zones[name]["alert_precip_mm_hr"])
        excess = mx - thr
        if excess <= 0:
            continue
        if best is None or excess > best[0]:
            best = (excess, name)
    return best[1] if best else None
