"""Resumen diario: eventos registrados vs máx. precipitación observada (archivo Open-Meteo)."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Tuple

from alert_event_log import DEFAULT_TZ, load_events_for_local_date

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore[misc, assignment]


def today_in_tz(tz_name: str = DEFAULT_TZ) -> date:
    if ZoneInfo is None:
        return datetime.utcnow().date()
    return datetime.now(ZoneInfo(tz_name)).date()


def _zone_coords_from_centroids(centroids) -> Dict[str, Tuple[float, float]]:
    out: Dict[str, Tuple[float, float]] = {}
    for _, row in centroids.iterrows():
        z = str(row["ZONE"])
        out[z] = (float(row["LATITUDE_CENTER"]), float(row["LONGITUDE_CENTER"]))
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
    events_all: List[dict] = load_events_for_local_date(
        m2_root, target_date, tz_name=tz_name
    )
    header = f"📊 Resumen operativo — {target_date} ({tz_name})"
    if not events_all:
        return f"{header}\n\nSin alertas enviadas este día."

    total = len(events_all)
    coords = _zone_coords_from_centroids(centroids)
    observed_cache: Dict[str, float] = {}
    if include_archive:
        from weather_client import archive_daily_max_precip_mm_hr

        zones_needed = {str(e.get("zone", "")) for e in events_all if e.get("zone")}
        for z in zones_needed:
            if z not in coords:
                continue
            lat, lon = coords[z]
            try:
                observed_cache[z] = archive_daily_max_precip_mm_hr(lat, lon, target_date)
            except Exception as e:
                try:
                    from ops_logging import get_ops_logger

                    get_ops_logger("daily_summary").warning(
                        "archive Open-Meteo zona=%s día=%s: %s",
                        z,
                        target_date,
                        e,
                    )
                except Exception:
                    pass
                observed_cache[z] = -1.0  # marcador N/D

    tail = ""
    events = events_all
    if len(events) > max_events:
        omitted = len(events) - max_events
        tail = f"\n… ({omitted} eventos anteriores omitidos)\n"
        events = events[-max_events:]

    lines = [
        header,
        f"Total eventos registrados: {total}",
    ]
    if total > max_events:
        lines.append(f"(Mostrando los últimos {max_events})")
    lines.append("")
    for i, ev in enumerate(events, 1):
        z = str(ev.get("zone", "?"))
        risk = str(ev.get("risk", "?"))
        fc = ev.get("forecast_precip_mm_hr")
        ratio = ev.get("projected_ratio")
        ef = ev.get("earnings_from")
        et = ev.get("earnings_to")
        ts = ev.get("ts", "")[:19].replace("T", " ")
        fc_s = f"{fc}" if fc is not None else "—"
        ratio_s = f"{ratio}" if ratio is not None else "—"
        earn_s = ""
        if ef is not None and et is not None:
            earn_s = f" | incentivo {ef}→{et} MXN"

        obs_line = ""
        if include_archive:
            obs = observed_cache.get(z, -1.0)
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
    return "\n".join(lines)
