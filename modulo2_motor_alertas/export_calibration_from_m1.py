#!/usr/bin/env python3
"""
Regenera `calibration.json` a partir del mismo panel y lógica que el notebook
`modulo1_diagnostico/notebooks/01_diagnostico_operacional.ipynb` (Módulo 1).

Reglas (documentadas también en README):
- ratio = ORDERS / CONNECTED_RT (CONNECTED_RT=0 → NaN)
- clasificación: saturacion si ratio > 1.8, etc. (igual que notebook)
- precip_coef: MCO por zona  ratio ~ PRECIPITATION_MM + C(HOUR) + C(dow)
  (dow = día de la semana desde DATE, 0=lun…6=dom; alineado a P2/GAP1 del notebook M1)
- mm_precip_healthy_to_saturation_linear: 0.6 / precip_coef si coef > 0
  (paso lineal 1.2 → 1.8 en ratio, Δ=0.6, como en el texto de P3 del notebook)
- sensitivity_index: |precip_coef| normalizado al máximo |coef| entre zonas
- base_earnings_mxn: mediana de EARNINGS por zona (redondeo a 2 decimales)
- alert_precip_mm_hr: p75 de PRECIPITATION_MM en filas saturacion;
  si p75 < 0.5 mm/h (saturación mayormente en horas secas en el panel),
  se usa 6.55 mm/h (valor de referencia del caso empaquetado para MTY_Guadalupe y San Nicolás)
- recommended_earnings_mxn: media de EARNINGS con PRECIPITATION_MM >= umbral de alerta
  (≥3 obs.); si no, 1.15 × mediana de EARNINGS. `decide_for_zone` la usa con base_earnings_mxn
  para el objetivo MXN (interpolación según ratio proyectado).

En ``global`` también se escriben ventanas de **ponderación horaria** (hora local operativa,
p. ej. comida/cena alineadas a picos de saturación en M1): el motor reduce el umbral de
lluvia de alerta en esas franjas y puede subir un escalón el riesgo (ver ``decision_engine``).

Uso (venv activado):
  Desde la raíz del repo:  python modulo2_motor_alertas/export_calibration_from_m1.py
  Desde modulo2_motor_alertas/:  python export_calibration_from_m1.py
  Opciones: --dry-run  |  --excel /ruta/datos.xlsx  |  --out /ruta/calibration.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

# Saturación “seca” en el panel: p75 de precip en filas saturacion < 0.5 mm/h
ALERT_DRY_SATURATION_FALLBACK_MM_HR = 6.55

DEFAULT_GLOBAL = {
    "healthy_ratio_max": 1.2,
    "saturation_ratio": 1.8,
    "incentive_cap_pct": 0.35,
    # Hora local para ponderar (Open-Meteo / operación MTY).
    "local_timezone": "America/Monterrey",
    # Franjas [start_hour, end_hour] inclusivas, 0–23. threshold_factor < 1 endurece el gate
    # (alerta con menos lluvia). risk_rank_boost suma escalones BAJO→…→CRÍTICO (tope 4).
    "hour_risk_windows": [
        {"start_hour": 12, "end_hour": 15, "label": "comida", "threshold_factor": 0.88, "risk_rank_boost": 0},
        {"start_hour": 19, "end_hour": 21, "label": "cena", "threshold_factor": 0.90, "risk_rank_boost": 0},
    ],
}


def clasificar(r: float) -> float | str:
    if pd.isna(r):
        return np.nan
    if r > 1.8:
        return "saturacion"
    if r < 0.5:
        return "sobre_oferta"
    if 0.9 <= r <= 1.2:
        return "saludable"
    return "intermedio"


def load_raw(excel_path: Path) -> pd.DataFrame:
    raw = pd.read_excel(excel_path, sheet_name="RAW_DATA")
    raw["ratio"] = raw["ORDERS"] / raw["CONNECTED_RT"].replace(0, np.nan)
    raw["clasificacion"] = raw["ratio"].apply(clasificar)
    raw["dow"] = pd.to_datetime(raw["DATE"], errors="coerce").dt.dayofweek
    return raw


def precip_coef_zone(raw: pd.DataFrame, zone: str) -> float:
    sub = raw[raw["ZONE"] == zone].dropna(subset=["ratio", "PRECIPITATION_MM", "HOUR", "dow"])
    if len(sub) < 48:
        raise ValueError(f"Zona {zone!r}: pocas filas válidas para regresión ({len(sub)}; mín. 48 con HOUR+dow)")
    model = smf.ols("ratio ~ PRECIPITATION_MM + C(HOUR) + C(dow)", data=sub).fit()
    return float(model.params["PRECIPITATION_MM"])


def alert_precip_mm_hr(raw: pd.DataFrame, zone: str) -> float:
    sat = raw[(raw["ZONE"] == zone) & (raw["clasificacion"] == "saturacion")]
    if len(sat) < 5:
        raise ValueError(f"Zona {zone!r}: menos de 5 observaciones en saturacion")
    p75 = float(sat["PRECIPITATION_MM"].quantile(0.75))
    if p75 < 0.5:
        return float(ALERT_DRY_SATURATION_FALLBACK_MM_HR)
    return p75


def recommended_earnings(raw: pd.DataFrame, zone: str, alert_thr: float) -> float:
    sub = raw[raw["ZONE"] == zone]
    hi = sub[sub["PRECIPITATION_MM"] >= alert_thr]
    base_med = float(sub["EARNINGS"].median())
    if len(hi) >= 3:
        return round(float(hi["EARNINGS"].mean()), 3)
    return round(base_med * 1.15, 2)


def build_calibration(raw: pd.DataFrame) -> Dict[str, Any]:
    zones = sorted(raw["ZONE"].dropna().unique())
    coefs: Dict[str, float] = {}
    for z in zones:
        coefs[z] = precip_coef_zone(raw, z)
    max_abs = max(abs(c) for c in coefs.values())
    if max_abs <= 0:
        raise ValueError("Todos los coeficientes de precipitación son cero")

    out_zones: Dict[str, Any] = {}
    for z in zones:
        coef = coefs[z]
        mm_lin = 0.6 / max(coef, 1e-9) if coef > 0 else float("inf")
        if not np.isfinite(mm_lin) or mm_lin > 1e6:
            mm_lin_val = None
        else:
            mm_lin_val = round(float(mm_lin), 2)

        sens = round(abs(coef) / max_abs, 4)
        base = round(float(raw.loc[raw["ZONE"] == z, "EARNINGS"].median()), 2)
        alert_thr = alert_precip_mm_hr(raw, z)
        rec = recommended_earnings(raw, z, alert_thr)

        out_zones[z] = {
            "precip_coef": coef,
            "sensitivity_index": sens,
            "mm_precip_healthy_to_saturation_linear": mm_lin_val,
            "alert_precip_mm_hr": alert_thr,
            "base_earnings_mxn": base,
            "recommended_earnings_mxn": rec,
        }
    return {"zones": out_zones, "global": dict(DEFAULT_GLOBAL)}


def write_calibration_json(excel_path: Path, out_path: Path) -> Dict[str, Any]:
    """
    Lee RAW_DATA desde `excel_path`, estima parámetros (Módulo 1) y escribe `out_path`.
    Expuesto para que `run_alert_engine.py` pueda encadenar recalibración + motor.
    """
    if not excel_path.is_file():
        raise FileNotFoundError(f"No se encuentra el Excel: {excel_path}")

    _src = Path(__file__).resolve().parent / "src"
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))
    from zones import validate_excel_zone_consistency  # noqa: E402

    zone_warnings, _ = validate_excel_zone_consistency(excel_path)
    for msg in zone_warnings:
        print(f"[zonas Excel] {msg}", file=sys.stderr)

    raw = load_raw(excel_path)
    cal = build_calibration(raw)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(cal, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return cal


def main() -> None:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Exportar calibration.json desde RAW_DATA (Módulo 1)")
    parser.add_argument(
        "--excel",
        type=Path,
        default=root.parent / "data" / "rappi_delivery_case_data.xlsx",
        help="Libro Excel con hoja RAW_DATA",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=root / "calibration.json",
        help="Ruta de salida del JSON",
    )
    parser.add_argument("--dry-run", action="store_true", help="Imprimir JSON a stdout sin escribir archivo")
    args = parser.parse_args()

    if not args.excel.is_file():
        raise SystemExit(f"No se encuentra el Excel: {args.excel}")

    if args.dry_run:
        raw = load_raw(args.excel)
        cal = build_calibration(raw)
        print(json.dumps(cal, indent=2, ensure_ascii=False) + "\n", end="")
    else:
        cal = write_calibration_json(args.excel, args.out)
        print(f"Escrito {args.out} ({len(cal['zones'])} zonas)")


if __name__ == "__main__":
    main()
