"""
Procesamiento geográfico: WKT → polígonos y asignación punto→zona.

GeoPandas es opcional (entorno mínimo: solo Shapely + pandas, como en el caso).
"""

from __future__ import annotations  # Tipos como Any sin comillas

from pathlib import Path  # Ruta al Excel del caso
from typing import Any, Dict, List, Optional, Tuple  # Tipos de listas y diccionarios de salida

# GeoPandas acelera algunos flujos; si falla la importación, el resto del módulo sigue vivo
try:
    import geopandas as gpd  # type: ignore
except Exception:  # pragma: no cover
    gpd = None  # type: ignore  # Marcador: funciones que dependen de gpd devolverán None

# Polígonos por zona y point-in-polygon reutilizan la misma lógica que el motor principal
from zones import load_zone_polygons, zone_for_lon_lat


def load_zones_gdf(xlsx: Path) -> Optional[Any]:
    """Si GeoPandas está instalado, devuelve GeoDataFrame EPSG:4326; si no, None."""
    # Sin geopandas no hay GeoDataFrame que construir
    if gpd is None:
        return None
    # Misma fuente WKT que el resto del pipeline
    poly = load_zone_polygons(xlsx)
    rows = []
    # Cada fila: nombre de zona + geometría Shapely
    for name, geom in poly.items():
        rows.append({"ZONE_NAME": name, "geometry": geom})
    # CRS WGS84 para coincidir con lon/lat del forecast
    return gpd.GeoDataFrame(rows, crs="EPSG:4326")


def assign_point_to_zone(lon: float, lat: float, xlsx: Path) -> Optional[str]:
    """Mapea coordenadas del forecast (lon, lat) a zona operacional (WKT)."""
    poly = load_zone_polygons(xlsx)  # Carga fresca desde Excel
    return zone_for_lon_lat(lon, lat, poly)  # Primera zona que contiene el punto


def aggregate_points_to_zones_max_precip(
    samples: List[Tuple[float, float, float]],
    xlsx: Path,
) -> Dict[str, float]:
    """
    samples: lista de (lon, lat, precip_mm_hr).
    Devuelve precip máxima por zona entre puntos que caen en cada polígono.
    """
    out: Dict[str, float] = {}  # Acumulador: zona → máximo mm/h visto
    poly = load_zone_polygons(xlsx)
    for lon, lat, p in samples:  # Cada muestra es un punto con su intensidad
        z = zone_for_lon_lat(lon, lat, poly)  # None si el punto no cae en ninguna zona
        if z is None:
            continue  # Ignorar puntos fuera de polígonos conocidos
        # Conservar el máximo por zona si ya había un valor previo
        out[z] = max(out.get(z, 0.0), float(p))
    return out
