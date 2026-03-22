"""
Optimización de reparto de incentivos entre zonas (supply-side).

Contexto operativo (ratio = ORDERS / CONNECTED_RT):
- Zonas con ratio alto: falta capacidad relativa → conviene **incentivar** para atraer
  más repartidores efectivos (sin modelar el mercado completo).
- Zonas con ratio ya bajo: no conviene seguir subiendo incentivos ahí (riesgo de
  **sobre-oferta** de repartidores / ocio).

Se formula un problema de optimización con restricciones (``scipy.optimize.minimize``,
método SLSQP) alineado a ideas de programación no lineal con restricciones
(``Teoria/Optimizacion/tema1.pdf`` en adelante).

Este módulo es **exploratorio**: los parámetros ``gamma`` y costes son calibrables;
no sustituye al motor M2 ni a políticas reales de Rappi.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import minimize


# ---------------------------------------------------------------------------
# Estructura de salida del optimizador
# ---------------------------------------------------------------------------


@dataclass
class RebalanceResult:
    """Contenedor con el resultado numérico del reparto óptimo de incentivos."""

    zones: List[str]  # nombres de zona en el mismo orden que los vectores
    orders: np.ndarray  # pedidos O_i (en el estado usado: pico o agregado)
    couriers: np.ndarray  # repartidores conectados C_i antes de incentivar
    ratio_before: np.ndarray  # r_i = O_i / C_i al inicio
    incentive: np.ndarray  # x_i ≥ 0: unidades de "presupuesto" asignadas por zona
    ratio_after: np.ndarray  # r'_i tras aplicar el modelo C' = C + γ·eff·x
    budget_used: float  # suma de x_i efectivamente asignada (≤ presupuesto B)
    success: bool  # si el solver SLSQP reportó convergencia satisfactoria
    message: str  # mensaje textual del optimizador (diagnóstico)
    niter: int  # iteraciones del solver
    raw: Dict[str, Any] = field(default_factory=dict)  # metadatos extra (pesos, eff, etc.)


# ---------------------------------------------------------------------------
# Utilidades: normalización y construcción de señales desde el análisis (P6 extendido)
# ---------------------------------------------------------------------------


def _normalize_positive(v: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    """
    Evita ceros/negativos y deja el vector con **media 1** para que el objetivo
    ponderado no cambie de escala global al meter pesos por zona.
    """
    a = np.maximum(np.asarray(v, dtype=float), eps)
    return a / np.mean(a)


def build_zone_priority_vector(
    zones: List[str],
    *,
    risk_df: Optional[pd.DataFrame] = None,
    zone_col: str = "ZONE",
    risk_col: str = "risk_score_display",
    p_sat_by_zone: Optional[pd.Series] = None,
    sens_rain_by_zone: Optional[pd.Series] = None,
    eps: float = 1e-12,
) -> Tuple[np.ndarray, pd.DataFrame]:
    """
    Construye **pesos por zona** para P6 a partir de señales del análisis previo.

    Combina (cuando existan) **risk score** (GAP5), **P(sat) media** por zona (logit)
    y **sensibilidad a lluvia** por zona. Cada factor se normaliza a media 1 en el
    conjunto de zonas; el peso final es la **media geométrica** de los factores
    disponibles (neutral 1.0 si falta un factor).

    Parameters
    ----------
    risk_df
        Tabla tipo GAP5 con columnas ``zone_col`` y ``risk_col`` (p. ej.
        ``risk_score_display``).
    p_sat_by_zone
        Serie indexada por zona: media de probabilidades de saturación (logit) en panel.
    sens_rain_by_zone
        Serie indexada por zona: |coef. precip.| del MCO por zona o columna análoga.
    """
    rows = []
    for z in zones:
        # Valores por defecto 1.0 = "neutral" si falta la señal para esa zona
        fac_r = fac_p = fac_s = 1.0
        if risk_df is not None and risk_col in risk_df.columns:
            sub = risk_df[risk_df[zone_col].astype(str) == str(z)]
            if len(sub) > 0:
                fac_r = float(sub.iloc[0][risk_col])
        if p_sat_by_zone is not None and z in p_sat_by_zone.index:
            fac_p = float(p_sat_by_zone.loc[z])
        elif p_sat_by_zone is not None:
            try:
                fac_p = float(p_sat_by_zone.loc[str(z)])
            except Exception:
                pass
        if sens_rain_by_zone is not None and z in sens_rain_by_zone.index:
            fac_s = float(sens_rain_by_zone.loc[z])
        elif sens_rain_by_zone is not None:
            try:
                fac_s = float(sens_rain_by_zone.loc[str(z)])
            except Exception:
                pass
        rows.append(
            {
                zone_col: z,
                "fac_risk": fac_r,
                "fac_p_sat": fac_p,
                "fac_sens_rain": fac_s,
            }
        )
    diag = pd.DataFrame(rows)
    # Cada columna en escala comparable (media 1) antes de combinar
    for c in ("fac_risk", "fac_p_sat", "fac_sens_rain"):
        diag[c + "_norm"] = _normalize_positive(diag[c].to_numpy(dtype=float), eps=eps)
    # Media geométrica: penaliza que falte señal en cualquiera de las tres dimensiones
    g = (
        diag["fac_risk_norm"].to_numpy(dtype=float)
        * diag["fac_p_sat_norm"].to_numpy(dtype=float)
        * diag["fac_sens_rain_norm"].to_numpy(dtype=float)
    ) ** (1.0 / 3.0)
    w = _normalize_positive(g, eps=eps)
    diag["priority_weight"] = w
    return w, diag


def build_supply_efficiency_vector(
    zones: List[str],
    beta_earnings: float,
    *,
    zone_col: str = "ZONE",
    risk_df: Optional[pd.DataFrame] = None,
    risk_col: str = "risk_score_display",
    mix_risk: float = 0.35,
    eps: float = 1e-12,
) -> Tuple[np.ndarray, pd.DataFrame]:
    """
    Eficiencia **relativa** por zona para traducir incentivo → capacidad (supply GAP2).

    ``C'_i = C_i + gamma * eff_i * x_i``. Se parte de un efecto marginal común
    ``beta_earnings`` (CONNECTED_RT ~ EARNINGS) y se modula ligeramente con el
    risk score de zona para reflejar heterogeneidad operativa documentada en el panel.

    ``mix_risk`` ∈ [0,1]: cuánto peso del risk score entra en ``eff_i`` (0 = homogéneo).
    """
    beta_earnings = float(beta_earnings)
    base = max(abs(beta_earnings), eps)  # magnitud mínima para no anular el canal supply
    n = len(zones)
    eff = np.full(n, base, dtype=float)
    if risk_df is not None and risk_col in risk_df.columns:
        # Mapa zona → risk; normalizamos y mezclamos con 1 para no sobre-amplificar
        rmap = risk_df.set_index(risk_df[zone_col].astype(str))[risk_col].to_dict()
        rv = np.array([float(rmap.get(str(z), 1.0)) for z in zones], dtype=float)
        rv = _normalize_positive(rv, eps=eps)
        eff = base * (1.0 - mix_risk + mix_risk * rv)
    d = pd.DataFrame({zone_col: zones, "supply_efficiency": eff, "beta_earnings_base": base})
    return eff, d


# ---------------------------------------------------------------------------
# Agregación del panel: totales vs. instante de máximo estrés por zona
# ---------------------------------------------------------------------------


def aggregate_zone_state(
    raw: pd.DataFrame,
    *,
    zone_col: str = "ZONE",
    orders_col: str = "ORDERS",
    couriers_col: str = "CONNECTED_RT",
) -> Tuple[List[str], np.ndarray, np.ndarray]:
    """
    Agrega el panel hora×día a totales por zona (suma de pedidos y repartidores-conectados).
    Útil para magnitudes globales; el **ratio** agregado suele estar muy cerca de 1.
    """
    g = raw.groupby(zone_col, sort=True).agg({orders_col: "sum", couriers_col: "sum"})
    zones = list(g.index.astype(str))
    O = g[orders_col].to_numpy(dtype=float)
    C = np.maximum(g[couriers_col].to_numpy(dtype=float), 1.0)  # evita división por 0
    return zones, O, C


def aggregate_zone_peak_stress(
    raw: pd.DataFrame,
    *,
    zone_col: str = "ZONE",
    orders_col: str = "ORDERS",
    couriers_col: str = "CONNECTED_RT",
) -> Tuple[List[str], np.ndarray, np.ndarray]:
    """
    Por cada zona, toma la **fila** (día–hora) donde ``ORDERS/CONNECTED_RT`` es
    máximo (estrés pico). Así el ratio entre zonas **difiere** y el optimizador
    puede repartir incentivos hacia las más saturadas en el peor momento.
    Requiere columna ``ratio`` o se calcula al vuelo.
    """
    df = raw.copy()
    if "ratio" not in df.columns:
        df["ratio"] = df[orders_col] / df[couriers_col].replace(0, np.nan)
    # idxmax devuelve el índice de fila con mayor ratio dentro de cada grupo zona
    idx = df.groupby(zone_col)["ratio"].idxmax()
    peak = df.loc[idx].set_index(zone_col)
    zones = list(peak.index.astype(str))
    O = peak[orders_col].to_numpy(dtype=float)
    C = np.maximum(peak[couriers_col].to_numpy(dtype=float), 1.0)
    return zones, O, C


# ---------------------------------------------------------------------------
# Optimización principal (SLSQP)
# ---------------------------------------------------------------------------


def optimize_incentive_rebalance(
    zones: List[str],
    orders: np.ndarray,
    couriers: np.ndarray,
    budget: float,
    *,
    r_target: float = 1.05,
    ratio_floor: float = 0.72,
    ratio_cap: float = 10.0,  # reservado para extensiones; no se usa como restricción dura
    gamma: float = 1.0,
    lambda_budget: float = 0.05,
    max_incentive_per_zone: Optional[float] = None,
    zone_weights: Optional[np.ndarray] = None,
    supply_efficiency: Optional[np.ndarray] = None,
) -> RebalanceResult:
    """
    Reparte ``budget`` de **capacidad equivalente** (repartidores efectivos atraídos
    por incentivos, unidades abstractas) para acercar el ratio por zona a ``r_target``.

    Modelo local (``gamma`` normalmente 1)::
        C'_i = C_i + gamma * eff_i * x_i,   x_i >= 0
        r'_i = O_i / C'_i

    Con ``supply_efficiency`` omitido, ``eff_i = 1``. Las **zone_weights** ponderan
    el término cuadrático por zona (prioriza corregir desviaciones donde el análisis
    previo —risk, logit, lluvia— indica mayor urgencia).

    ``budget`` es el máximo de **sum_i x_i** (p. ej. “100” = hasta 100 repartidores
    equivalentes repartibles entre zonas). Con ``gamma=1`` y ``eff=1``, ``x_i`` son
    directamente esas unidades.

    Solo se permiten ``x_i > 0`` en zonas donde el ratio **actual** supera
    ``r_target`` (presión de demanda).

    Parámetros
    ----------
    ratio_floor
        Mínimo ratio permitido **después** de la intervención en zonas incentivadas
        (evita sobre-oferta de repartidores).
    lambda_budget
        Penalización por usar presupuesto: ``obj += lambda * sum(x)``.
    zone_weights
        Vector longitud ``n``, pesos relativos en ``sum_i w_i (r'_i - r_target)^2``.
        Si es ``None``, se usan unos.
    supply_efficiency
        Vector longitud ``n``, eficiencia marginal zona-específica (p. ej. desde
        GAP2). Si es ``None``, unos.
    """
    O = np.asarray(orders, dtype=float)
    C = np.maximum(np.asarray(couriers, dtype=float), 1.0)
    n = len(zones)
    if O.shape != (n,) or C.shape != (n,):
        raise ValueError("orders y couriers deben tener longitud len(zones)")
    # Pesos y eficiencias en el mismo orden que `zones`
    w = np.ones(n, dtype=float) if zone_weights is None else _normalize_positive(np.asarray(zone_weights, dtype=float))
    eff = np.ones(n, dtype=float) if supply_efficiency is None else _normalize_positive(np.asarray(supply_efficiency, dtype=float))
    if w.shape != (n,) or eff.shape != (n,):
        raise ValueError("zone_weights y supply_efficiency deben tener longitud len(zones)")
    r0 = O / C
    # Solo tiene sentido "inyectar" capacidad donde ya hay presión (ratio alto)
    high = r0 > r_target
    idx_high = np.where(high)[0]
    if len(idx_high) == 0:
        return RebalanceResult(
            zones=list(zones),
            orders=O,
            couriers=C,
            ratio_before=r0,
            incentive=np.zeros(n),
            ratio_after=r0.copy(),
            budget_used=0.0,
            success=True,
            message="Ninguna zona por encima de r_target; no hace falta incentivar.",
            niter=0,
        )

    if budget <= 0:
        return RebalanceResult(
            zones=list(zones),
            orders=O,
            couriers=C,
            ratio_before=r0,
            incentive=np.zeros(n),
            ratio_after=r0.copy(),
            budget_used=0.0,
            success=False,
            message="Presupuesto nulo o negativo.",
            niter=0,
        )

    cap = max_incentive_per_zone if max_incentive_per_zone is not None else budget
    # Solo optimizamos coordenadas x en las zonas "high"; el resto queda en 0
    bounds = [(0.0, float(min(cap, budget)))] * len(idx_high)

    def unpack_x(x_sub: np.ndarray) -> np.ndarray:
        """Pasa del vector reducido (solo zonas tensionadas) al vector completo n."""
        x_full = np.zeros(n)
        for k, j in enumerate(idx_high):
            x_full[j] = x_sub[k]
        return x_full

    def objective(x_sub: np.ndarray) -> float:
        """Mínimos cuadrados ponderados del gap al ratio objetivo + penalización L1 del uso de B."""
        x_full = unpack_x(x_sub)
        Cn = C + gamma * eff * x_full
        Cn = np.maximum(Cn, 1e-6)
        rn = O / Cn
        return float(np.sum(w * (rn - r_target) ** 2) + lambda_budget * np.sum(x_full))

    def cons_budget(x_sub: np.ndarray) -> float:
        # SLSQP usa g(x) ≥ 0 para desigualdades: budget - sum(x) ≥ 0  <=>  sum(x) ≤ budget
        return budget - float(np.sum(x_sub))

    cons = [{"type": "ineq", "fun": cons_budget}]

    # Solo zonas con presión (ratio > r_target) reciben x > 0; ahí exigimos suelo/techo
    # para no “inundar” de repartidores (ratio_floor) ni dejar saturación extrema (ratio_cap).
    def make_floor(j: int):
        def f(x_sub: np.ndarray) -> float:
            x_full = unpack_x(x_sub)
            Cn = np.maximum(C + gamma * eff * x_full, 1e-6)
            rn = O / Cn
            # rn[j] - ratio_floor ≥ 0  →  no bajar demasiado el ratio (evitar ocio excesivo)
            return float(rn[j] - ratio_floor)

        return f

    for j in idx_high:
        cons.append({"type": "ineq", "fun": make_floor(j)})
    # No forzamos techo duro en ratio: en x=0 puede ser r0 >> ratio_cap y sería infactible.
    # El objetivo ya penaliza alejarse de r_target; ratio_cap queda como parámetro reservado / futuros refinamientos.

    x0 = np.zeros(len(idx_high))
    res = minimize(
        objective,
        x0,
        method="SLSQP",
        bounds=bounds,
        constraints=cons,
        options={"maxiter": 500, "ftol": 1e-9},
    )

    x_opt = unpack_x(res.x)
    Cn = np.maximum(C + gamma * eff * x_opt, 1e-6)
    rn = O / Cn

    msg = res.message if isinstance(res.message, str) else str(res.message)
    return RebalanceResult(
        zones=list(zones),
        orders=O,
        couriers=C,
        ratio_before=r0,
        incentive=x_opt,
        ratio_after=rn,
        budget_used=float(np.sum(x_opt)),
        success=bool(res.success),
        message=msg,
        niter=int(res.nit),
        raw={
            "nit": res.nit,
            "status": res.status,
            "fun": res.fun,
            "zone_weights": w,
            "supply_efficiency": eff,
        },
    )


def result_to_dataframe(res: RebalanceResult) -> pd.DataFrame:
    """Exporta el resultado a tabla plana para el notebook (y gráficos)."""
    out: Dict[str, Any] = {
        "zone": res.zones,
        "orders": res.orders,
        "couriers": res.couriers,
        "ratio_before": res.ratio_before,
        "incentive": res.incentive,
        "ratio_after": res.ratio_after,
        "delta_ratio": res.ratio_after - res.ratio_before,
    }
    rw = res.raw
    if isinstance(rw, dict):
        if "zone_weights" in rw:
            out["zone_weight"] = rw["zone_weights"]
        if "supply_efficiency" in rw:
            out["supply_efficiency_used"] = rw["supply_efficiency"]
    return pd.DataFrame(out)
