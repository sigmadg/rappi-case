"""
Procesamiento geográfico: WKT → polígonos y asignación punto→zona.

GeoPandas es opcional (entorno mínimo: solo Shapely + pandas, como en el caso).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import geopandas as gpd  # type: ignore
except Exception:  # pragma: no cover
    gpd = None  # type: ignore

from zones import load_zone_polygons, zone_for_lon_lat


def load_zones_gdf(xlsx: Path) -> Optional[Any]:
    """Si GeoPandas está instalado, devuelve GeoDataFrame EPSG:4326; si no, None."""
    if gpd is None:
        return None
    poly = load_zone_polygons(xlsx)
    rows = []
    for name, geom in poly.items():
        rows.append({"ZONE_NAME": name, "geometry": geom})
    return gpd.GeoDataFrame(rows, crs="EPSG:4326")


def assign_point_to_zone(lon: float, lat: float, xlsx: Path) -> Optional[str]:
    """Mapea coordenadas del forecast (lon, lat) a zona operacional (WKT)."""
    poly = load_zone_polygons(xlsx)
    return zone_for_lon_lat(lon, lat, poly)


def aggregate_points_to_zones_max_precip(
    samples: List[Tuple[float, float, float]],
    xlsx: Path,
) -> Dict[str, float]:
    """
    samples: lista de (lon, lat, precip_mm_hr).
    Devuelve precip máxima por zona entre puntos que caen en cada polígono.
    """
    out: Dict[str, float] = {}
    poly = load_zone_polygons(xlsx)
    for lon, lat, p in samples:
        z = zone_for_lon_lat(lon, lat, poly)
        if z is None:
            continue
        out[z] = max(out.get(z, 0.0), float(p))
    return out
