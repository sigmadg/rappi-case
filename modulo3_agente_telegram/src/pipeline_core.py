"""
Una pasada del agente operativo: Open-Meteo → motor M2 → debounce → RAG/LLM → Telegram.

Flujo (referencia rápida para demo):
  1. Cargar Excel y ``calibration.json``; puntos por zona (centroides).
  2. **Clima:** por zona, pronóstico Open-Meteo (o serie demo). Si la API falla tras
     reintentos, esa zona queda en 0 mm/h y se registra en auditoría; si **todas** fallan,
     estado ``weather_error``.
  3. Elegir zona primaria (mayor exceso sobre umbral) y decidir riesgo / incentivos (M2).
  4. **Debounce:** evita spam de Telegram en la misma severidad (TTL configurable).
  5. **M3:** JSON estructurado → mensaje (LLM o plantilla) → Telegram si aplica.

Salida: dict con ``status`` (``no_data``, ``weather_error``, ``no_alert``, ``no_decision``,
``debounced``, ``sent``, ``validate``) y campos de contexto.

Usado por ``run_agent.py`` y por el monitor LangChain (``langchain_monitor``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from decision_engine import decide_for_zone, load_calibration, pick_primary_zone
from ops_audit import append_audit
from ops_logging import get_ops_logger, setup_ops_logging
from rag_chain import build_telegram_alert
from telegram_sender import send_message
from weather_client import try_fetch_hourly_precipitation
from zones import default_data_path, load_centroids

from alert_event_log import append_alert_event
from debounce import debounce_ttl_sec_from_env, should_emit_alert
from monitor_ping import maybe_send_monitor_status_ping

setup_ops_logging()
_LOG = get_ops_logger("pipeline")

ROOT_PKG = Path(__file__).resolve().parents[1]
M2 = ROOT_PKG.parent / "modulo2_motor_alertas"
CAL_PATH = M2 / "calibration.json"
STATE_PATH = M2 / ".alert_state.json"
HORIZON = 2

HIST_NOTE = (
    "con lluvia >0.5 mm/hr la fracción de horas saturadas es ~8× vs sin lluvia fuerte "
    "(histórico 30 días, Monterrey)."
)


def _audit_tick_end(
    out: Dict[str, Any],
    *,
    dry_run: bool = False,
    validate: bool = False,
    telegram_already_sent: bool = False,
) -> Dict[str, Any]:
    """Una línea JSONL + log INFO; opcionalmente ping de monitor a Telegram (ver ``monitor_ping``)."""
    slim: Dict[str, Any] = {
        "status": out.get("status"),
        "zone": out.get("zone"),
        "risk": out.get("risk"),
        "reason": out.get("reason"),
        "detail": (str(out.get("detail") or ""))[:500],
    }
    if out.get("failures"):
        slim["weather_failures_count"] = len(out["failures"])
    append_audit(M2, "operational_tick", **slim)
    _LOG.info(
        "operational_tick status=%s zone=%s risk=%s",
        slim.get("status"),
        slim.get("zone"),
        slim.get("risk"),
    )
    try:
        maybe_send_monitor_status_ping(
            M2,
            out,
            dry_run=dry_run,
            validate=validate,
            telegram_already_sent=telegram_already_sent,
        )
    except Exception:
        _LOG.debug("monitor ping omitido por error no crítico", exc_info=True)
    return out


def run_operational_tick(
    *,
    demo: bool = False,
    force_send: bool = False,
    dry_run: bool = False,
    validate: bool = False,
    send_debounce_telegram: bool = True,
) -> Dict[str, Any]:
    """
    Returns dict con al menos ``status``:
    - ``no_data``: falta Excel
    - ``weather_error``: Open-Meteo no respondió para ninguna zona (tras reintentos)
    - ``no_alert``: ninguna zona supera umbral
    - ``no_decision``: motor sin decisión
    - ``debounced``: debounce bloqueó (puede haber enviado aviso corto a Telegram)
    - ``sent``: alerta principal enviada (o dry_run)
    - ``validate``: solo validación (``text``, ``issues``, ``used_llm``)
    """
    append_audit(
        M2,
        "operational_tick_start",
        demo=demo,
        dry_run=dry_run,
        force_send=force_send,
        validate=validate,
    )

    data_path = default_data_path()
    if not data_path.exists():
        return _audit_tick_end(
            {"status": "no_data", "detail": str(data_path)},
            dry_run=dry_run,
            validate=validate,
        )

    cal = load_calibration(CAL_PATH)
    centroids = load_centroids(data_path)

    # --- Fase clima: una serie de mm/h por zona (demo = sintético; vivo = Open-Meteo con reintentos).
    zone_precip: List[Tuple[str, List[float]]] = []
    weather_failures: List[Dict[str, Any]] = []

    for _, row in centroids.iterrows():
        zone = str(row["ZONE"])
        lat = float(row["LATITUDE_CENTER"])
        lon = float(row["LONGITUDE_CENTER"])
        if demo and zone == "Santiago":
            series = [7.2, 6.8, 5.1, 2.0] + [0.0] * 20
        elif demo:
            series = [0.0] * 24
        else:
            series, werr = try_fetch_hourly_precipitation(lat, lon, zone=zone)
            if werr:
                weather_failures.append({"zone": zone, "error": werr, "lat": lat, "lon": lon})
                append_audit(
                    M2,
                    "weather_zone_failed",
                    zone=zone,
                    error=str(werr)[:400],
                    lat=lat,
                    lon=lon,
                )
                series = [0.0] * 24
        zone_precip.append((zone, series))

    # Si ninguna zona obtuvo datos reales, no tiene sentido continuar (evita decisión sobre ceros por error).
    n_z = len(centroids)
    if not demo and n_z > 0 and len(weather_failures) == n_z:
        return _audit_tick_end(
            {
                "status": "weather_error",
                "detail": "Open-Meteo no entregó datos para ninguna zona tras reintentos",
                "failures": weather_failures,
            },
            dry_run=dry_run,
            validate=validate,
        )

    # --- Fase motor (M2): elegir zona con mayor exceso vs umbral y construir AlertDecision.
    flat_max = [(z, max(s[:HORIZON]) if s else 0.0) for z, s in zone_precip]
    primary = pick_primary_zone(flat_max, cal)
    if primary is None and demo:
        primary = "Santiago"
    if primary is None:
        return _audit_tick_end(
            {
                "status": "no_alert",
                "detail": "ninguna zona supera umbral",
                "weather_failures": weather_failures or None,
            },
            dry_run=dry_run,
            validate=validate,
        )

    append_audit(M2, "primary_zone_selected", zone=primary)

    precip_series = next(s for z, s in zone_precip if z == primary)
    d = decide_for_zone(primary, precip_series, cal, horizon_hours=HORIZON)
    if d is None:
        return _audit_tick_end(
            {"status": "no_decision", "detail": primary},
            dry_run=dry_run,
            validate=validate,
        )

    # --- Fase debounce (TTL + escalada); force_send y validate saltan este bloque.
    ttl = debounce_ttl_sec_from_env()
    if not force_send and not validate:
        fc = float(d.expert_context.get("forecast_precip_mm_hr", 0))
        thr_ctx = float(d.expert_context.get("threshold_precip_mm_hr", 0))
        emit, reason = should_emit_alert(
            d.zone,
            d.risk,
            STATE_PATH,
            ttl_sec=ttl,
            precip_mm_max=fc,
            threshold_mm=thr_ctx,
        )
        if not emit:
            ttl_min = max(1, round(ttl / 60))
            debounce_msg = (
                f"⏸️ (Debounce) {reason}\n"
                f"Zona: {d.zone}\n"
                f"Riesgo actual: {d.risk}\n"
                f"TTL ~{ttl_min} min: no se repite el mismo evento (severidad + lluvia sin empeoramiento "
                f"material); escalada sí. Cooldown global opcional: ALERT_GLOBAL_MIN_INTERVAL_SEC."
            )
            if not dry_run and send_debounce_telegram:
                try:
                    send_message(debounce_msg)
                except RuntimeError as e:
                    _LOG.warning("telegram debounce aviso no enviado: %s", e)
            append_audit(
                M2,
                "debounce_blocked",
                zone=d.zone,
                risk=d.risk,
                reason=reason,
            )
            return _audit_tick_end(
                {
                    "status": "debounced",
                    "reason": reason,
                    "zone": d.zone,
                    "risk": d.risk,
                    "debounce_message": debounce_msg,
                },
                dry_run=dry_run,
                validate=validate,
                telegram_already_sent=(not dry_run and send_debounce_telegram),
            )

    # --- Fase M3: JSON del motor → texto (LLM o plantilla) → Telegram si no es dry_run/validate.
    final, issues, used_llm = build_telegram_alert(d.expert_context, HIST_NOTE)

    if validate:
        return _audit_tick_end(
            {
                "status": "validate",
                "text": final,
                "issues": issues,
                "used_llm": used_llm,
                "zone": d.zone,
                "risk": d.risk,
            },
            dry_run=dry_run,
            validate=True,
        )

    if dry_run:
        append_audit(
            M2,
            "alert_prepared",
            zone=d.zone,
            risk=d.risk,
            dry_run=True,
            used_llm=used_llm,
        )
        return _audit_tick_end(
            {
                "status": "sent",
                "dry_run": True,
                "text": final,
                "zone": d.zone,
                "risk": d.risk,
            },
            dry_run=True,
            validate=validate,
        )

    send_message(final)
    append_alert_event(
        M2,
        {
            "zone": d.zone,
            "risk": d.risk,
            "forecast_precip_mm_hr": d.expert_context.get("forecast_precip_mm_hr"),
            "projected_ratio": d.expert_context.get("projected_ratio"),
            "earnings_from": d.expert_context.get("earnings_from"),
            "earnings_to": d.expert_context.get("earnings_to"),
            "horizon_hours": d.expert_context.get("horizon_hours"),
            "secondary_zones": d.expert_context.get("secondary_zones"),
        },
    )
    append_audit(
        M2,
        "telegram_alert_sent",
        zone=d.zone,
        risk=d.risk,
        used_llm=used_llm,
    )
    return _audit_tick_end(
        {
            "status": "sent",
            "text": final,
            "zone": d.zone,
            "risk": d.risk,
            "used_llm": used_llm,
        },
        dry_run=dry_run,
        validate=validate,
        telegram_already_sent=True,
    )
