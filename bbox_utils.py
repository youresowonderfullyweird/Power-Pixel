"""
bbox_utils.py

Turns a center (lat, lon) into a lat/lon bounding box covering a given
side length in kilometers (default 0.5 x 0.5 km, matching the request).

Uses a simple equirectangular approximation, which is accurate to well
under a meter of error at this scale (hundreds of meters) — no need for a
full geodesic library here.
"""

import math
from dataclasses import dataclass


EARTH_RADIUS_KM = 6371.0088


@dataclass
class BBox:
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float

    def as_dict(self) -> dict:
        return {
            "minLat": self.min_lat,
            "minLon": self.min_lon,
            "maxLat": self.max_lat,
            "maxLon": self.max_lon,
        }


def compute_bbox(center_lat: float, center_lon: float, side_km: float = 0.5) -> BBox:
    """
    Compute a square bounding box `side_km` wide, centered on (center_lat, center_lon).
    """
    half_km = side_km / 2.0

    # 1 degree of latitude is ~111.32 km everywhere.
    dlat = half_km / 111.32

    # 1 degree of longitude shrinks with cos(latitude).
    dlon = half_km / (111.32 * math.cos(math.radians(center_lat)))

    return BBox(
        min_lat=center_lat - dlat,
        max_lat=center_lat + dlat,
        min_lon=center_lon - dlon,
        max_lon=center_lon + dlon,
    )


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Compute a lat/lon bounding box around a center point.")
    ap.add_argument("lat", type=float)
    ap.add_argument("lon", type=float)
    ap.add_argument("--side-km", type=float, default=0.5)
    args = ap.parse_args()

    bbox = compute_bbox(args.lat, args.lon, args.side_km)
    print(json.dumps(bbox.as_dict(), indent=2))
