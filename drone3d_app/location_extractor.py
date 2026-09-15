"""
location_extractor.py

Pulls a single (lat, lon) "center point" out of drone footage metadata so it
can be handed to Blosm. The video's pixel content is never inspected — only
location metadata is used, matching the "video as decoy" workflow.

Supported sources, in order of preference:
    1. A DJI-style .SRT sidecar file (subtitle track with embedded GPS)
    2. A .GPX track file (exported flight log)
    3. Embedded EXIF/QuickTime GPS on the video file itself (via exiftool)
    4. Manual lat/lon passed straight through

Only the standard library plus an optional `exiftool` binary are required.
"""

from __future__ import annotations

import json
import re
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class GPSFix:
    lat: float
    lon: float
    alt: Optional[float] = None
    source: str = "unknown"


# ---------------------------------------------------------------------------
# .SRT (DJI / Autel telemetry subtitle) parsing
# ---------------------------------------------------------------------------

# Covers common DJI SRT patterns, e.g.:
#   [latitude: 12.971600] [longitude: 77.594600]
#   GPS(77.594600, 12.971600, 920.4M)
#   lat: 12.9716, lon: 77.5946
_LATLON_PATTERNS = [
    re.compile(r"latitude\s*:\s*(-?\d+\.\d+).*?longitude\s*:\s*(-?\d+\.\d+)", re.I | re.S),
    re.compile(r"GPS\s*\(\s*(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)", re.I),  # (lon, lat, alt) — DJI order
    re.compile(r"lat\s*:\s*(-?\d+\.\d+).*?lon\s*:\s*(-?\d+\.\d+)", re.I | re.S),
]


def parse_srt(path: Path) -> List[GPSFix]:
    """Extract every GPS fix found in a DJI/Autel-style .SRT telemetry file."""
    text = path.read_text(errors="ignore")
    fixes: List[GPSFix] = []

    for pattern in _LATLON_PATTERNS:
        for match in pattern.finditer(text):
            a, b = float(match.group(1)), float(match.group(2))
            # The "GPS(lon, lat, alt)" pattern is lon-first; everything else is lat-first.
            if "GPS" in pattern.pattern:
                lon, lat = a, b
            else:
                lat, lon = a, b
            fixes.append(GPSFix(lat=lat, lon=lon, source=f"srt:{path.name}"))
        if fixes:
            break  # stop after the first pattern that actually matched

    return fixes


# ---------------------------------------------------------------------------
# .GPX track parsing
# ---------------------------------------------------------------------------

def parse_gpx(path: Path) -> List[GPSFix]:
    """Extract trackpoints from a GPX file (common flight-log export format)."""
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    tree = ET.parse(path)
    root = tree.getroot()

    fixes: List[GPSFix] = []
    for trkpt in root.iter():
        tag = trkpt.tag.split("}")[-1]
        if tag in ("trkpt", "wpt", "rtept"):
            lat = trkpt.attrib.get("lat")
            lon = trkpt.attrib.get("lon")
            if lat and lon:
                ele_el = None
                for child in trkpt:
                    if child.tag.endswith("ele"):
                        ele_el = child
                        break
                alt = float(ele_el.text) if ele_el is not None and ele_el.text else None
                fixes.append(GPSFix(lat=float(lat), lon=float(lon), alt=alt, source=f"gpx:{path.name}"))
    return fixes


# ---------------------------------------------------------------------------
# Embedded video EXIF/QuickTime GPS (requires the `exiftool` CLI on PATH)
# ---------------------------------------------------------------------------

def parse_video_exif(path: Path) -> Optional[GPSFix]:
    """
    Try to read embedded GPS from the video container itself using exiftool.
    Returns None (without raising) if exiftool is missing or no GPS tag exists —
    this is a best-effort fallback, not the primary path for most drone footage.
    """
    try:
        result = subprocess.run(
            ["exiftool", "-j", "-GPSLatitude", "-GPSLongitude", "-GPSAltitude", str(path)],
            capture_output=True,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

    try:
        data = json.loads(result.stdout)[0]
    except (json.JSONDecodeError, IndexError):
        return None

    lat = _dms_or_float(data.get("GPSLatitude"))
    lon = _dms_or_float(data.get("GPSLongitude"))
    if lat is None or lon is None:
        return None

    alt_raw = data.get("GPSAltitude")
    alt = float(re.sub(r"[^\d.\-]", "", str(alt_raw))) if alt_raw else None

    return GPSFix(lat=lat, lon=lon, alt=alt, source=f"exif:{path.name}")


def _dms_or_float(value) -> Optional[float]:
    """exiftool may return '12 deg 58\' 17.76\" N' or a plain decimal — normalize both."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    s = str(value).strip()
    try:
        return float(s)
    except ValueError:
        pass

    m = re.match(r"(\d+)\s*deg\s*(\d+)'\s*([\d.]+)\"?\s*([NSEW])", s)
    if not m:
        return None
    deg, minutes, seconds, hemi = m.groups()
    val = float(deg) + float(minutes) / 60 + float(seconds) / 3600
    if hemi in ("S", "W"):
        val = -val
    return val


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def get_center_point(
    video_path: Optional[str] = None,
    srt_path: Optional[str] = None,
    gpx_path: Optional[str] = None,
    manual_latlon: Optional[Tuple[float, float]] = None,
) -> GPSFix:
    """
    Resolve a single center (lat, lon) using the first available source, in
    priority order: manual override > .SRT > .GPX > embedded video EXIF.
    """
    if manual_latlon is not None:
        lat, lon = manual_latlon
        return GPSFix(lat=lat, lon=lon, source="manual")

    if srt_path:
        fixes = parse_srt(Path(srt_path))
        if fixes:
            return _centroid(fixes)

    if gpx_path:
        fixes = parse_gpx(Path(gpx_path))
        if fixes:
            return _centroid(fixes)

    if video_path:
        fix = parse_video_exif(Path(video_path))
        if fix:
            return fix

    raise ValueError(
        "Could not resolve a location. Provide --manual-latlon, or a valid "
        "--srt / --gpx file, or a video with embedded GPS (needs exiftool)."
    )


def _centroid(fixes: List[GPSFix]) -> GPSFix:
    """Average a list of fixes into one representative center point."""
    lat = sum(f.lat for f in fixes) / len(fixes)
    lon = sum(f.lon for f in fixes) / len(fixes)
    return GPSFix(lat=lat, lon=lon, source=fixes[0].source)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Extract a GPS center point from drone footage metadata.")
    ap.add_argument("--video", help="Path to the drone video file")
    ap.add_argument("--srt", help="Path to a DJI/Autel .SRT telemetry sidecar file")
    ap.add_argument("--gpx", help="Path to a .GPX flight log")
    ap.add_argument("--manual-latlon", nargs=2, type=float, metavar=("LAT", "LON"))
    args = ap.parse_args()

    fix = get_center_point(
        video_path=args.video,
        srt_path=args.srt,
        gpx_path=args.gpx,
        manual_latlon=tuple(args.manual_latlon) if args.manual_latlon else None,
    )
    print(json.dumps(fix.__dict__, indent=2))
