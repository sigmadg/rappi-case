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

from __future__ import annotations  # Tipos adelantados (Dict[str, Any] sin comillas)

import time  # Cronómetro del tick para auditoría y métrica Prometheus
from pathlib import Path  # Rutas a M2, Excel, estado de debounce
from typing import Any, Dict, List, Optional, Tuple  # Contratos de datos entre fases

from decision_engine import decide_for_zone, load_calibration, pick_primary_zone  # Motor M2
from ops_audit import append_audit  # JSONL de trazabilidad en disco (módulo 2)
from ops_logging import get_ops_logger, setup_ops_logging  # Logger caso_tecnico.*
from rag_chain import build_telegram_alert  # LLM o plantilla → texto Telegram
from telegram_sender import send_message  # Envío real a la API de Telegram
from weather_client import try_fetch_hourly_precipitation  # Open-Meteo con reintentos
from zones import default_data_path, load_centroids  # Excel de zonas y centroides

from alert_event_log import append_alert_event  # Historial de alertas enviadas (JSONL)
from debounce import debounce_ttl_sec_from_env, should_emit_alert  # Anti-spam por zona/riesgo
from monitor_ping import maybe_send_monitor_status_ping  # Latido opcional a Telegram
from ops_prometheus import record_operational_tick as _prom_record_tick  # Contador/latencia

setup_ops_logging()  # Nivel/formato de logs según env del proceso
_LOG = get_ops_logger("pipeline")  # Logger con nombre jerárquico para filtrar en producción

ROOT_PKG = Path(__file__).resolve().parents[1]  # Carpeta ``modulo3_agente_telegram``
M2 = ROOT_PKG.parent / "modulo2_motor_alertas"  # Raíz del motor (calibración, auditoría, estado)
CAL_PATH = M2 / "calibration.json"  # Umbrales por zona, earnings, etc.
STATE_PATH = M2 / ".alert_state.json"  # Persistencia del debounce entre ticks
HORIZON = 2  # Horas de pronóstico que usa el motor para max precip en ventana corta

HIST_NOTE = (
    "con lluvia >0.5 mm/hr la fracción de horas saturadas es ~8× vs sin lluvia fuerte "
    "(histórico 30 días, Monterrey)."
)  # Texto fijo que el RAG/LLM puede citar como contexto histórico


def _audit_tick_end(
    out: Dict[str, Any],
    *,
    dry_run: bool = False,
    validate: bool = False,
    telegram_already_sent: bool = False,
    duration_sec: Optional[float] = None,
) -> Dict[str, Any]:
    """Una línea JSONL + log INFO; opcionalmente ping de monitor a Telegram (ver ``monitor_ping``)."""
    slim: Dict[str, Any] = {  # Subconjunto serializable (evita dicts enormes en audit)
        "status": out.get("status"),
        "zone": out.get("zone"),
        "risk": out.get("risk"),
        "reason": out.get("reason"),
        "detail": (str(out.get("detail") or ""))[:500],  # Trunca para no inflar el JSONL
    }
    if out.get("failures"):  # Solo en ``weather_error`` u otros paths con lista de fallos
        slim["weather_failures_count"] = len(out["failures"])
    append_audit(M2, "operational_tick", **slim)  # Escribe una línea en el log de auditoría M2
    _LOG.info(  # Nivel INFO para visibilidad en consola/Docker sin volcar todo el payload
        "operational_tick status=%s zone=%s risk=%s",
        slim.get("status"),
        slim.get("zone"),
        slim.get("risk"),
    )
    try:
        maybe_send_monitor_status_ping(  # Mensaje corto de “sigo vivo” si TELEGRAM_MONITOR_PING=1
            M2,
            out,
            dry_run=dry_run,
            validate=validate,
            telegram_already_sent=telegram_already_sent,
        )
    except Exception:
        _LOG.debug("monitor ping omitido por error no crítico", exc_info=True)  # No tumbar el tick
    try:
        _prom_record_tick(str(out.get("status") or "unknown"), duration_sec)  # Métricas /metrics
    except Exception:
        _LOG.debug("prometheus tick record omitido", exc_info=True)  # Observabilidad best-effort
    return out  # Mismo dict que recibió el caller (patrón fluido)


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
    t0 = time.perf_counter()  # Inicio monotónico para duración precisa

    def _dur() -> float:
        return time.perf_counter() - t0  # Segundos transcurridos hasta el return actual

    append_audit(  # Marca inicio del tick con flags (reproducir condiciones en soporte)
        M2,
        "operational_tick_start",
        demo=demo,
        dry_run=dry_run,
        force_send=force_send,
        validate=validate,
    )

    data_path = default_data_path()  # Ruta al Excel de datos (env o convención del repo)
    if not data_path.exists():
        return _audit_tick_end(  # Sin datos no hay centroides ni motor
            {"status": "no_data", "detail": str(data_path)},
            dry_run=dry_run,
            validate=validate,
            duration_sec=_dur(),
        )

    cal = load_calibration(CAL_PATH)  # Dict de calibración por zona (umbrales, earnings)
    centroids = load_centroids(data_path)  # DataFrame: ZONE, LAT, LON por fila

    # --- Fase clima: una serie de mm/h por zona (demo = sintético; vivo = Open-Meteo con reintentos).
    zone_precip: List[Tuple[str, List[float]]] = []  # Pares (nombre_zona, serie_24h_mm_h)
    weather_failures: List[Dict[str, Any]] = []  # Zonas donde la API falló (auditoría + decisión)

    for _, row in centroids.iterrows():  # Una pasada por cada zona geográfica
        zone = str(row["ZONE"])  # Identificador de zona (debe coincidir con calibration)
        lat = float(row["LATITUDE_CENTER"])  # Centroide para la celda Open-Meteo
        lon = float(row["LONGITUDE_CENTER"])
        if demo and zone == "Santiago":  # Demo: forzar escenario con lluvia en una zona
            series = [7.2, 6.8, 5.1, 2.0] + [0.0] * 20  # Picos al inicio, luego seco
        elif demo:
            series = [0.0] * 24  # Resto de zonas en demo sin precipitación
        else:
            series, werr = try_fetch_hourly_precipitation(lat, lon, zone=zone)  # HTTP + retries
            if werr:  # Error de red o API: no abortar todo el tick, registrar y usar ceros
                weather_failures.append({"zone": zone, "error": werr, "lat": lat, "lon": lon})
                append_audit(  # Trazabilidad por zona para diagnosticar cobertura meteorológica
                    M2,
                    "weather_zone_failed",
                    zone=zone,
                    error=str(werr)[:400],
                    lat=lat,
                    lon=lon,
                )
                series = [0.0] * 24  # Conservador: sin datos asumimos 0 mm/h
        zone_precip.append((zone, series))  # Acumula para el motor y para ``weather_error`` global

    # Si ninguna zona obtuvo datos reales, no tiene sentido continuar (evita decisión sobre ceros por error).
    n_z = len(centroids)  # Número esperado de zonas en el Excel
    if not demo and n_z > 0 and len(weather_failures) == n_z:  # Todas fallaron en modo vivo
        return _audit_tick_end(
            {
                "status": "weather_error",
                "detail": "Open-Meteo no entregó datos para ninguna zona tras reintentos",
                "failures": weather_failures,
            },
            dry_run=dry_run,
            validate=validate,
            duration_sec=_dur(),
        )

    # --- Fase motor (M2): elegir zona con mayor exceso vs umbral y construir AlertDecision.
    flat_max = [(z, max(s[:HORIZON]) if s else 0.0) for z, s in zone_precip]  # Max en primeras H h
    primary = pick_primary_zone(flat_max, cal)  # Zona con mayor “exceso” sobre umbral calibrado
    if primary is None and demo:  # Demo sin umbral cruzado: igual mostrar flujo con Santiago
        primary = "Santiago"
    if primary is None:  # Ninguna zona supera umbral: no hay alerta operativa
        return _audit_tick_end(
            {
                "status": "no_alert",
                "detail": "ninguna zona supera umbral",
                "weather_failures": weather_failures or None,
            },
            dry_run=dry_run,
            validate=validate,
            duration_sec=_dur(),
        )

    append_audit(M2, "primary_zone_selected", zone=primary)  # Qué zona gobierna este tick

    precip_series = next(s for z, s in zone_precip if z == primary)  # Serie completa de la primaria
    d = decide_for_zone(primary, precip_series, cal, horizon_hours=HORIZON)  # AlertDecision + contexto
    if d is None:  # Motor devolvió sin decisión (datos insuficientes o regla no aplicable)
        return _audit_tick_end(
            {"status": "no_decision", "detail": primary},
            dry_run=dry_run,
            validate=validate,
            duration_sec=_dur(),
        )

    # --- Fase debounce (TTL + escalada); force_send y validate saltan este bloque.
    ttl = debounce_ttl_sec_from_env()  # Segundos entre repeticiones “iguales” (env)
    if not force_send and not validate:  # Forzar envío o modo checklist: no aplicar debounce
        fc = float(d.expert_context.get("forecast_precip_mm_hr", 0))  # Pronóstico agregado motor
        thr_ctx = float(  # Umbral efectivo o base para comparar empeoramiento
            d.expert_context.get("threshold_precip_mm_hr_effective")
            or d.expert_context.get("threshold_precip_mm_hr", 0)
        )
        emit, reason = should_emit_alert(  # Lee/escribe STATE_PATH; cooldown global opcional
            d.zone,
            d.risk,
            STATE_PATH,
            ttl_sec=ttl,
            precip_mm_max=fc,
            threshold_mm=thr_ctx,
        )
        if not emit:  # Misma severidad reciente sin escalada material
            ttl_min = max(1, round(ttl / 60))  # Minutos redondeados para el texto humano
            debounce_msg = (  # Aviso corto distinto a la alerta LLM larga
                f"⏸️ (Debounce) {reason}\n"
                f"Zona: {d.zone}\n"
                f"Riesgo actual: {d.risk}\n"
                f"TTL ~{ttl_min} min: no se repite el mismo evento (severidad + lluvia sin empeoramiento "
                f"material); escalada sí. Cooldown global opcional: ALERT_GLOBAL_MIN_INTERVAL_SEC."
            )
            if not dry_run and send_debounce_telegram:  # Puede desactivarse en tests
                try:
                    send_message(debounce_msg)  # Telegram: usuario ve por qué no hay alerta larga
                except RuntimeError as e:  # Falta token, chat, red, etc.
                    _LOG.warning("telegram debounce aviso no enviado: %s", e)
            append_audit(  # Correlacionar con métricas y soporte
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
                telegram_already_sent=(not dry_run and send_debounce_telegram),  # Para monitor_ping
                duration_sec=_dur(),
            )

    # --- Fase M3: JSON del motor → texto (LLM o plantilla) → Telegram si no es dry_run/validate.
    final, issues, used_llm = build_telegram_alert(d.expert_context, HIST_NOTE)  # RAG-lite

    if validate:  # Solo inspeccionar texto e incumplimientos de checklist, sin enviar
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
            duration_sec=_dur(),
        )

    if dry_run:  # Construir mensaje y auditar pero no llamar a Telegram
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
                "status": "sent",  # Semántica “listo”; ``dry_run: True`` aclara que no hubo envío
                "dry_run": True,
                "text": final,
                "zone": d.zone,
                "risk": d.risk,
            },
            dry_run=True,
            validate=validate,
            duration_sec=_dur(),
        )

    send_message(final)  # Envío de la alerta operativa completa
    append_alert_event(  # JSONL diario para resúmenes y post-mortem
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
    append_audit(  # Confirmación explícita de envío
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
        telegram_already_sent=True,  # Evita ping duplicado de “monitor” salvo debounced
        duration_sec=_dur(),
    )
