"""
main.py

End-to-end pipeline, usable either as a CLI or imported by gui.py:

  drone video / SRT / GPX / manual lat-lon
      -> extract a center coordinate            (location_extractor.py)
      -> compute a 0.5x0.5 km bounding box       (bbox_utils.py)
      -> drive Blender + Blosm headlessly        (blosm_headless_import.py)
      -> exported .glb / .ply / .blend

CLI example usage:

    python main.py \
        --srt DJI_0001.SRT \
        --side-km 0.5 \
        --arcgis-token YOUR_ARCGIS_TOKEN \
        --blender-exe /usr/bin/blender \
        --out model

    python main.py \
        --manual-latlon 12.9716 77.5946 \
        --arcgis-token YOUR_ARCGIS_TOKEN \
        --blender-exe /usr/bin/blender \
        --out model

For a GUI, run gui.py instead — it calls run_pipeline() below directly.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from location_extractor import get_center_point
from bbox_utils import compute_bbox

HERE = Path(__file__).parent


def run_pipeline(
    video: Optional[str] = None,
    srt: Optional[str] = None,
    gpx: Optional[str] = None,
    manual_latlon: Optional[Tuple[float, float]] = None,
    side_km: float = 1.5,
    arcgis_token: str = "",
    blender_exe: str = "blender",
    out_base: str = "model",
    formats: Optional[List[str]] = None,
    import_buildings: bool = True,
    import_terrain: bool = True,
    import_satellite: bool = True,
    keep_config: bool = False,
    log: Callable[[str], None] = print,
) -> dict:
    """
    Runs the full pipeline and returns a dict with the resolved center point,
    bbox, and the list of output file paths that were requested.

    `log` is called with each progress line — pass a GUI-friendly callback
    (e.g. one that appends to a text widget) instead of the default print().
    """
    formats = formats or ["glb", "ply", "blend"]

    # 1. Resolve center coordinate purely from metadata (or manual override) — never from video pixels.
    fix = get_center_point(
        video_path=video,
        srt_path=srt,
        gpx_path=gpx,
        manual_latlon=manual_latlon,
    )
    log(f"Center point: lat={fix.lat:.6f}, lon={fix.lon:.6f} (source: {fix.source})")

    # 2. Compute the bounding box for the requested area.
    bbox = compute_bbox(fix.lat, fix.lon, side_km=side_km)
    log(f"Bounding box ({side_km} km square): {bbox.as_dict()}")

    # 3. Write a config file for the Blender-side script to consume.
    out_base_resolved = str(Path(out_base).with_suffix("").resolve())

    config = {
        "bbox": bbox.as_dict(),
        "arcgis_access_token": arcgis_token,
        "import_buildings": import_buildings,
        "import_terrain": import_terrain,
        "import_satellite_overlay": import_satellite,
        "export_base_path": out_base_resolved,
        "export_formats": formats,
    }

    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(config, tmp, indent=2)
    tmp.close()
    log(f"Wrote Blender config to {tmp.name}")

    # 4. Invoke Blender headlessly to run the Blosm import + export.
    blosm_script = str(HERE / "blosm_headless_import.py")
    cmd = [blender_exe, "--background", "--python", blosm_script, "--", tmp.name]
    log(f"Running: {' '.join(cmd)}")

    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
    )
    for line in process.stdout:
        log(line.rstrip())
    returncode = process.wait()

    if not keep_config:
        Path(tmp.name).unlink(missing_ok=True)

    if returncode != 0:
        raise RuntimeError(f"Blender exited with code {returncode} — see the log above.")

    output_files = [f"{out_base_resolved}.{fmt}" for fmt in formats]
    log(f"Done. Files written: {output_files}")

    return {
        "center": {"lat": fix.lat, "lon": fix.lon, "source": fix.source},
        "bbox": bbox.as_dict(),
        "output_files": output_files,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Build a location-based 3D model via Blosm from drone footage metadata.")

    loc = ap.add_argument_group("location source (pick one)")
    loc.add_argument("--video", help="Drone video file (used for embedded EXIF GPS, needs exiftool)")
    loc.add_argument("--srt", help="DJI/Autel .SRT telemetry sidecar file")
    loc.add_argument("--gpx", help="GPX flight log")
    loc.add_argument("--manual-latlon", nargs=2, type=float, metavar=("LAT", "LON"))

    ap.add_argument("--side-km", type=float, default=1.5, help="Square area side length in km (default 1.5)")
    ap.add_argument("--arcgis-token", required=True, help="ArcGIS Location Platform access token")
    ap.add_argument("--blender-exe", default="blender", help="Path to the Blender executable")
    ap.add_argument("--out", default="model", help="Output base path, no extension (e.g. 'model' -> model.glb/.ply/.blend)")
    ap.add_argument("--formats", default="glb,ply,blend",
                     help="Comma-separated export formats to write: glb, ply, blend (default: all three)")
    ap.add_argument("--no-terrain", action="store_true")
    ap.add_argument("--no-buildings", action="store_true")
    ap.add_argument("--no-satellite", action="store_true")
    ap.add_argument("--keep-config", action="store_true", help="Don't delete the temp config JSON (for debugging)")

    return ap


def main():
    args = build_arg_parser().parse_args()
    try:
        run_pipeline(
            video=args.video,
            srt=args.srt,
            gpx=args.gpx,
            manual_latlon=tuple(args.manual_latlon) if args.manual_latlon else None,
            side_km=args.side_km,
            arcgis_token=args.arcgis_token,
            blender_exe=args.blender_exe,
            out_base=args.out,
            formats=[f.strip().lower() for f in args.formats.split(",") if f.strip()],
            import_buildings=not args.no_buildings,
            import_terrain=not args.no_terrain,
            import_satellite=not args.no_satellite,
            keep_config=args.keep_config,
        )
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
