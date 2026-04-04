#!/usr/bin/env python3
"""
Motor de alertas (sistema experto): forecast Open-Meteo por punto **dentro del polígono WKT**
de cada zona (o centroide de respaldo) → reglas → salida accionable.

Uso:
  python run_alert_engine.py
  python run_alert_engine.py --recalibrate   # primero RAW_DATA → calibration.json, luego motor
  python run_alert_engine.py --demo   # simula lluvia fuerte en Santiago (sin red)

Debounce: deduplicación por zona + evento (riesgo y precipitación); escalada MEDIO→CRITICO;
opcional ALERT_GLOBAL_MIN_INTERVAL_SEC (mínimo entre alertas en cualquier zona).
Estado: ``.alert_state.json`` o env ``ALERT_STATE_PATH`` (debounce separado del monitor M3 en Docker).

Orden de ``run()``:
  validar Excel → (opcional) recalibrar → clima por zona → motor → debounce → imprimir decisión.
Códigos de salida: 0 OK, 1 error de datos/recalibración, 2 fallo total de clima.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
# Importar módulos locales (decision_engine, weather_client, …) desde src/.
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

load_dotenv(ROOT.parent / ".env")

from debounce import debounce_ttl_sec_from_env, should_emit_alert  # noqa: E402
from decision_engine import (  # noqa: E402
    decide_for_zone,
    load_calibration,
    pick_primary_zone,
)
from ops_audit import append_audit  # noqa: E402
from ops_logging import get_ops_logger, setup_ops_logging  # noqa: E402
from weather_client import try_fetch_hourly_precipitation  # noqa: E402
from zones import (  # noqa: E402
    default_data_path,
    lat_lon_for_forecast_query,
    load_centroids,
    load_zone_polygons,
    validate_excel_zone_consistency,
)

CAL_PATH = ROOT / "calibration.json"
_raw_state = (os.environ.get("ALERT_STATE_PATH") or "").strip()
if _raw_state:
    _p = Path(_raw_state)
    STATE_PATH = (_p if _p.is_absolute() else ROOT / _p).resolve()
else:
    STATE_PATH = ROOT / ".alert_state.json"
HORIZON = 2


def _recalibrate_from_excel(excel_path: Path, cal_path: Path) -> None:
    """Regenera `calibration.json` con la misma lógica que `export_calibration_from_m1.py`."""
    spec = importlib.util.spec_from_file_location(
        "_m1_export_calibration_module",
        ROOT / "export_calibration_from_m1.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("No se pudo cargar export_calibration_from_m1.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.write_calibration_json(excel_path, cal_path)


def run(*, demo: bool = False, verbose: bool = False, recalibrate: bool = False) -> int:
    setup_ops_logging()
    log = get_ops_logger("alert_engine")
    append_audit(ROOT, "alert_engine_start", demo=demo, verbose=verbose, recalibrate=recalibrate)

    # --- Entrada de datos
    data_path = default_data_path()
    if not data_path.exists():
        print(f"No se encuentra el dataset: {data_path}", file=sys.stderr)
        return 1

    zone_warnings, _ = validate_excel_zone_consistency(data_path)
    for msg in zone_warnings:
        print(f"[zonas Excel] {msg}", file=sys.stderr)

    if recalibrate:
        try:
            print(
                f"Recalibrando calibration.json desde {data_path.resolve()}…",
                file=sys.stderr,
            )
            _recalibrate_from_excel(data_path, CAL_PATH)
        except Exception as e:
            print(f"Error al recalibrar: {e}", file=sys.stderr)
            return 1

    # --- Calibración y geometría (misma fuente que M3)
    cal = load_calibration(CAL_PATH)
    centroids = load_centroids(data_path)
    polygons = load_zone_polygons(data_path)

    # --- Pronóstico por zona (WKT → punto de query; fallo por zona → ceros + auditoría)
    zone_precip: list[tuple[str, list[float]]] = []
    weather_failures: list[dict] = []

    for _, row in centroids.iterrows():
        zone = str(row["ZONE"])
        lat, lon, _src = lat_lon_for_forecast_query(zone, row, polygons)
        # Demo: precip máx. en 2h ~4.5 mm/h → ratio ~1.9 y riesgo ALTO (ilustrativo tipo enunciado)
        if demo and zone == "Santiago":
            series = [4.5, 4.2, 3.0, 1.0] + [0.0] * 20
        elif demo:
            series = [0.0] * 24
        else:
            series, werr = try_fetch_hourly_precipitation(lat, lon, zone=zone)
            if werr:
                weather_failures.append({"zone": zone, "error": werr})
                append_audit(
                    ROOT,
                    "weather_zone_failed",
                    zone=zone,
                    error=str(werr)[:400],
                    lat=lat,
                    lon=lon,
                )
                log.warning("Open-Meteo zona %s: %s", zone, werr)
                series = [0.0] * 24

        zone_precip.append((zone, series))

    n_z = len(centroids)
    if not demo and n_z > 0 and len(weather_failures) == n_z:
        msg = "Open-Meteo no entregó datos para ninguna zona tras reintentos."
        print(msg, file=sys.stderr)
        append_audit(ROOT, "alert_engine_weather_total_failure", failures=weather_failures[:30])
        log.error(msg)
        return 2

    # --- Reglas M2 + debounce (misma lógica que pipeline_core, sin Telegram/LLM)
    flat_max = [(z, max(s[:HORIZON]) if s else 0.0) for z, s in zone_precip]
    primary = pick_primary_zone(flat_max, cal)
    if primary is None:
        if demo:
            primary = "Santiago"
        else:
            print("Sin riesgo inmediato: ninguna zona supera su umbral de precipitación.")
            return 0

    precip_series = next(s for z, s in zone_precip if z == primary)
    mx = max(precip_series[:HORIZON]) if precip_series else 0.0
    decision = decide_for_zone(primary, precip_series, cal, horizon_hours=HORIZON)
    if decision is None:
        print("No se pudo construir decisión.")
        return 1

    thr_ctx = float(
        decision.expert_context.get("threshold_precip_mm_hr_effective")
        or decision.expert_context.get("threshold_precip_mm_hr", 0)
    )
    emit, reason = should_emit_alert(
        decision.zone,
        decision.risk,
        STATE_PATH,
        ttl_sec=debounce_ttl_sec_from_env(),
        precip_mm_max=mx,
        threshold_mm=thr_ctx,
    )
    if not emit:
        print(f"(Debounce) Omitido: {reason}", file=sys.stderr)
        append_audit(
            ROOT,
            "debounce_blocked",
            zone=decision.zone,
            risk=decision.risk,
            reason=reason,
        )
        log.info("debounce omitido zona=%s %s", decision.zone, reason)
        return 0
    # Enunciado 2c: solo las dos zonas más sensibles (además de la primaria)
    zcal = cal.get("zones") or {}
    sens_pairs = sorted(
        ((n, float(zcal[n].get("sensitivity_index", 0))) for n in zcal if n != decision.zone),
        key=lambda x: -x[1],
    )
    secondary_two = [n for n, _ in sens_pairs[:2]]
    secs = ", ".join(secondary_two)

    lines = [
        f"Zona: {decision.zone}",
        f"Precipitación esperada: {mx:.1f} mm/hr en las próximas {HORIZON} horas",
        (
            f"Riesgo: {decision.risk} (ratio proyectado ~{decision.projected_ratio} "
            f"basado en histórico)"
        ),
        (
            f"Acción recomendada: subir earnings de {decision.earnings_from:.0f} a "
            f"{decision.earnings_to:.0f} MXN en los próximos {decision.action_minutes} min"
        ),
        f"Zonas secundarias a monitorear: {secs}",
    ]
    print("\n".join(lines))
    append_audit(
        ROOT,
        "alert_engine_decision",
        zone=decision.zone,
        risk=decision.risk,
        precip_mm_hr_max=round(mx, 2),
        debounce_allowed=True,
        weather_partial_failures=len(weather_failures),
    )
    log.info(
        "decisión zona=%s riesgo=%s mm/h≈%.2f",
        decision.zone,
        decision.risk,
        mx,
    )
    if verbose:
        mm_note = (
            f" (~{decision.mm_precip_healthy_to_saturation_linear:.1f} mm/hr lineal 1.2→1.8)"
            if decision.mm_precip_healthy_to_saturation_linear
            else ""
        )
        print(
            f"\n[detalle] debounce: {reason} | multiplicador +{decision.incentive_multiplier_pct:.1f}% "
            f"| sensibilidad {decision.sensitivity_index:.2f}{mm_note}",
            file=sys.stdout,
        )
    return 0


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--demo",
        action="store_true",
        help="Simula precipitación en Santiago (sin red); salida tipo enunciado 2c",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Muestra debounce, multiplicador y nota mm/h 1.2→1.8 tras el bloque principal",
    )
    p.add_argument(
        "--recalibrate",
        action="store_true",
        help=(
            "Antes del motor: vuelve a estimar calibration.json desde RAW_DATA del Excel "
            "(misma lógica que export_calibration_from_m1.py; requiere statsmodels)"
        ),
    )
    args = p.parse_args()
    raise SystemExit(
        run(demo=args.demo, verbose=args.verbose, recalibrate=args.recalibrate)
    )


if __name__ == "__main__":
    main()
