"""Resumen diario: eventos registrados vs máx. precipitación observada (archivo Open-Meteo)."""

from __future__ import annotations  # Tipos con anotaciones modernas

from datetime import date, datetime  # Día calendario local y “ahora” con zona
from pathlib import Path  # m2_root apunta a modulo2_motor_alertas (logs de eventos)
from typing import Dict, List, Tuple  # Mapa zona→(lat,lon) y listas de eventos

from alert_event_log import DEFAULT_TZ, load_events_for_local_date  # TZ Monterrey por defecto + lector JSONL

try:
    from zoneinfo import ZoneInfo  # Python 3.9+: IANA tz database
except ImportError:
    ZoneInfo = None  # type: ignore[misc, assignment]  # Entornos viejos: caer a UTC naive


def today_in_tz(tz_name: str = DEFAULT_TZ) -> date:
    if ZoneInfo is None:  # Sin zoneinfo: usar fecha UTC del reloj del sistema
        return datetime.utcnow().date()
    return datetime.now(ZoneInfo(tz_name)).date()  # Fecha civil en la zona operativa (p. ej. America/Monterrey)


def _zone_coords_from_centroids(centroids) -> Dict[str, Tuple[float, float]]:
    out: Dict[str, Tuple[float, float]] = {}  # Acumulador nombre → par lat/lon
    for _, row in centroids.iterrows():  # Mismo Excel que usa el pipeline operativo
        z = str(row["ZONE"])
        out[z] = (float(row["LATITUDE_CENTER"]), float(row["LONGITUDE_CENTER"]))  # Centroide para archivo clima
    return out


def build_daily_summary_text(
    target_date: date,
    m2_root: Path,
    centroids,
    *,
    include_archive: bool = True,
    tz_name: str = DEFAULT_TZ,
    max_events: int = 25,
) -> str:
    events_all: List[dict] = load_events_for_local_date(  # Eventos cuyo timestamp cae en ese día local
        m2_root, target_date, tz_name=tz_name
    )
    header = f"📊 Resumen operativo — {target_date} ({tz_name})"  # Primera línea del mensaje Telegram
    if not events_all:
        return f"{header}\n\nSin alertas enviadas este día."  # Salida temprana sin llamadas a archivo

    total = len(events_all)  # Conteo completo antes de truncar visualización
    coords = _zone_coords_from_centroids(centroids)  # Necesario para consultar Open-Meteo por zona
    observed_cache: Dict[str, float] = {}  # Por zona: máx mm/h del día en archivo (o -1 = N/D)
    if include_archive:  # Puede desactivarse para tests offline o velocidad
        from weather_client import archive_daily_max_precip_mm_hr  # Import perezoso: evita carga si no hace falta

        zones_needed = {str(e.get("zone", "")) for e in events_all if e.get("zone")}  # Conjunto de zonas citadas
        for z in zones_needed:  # Una petición de archivo por zona distinta
            if z not in coords:  # Zona desconocida en el Excel actual: no hay lat/lon
                continue
            lat, lon = coords[z]
            try:
                observed_cache[z] = archive_daily_max_precip_mm_hr(lat, lon, target_date)  # API archivo histórico
            except Exception as e:  # Red, 404, parseo: no tumbar el resumen entero
                try:
                    from ops_logging import get_ops_logger

                    get_ops_logger("daily_summary").warning(
                        "archive Open-Meteo zona=%s día=%s: %s",
                        z,
                        target_date,
                        e,
                    )
                except Exception:
                    pass  # Si incluso el logger falla, seguir
                observed_cache[z] = -1.0  # marcador N/D

    tail = ""  # Texto opcional si se omitieron eventos viejos
    events = events_all
    if len(events) > max_events:  # Evitar mensajes Telegram gigantes
        omitted = len(events) - max_events  # Cuántos no se listan
        tail = f"\n… ({omitted} eventos anteriores omitidos)\n"
        events = events[-max_events:]  # Conservar los más recientes

    lines = [
        header,
        f"Total eventos registrados: {total}",
    ]
    if total > max_events:  # Aclarar que la lista está truncada
        lines.append(f"(Mostrando los últimos {max_events})")
    lines.append("")
    for i, ev in enumerate(events, 1):  # Numeración 1-based para lectura humana
        z = str(ev.get("zone", "?"))
        risk = str(ev.get("risk", "?"))
        fc = ev.get("forecast_precip_mm_hr")  # Valor al momento del envío de la alerta
        ratio = ev.get("projected_ratio")
        ef = ev.get("earnings_from")
        et = ev.get("earnings_to")
        ts = ev.get("ts", "")[:19].replace("T", " ")  # ISO acortado y espacio en lugar de T
        fc_s = f"{fc}" if fc is not None else "—"
        ratio_s = f"{ratio}" if ratio is not None else "—"
        earn_s = ""
        if ef is not None and et is not None:
            earn_s = f" | incentivo {ef}→{et} MXN"  # Fragmento opcional de la línea

        obs_line = ""
        if include_archive:
            obs = observed_cache.get(z, -1.0)  # -1 si no se consultó o falló
            if obs < 0:
                obs_line = " | observado (archivo día): N/D"
            else:
                obs_line = f" | observado (archivo día): {obs:.2f} mm/h máx."

        lines.append(
            f"{i}. [{ts} UTC…] {z} — {risk} | pronosticado al enviar: {fc_s} mm/h "
            f"| ratio proj. {ratio_s}{earn_s}{obs_line}"
        )

    lines.append(tail)
    lines.append("")
    lines.append(
        "Nota: “observado” es la máx. horaria del archivo meteorológico ese día en el "
        "centroide de la zona (proxy de impacto real vs pronóstico al momento del aviso)."
    )
    return "\n".join(lines)  # Un solo string multilínea para send_message
