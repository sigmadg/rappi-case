"""
Carga de geometrías de zona y utilidades point-in-polygon.

Orden típico en el motor:
  1) ``load_zone_polygons`` + ``load_centroids`` desde el Excel.
  2) Por cada zona, ``lat_lon_for_forecast_query`` elige el punto para Open-Meteo
     (dentro del polígono WKT si es válido; si no, centroide ZONE_INFO).
  3) ``validate_excel_zone_consistency`` (opcional) avisa si nombres o WKT no cuadran.
"""

from __future__ import annotations  # Tipos forward en anotaciones

from pathlib import Path  # Rutas al Excel y a data/
from typing import Any, Dict, List, Optional, Tuple  # Polígonos como dict nombre→geom

import pandas as pd  # Lectura de hojas Excel
from shapely import wkt  # Parser de Well-Known Text
from shapely.geometry import Point  # Geometría punto para contains()


def project_root() -> Path:
    """Raíz del repo (dos niveles por encima de este archivo: .../caso_tecnico)."""
    # Este archivo: caso_tecnico/modulo2_motor_alertas/src/zones.py → parents[2] = repo
    return Path(__file__).resolve().parents[2]


def load_zone_polygons(xlsx: Path) -> Dict[str, object]:
    """
    Devuelve ``{nombre_zona: geometría Shapely}`` solo para filas con WKT parseable.

    WKT debe leerse como texto; si Excel/pandas infieren float, Shapely falla.
    Celdas demasiado largas suelen indicar **truncado** en Excel (~32k caracteres);
    un WKT cortado no es geometría válida: esas zonas **no** entran aquí y el
    pipeline usa ``LATITUDE_CENTER``/``LONGITUDE_CENTER`` de ``ZONE_INFO`` en
    :func:`lat_lon_for_forecast_query` (degradación explícita ante datos fuente
    imperfectos, sin perder filas de ``RAW_DATA``).
    """
    # dtype str evita que Excel convierta WKT a número científico
    df = pd.read_excel(xlsx, sheet_name="ZONE_POLYGONS", dtype={"GEOMETRY_WKT": str})
    out: Dict[str, object] = {}
    for _, row in df.iterrows():  # Cada fila es una zona con su polígono
        name = str(row["ZONE_NAME"])  # Identificador operativo de la zona
        raw = row["GEOMETRY_WKT"]  # Cadena WKT o NaN
        if not isinstance(raw, str) or not raw.strip():
            continue  # Sin geometría usable
        # Excel trunca celdas largas (~32767); WKT incompleto no parsea de forma fiable
        if len(raw) >= 32700:
            continue  # Tratar como ausencia de polígono; se usará centroide
        try:
            geom = wkt.loads(raw)  # Construir geometría Shapely
        except Exception:
            continue  # WKT inválido: omitir esta zona en el mapa polígono
        out[name] = geom
    return out


def zone_for_lon_lat(
    lon: float, lat: float, polygons: Dict[str, object]
) -> Optional[str]:
    """
    Dado un punto (lon, lat), devuelve el nombre de la primera zona cuyo polígono
    **contiene** ese punto, o None si no cae en ninguno (tests de coherencia).
    """
    p = Point(lon, lat)  # Shapely usa (x, y) = (lon, lat) en WGS84
    for name, geom in polygons.items():  # Orden de iteración define desempate si solapan
        if geom.contains(p):
            return name  # Primera zona que contiene el punto
    return None  # Punto fuera de todas las geometrías cargadas


def load_centroids(xlsx: Path) -> pd.DataFrame:
    """Lee la hoja ZONE_INFO (centroides y metadatos por zona operativa)."""
    return pd.read_excel(xlsx, sheet_name="ZONE_INFO")


def validate_excel_zone_consistency(xlsx: Path) -> Tuple[List[str], Dict[str, Any]]:
    """
    Cruza **RAW_DATA**, **ZONE_INFO** y **ZONE_POLYGONS** (mismo criterio Módulo 1 → Módulo 2).

    Comprueba que los nombres de zona coincidan entre hojas y cuente cuántos WKT son
    parseables. Los **truncados u otros WKT inválidos** en Excel no entran en
    ``load_zone_polygons``; para esas zonas el motor **no** elimina datos del panel:
    la consulta de clima usa **centroides oficiales** ``LATITUDE_CENTER`` /
    ``LONGITUDE_CENTER`` desde **ZONE_INFO** (véase ``lat_lon_for_forecast_query``).
    Eso es la política de respaldo documentada en el notebook de diagnóstico
    («Validación de polígonos»).

    Returns:
        (advertencias, resumen con claves n_rows_raw, n_zones, n_polygons_valid, zone_names)
    """
    raw = pd.read_excel(xlsx, sheet_name="RAW_DATA")  # Panel operativo
    zinfo = pd.read_excel(xlsx, sheet_name="ZONE_INFO")  # Centroides por zona
    zpoly = pd.read_excel(xlsx, sheet_name="ZONE_POLYGONS", dtype={"GEOMETRY_WKT": str})  # Geometrías

    warnings: List[str] = []  # Mensajes humanos para log o consola
    # Conjuntos de nombres para comparar consistencia entre hojas
    zones_raw = set(raw["ZONE"].dropna().astype(str).unique())  # Zonas que aparecen en transacciones
    zones_info = set(zinfo["ZONE"].astype(str))  # Zonas definidas en metadatos
    zones_poly = set(zpoly["ZONE_NAME"].astype(str))  # Zonas con fila en polígonos

    if zones_raw != zones_info:
        warnings.append(
            "RAW_DATA vs ZONE_INFO: "
            f"solo en RAW {sorted(zones_raw - zones_info)}; "
            f"solo en INFO {sorted(zones_info - zones_raw)}"
        )
    if zones_info != zones_poly:
        warnings.append(
            "ZONE_INFO vs ZONE_POLYGONS: "
            f"solo en INFO {sorted(zones_info - zones_poly)}; "
            f"solo en POLY {sorted(zones_poly - zones_info)}"
        )

    polys = load_zone_polygons(xlsx)  # Solo entran WKT válidos y no truncados
    # Zonas en INFO pero sin entrada en polys (WKT mal o truncado)
    missing_wkt = zones_info - set(polys.keys())
    if missing_wkt:
        warnings.append(
            "Zonas sin WKT válido en Excel (truncado u otro error) — M2 usa centroides ZONE_INFO: "
            + ", ".join(sorted(missing_wkt))
        )

    summary: Dict[str, Any] = {
        "n_rows_raw": int(len(raw)),  # Tamaño del panel
        "n_zones": len(zones_info),  # Zonas en catálogo
        "n_polygons_valid": len(polys),  # Polígonos parseables
        "zone_names": sorted(zones_info),  # Lista ordenada para reproducibilidad
    }
    return warnings, summary


def lat_lon_for_forecast_query(
    zone_name: str,
    zone_info_row: pd.Series,
    polygons: Dict[str, object],
) -> Tuple[float, float, str]:
    """
    Coordenadas (lat, lon) para llamar a la API de clima, alineadas al enunciado 2a:

    - Si existe polígono WKT válido para la zona, se usa ``representative_point()``
      de Shapely (punto garantizado **dentro** del polígono) y se comprueba con
      ``zone_for_lon_lat`` que la coordenada cae en la zona operativa correcta.
    - Si no hay WKT (truncado en Excel, etc.), se usa ``LATITUDE_CENTER`` /
      ``LONGITUDE_CENTER`` de ``ZONE_INFO`` como respaldo.

    Returns:
        (latitude, longitude, fuente) con fuente en ``"wkt_polygon"`` o ``"centroid_fallback"``.
    """
    geom = polygons.get(zone_name)  # None si la zona no tiene polígono cargado
    if geom is not None:
        # Punto robusto dentro del polígono (no siempre el centroide matemático)
        rp = geom.representative_point()
        lon, lat = float(rp.x), float(rp.y)  # Shapely: x=lon, y=lat
        mapped = zone_for_lon_lat(lon, lat, polygons)  # Verificar que el punto cae en la zona esperada
        if mapped == zone_name:
            return lat, lon, "wkt_polygon"  # Coherencia: el punto representativo pertenece a esta zona
    # Respaldo: coordenadas tabuladas en ZONE_INFO (siempre disponibles por zona)
    lat = float(zone_info_row["LATITUDE_CENTER"])
    lon = float(zone_info_row["LONGITUDE_CENTER"])
    return lat, lon, "centroid_fallback"


def default_data_path() -> Path:
    """Ruta por defecto al Excel del caso (carpeta ``data/`` en la raíz del repo)."""
    return project_root() / "data" / "rappi_delivery_case_data.xlsx"
