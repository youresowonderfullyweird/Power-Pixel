# Drone-Location 3D Model Builder (Blosm + ArcGIS)

Builds a 3D model of a 0.5 x 0.5 km area (configurable) using **only the
location metadata** from a drone video (or a manually entered coordinate) —
not the video's visual content. It uses that coordinate to drive the
open-source **Blosm** Blender addon, which pulls OpenStreetMap buildings,
terrain, and ArcGIS satellite imagery for the area and assembles them into a
3D scene.

**What this is:** a map-data import automated by location.
**What this is not:** photogrammetry / structure-from-motion reconstruction
of what the drone actually filmed. If you need a model derived from the
video frames themselves, you'd want a separate SfM pipeline (Meshroom,
COLMAP, WebODM, RealityCapture, etc.) instead of or alongside this.

## How it works

```
video / .SRT / .GPX / manual lat,lon
        │
        ▼
location_extractor.py   -> center (lat, lon)
        │
        ▼
bbox_utils.py            -> 0.5x0.5 km bounding box
        │
        ▼
main.py                  -> writes a JSON config, launches Blender headlessly
        │
        ▼
blosm_headless_import.py -> runs INSIDE Blender: configures Blosm with the
                             bbox + ArcGIS token, imports buildings/terrain/
                             satellite overlay, exports the model
        │
        ▼
model.glb / .fbx / .obj
```

## GUI

If you'd rather not use the command line, run:

```bash
python gui.py
```

This opens a desktop window (Tkinter — ships with Python, nothing extra to
install) where you can:

- Choose **"Use drone video / SRT metadata"** and browse for your drone
  video and/or its `.SRT` telemetry sidecar (a GPX flight log also works;
  the video itself is optional — it's only used as an EXIF fallback if no
  `.SRT`/`.GPX` is given), **or**
- Choose **"Enter latitude / longitude manually"** and type coordinates
  directly — the "decoy" path, no video needed at all
- Set the area size, paste your ArcGIS token, toggle buildings/terrain/
  satellite, pick your Blender executable, choose an output base path, and
  check off which export formats you want (`.glb` / `.ply` / `.blend`)
- Click **Build 3D Model** and watch Blender's output stream into the log
  panel live

The GUI runs the exact same `run_pipeline()` function the CLI uses — it's a
thin front end, not a separate implementation, so anything that works from
the command line works here too. It runs the Blender subprocess in a
background thread so the window doesn't freeze while the import/export runs.

## Setup

1. **Install Blender** (3.6 or newer recommended): https://www.blender.org/download/
2. **Install the Blosm addon** in Blender: Edit > Preferences > Add-ons > Install,
   pick the Blosm zip from https://github.com/vvoovv/blosm, then enable it.
3. **Get an ArcGIS access token** (free tier available):
   https://location.arcgis.com/sign-up/ — sign up, generate an API key, and
   keep it handy (do not commit it to source control).
4. (Optional) Install `exiftool` if you want GPS read directly from the video
   file rather than a `.SRT`/`.GPX` sidecar: https://exiftool.org/
5. No pip packages are required — see `requirements.txt`.

## Usage

By default the pipeline writes **all three formats** — `.glb`, `.ply`, and
`.blend` — from a single `--out` base name (no extension needed):

From a DJI `.SRT` telemetry sidecar file:

```bash
python main.py \
  --srt DJI_0001.SRT \
  --side-km 0.5 \
  --arcgis-token YOUR_ARCGIS_TOKEN \
  --blender-exe /path/to/blender \
  --out model
```

This produces `model.glb`, `model.ply`, and `model.blend` next to wherever
`--out` points.

From a manual coordinate (the "decoy" path — no video needed at all):

```bash
python main.py \
  --manual-latlon 12.9716 77.5946 \
  --side-km 0.5 \
  --arcgis-token YOUR_ARCGIS_TOKEN \
  --blender-exe /path/to/blender \
  --out model
```

From a GPX flight log:

```bash
python main.py --gpx flight_log.gpx --arcgis-token YOUR_TOKEN --out model
```

To write only some formats, use `--formats`:

```bash
python main.py --manual-latlon 12.9716 77.5946 --arcgis-token YOUR_TOKEN --out model --formats glb,blend
```

### What's in each format

| Format | Contains | Use it for |
|---|---|---|
| `.glb` | Geometry + materials + textures, single file | Viewing in web viewers, game engines, quick sharing |
| `.ply` | Geometry only (no materials, no satellite texture, no object hierarchy) | Point-cloud/mesh-processing tools, CAD, measurement |
| `.blend` | The full Blender scene exactly as built (materials, hierarchy, satellite overlay, terrain) | Re-opening in Blender to keep editing |

## Important: verify the Blosm property names for your version

Blosm is designed to be driven from its UI panel; its internal Python
property names are **not** a stable, documented public API and have changed
across releases. `blosm_headless_import.py` sets properties defensively
(only if the attribute exists) and **prints a full dump** of
`scene.blosm` and the addon preferences the first time you run it.

If an import step silently produces nothing:

1. Run once and read the printed property list in the terminal.
2. Open Blender normally, enable Blosm, open its panel, and match what
   the panel's fields are called against `dir(bpy.context.scene.blosm)`
   in Blender's Python console.
3. Update the `NAME CANDIDATES` lists near the top of
   `blosm_headless_import.py` to match.

This is the one part of the pipeline that depends on exactly which Blosm
version you have installed, so treat the script as a strong starting point
rather than a guaranteed drop-in.

## Files

| File | Purpose |
|---|---|
| `location_extractor.py` | Parses `.SRT`, `.GPX`, or video EXIF for a GPS center point, or accepts a manual override |
| `bbox_utils.py` | Converts a center point + side length into a lat/lon bounding box |
| `main.py` | Core `run_pipeline()` function + CLI entry point |
| `gui.py` | Tkinter desktop GUI — calls `run_pipeline()` directly |
| `blosm_headless_import.py` | Runs inside Blender to configure and run Blosm, then exports the model |
| `config_example.json` | Example of the config JSON passed between `main.py` and the Blender script |

## Notes & caveats

- **Data completeness** depends on OpenStreetMap coverage for your area —
  building heights/footprints may be sparse in less-mapped regions.
- **ArcGIS usage limits**: the free tier has request/credit caps. Check
  ArcGIS Location Platform's current terms if you'll run this at volume or
  in a shipped product.
- **Terrain resolution** from Blosm is typically ~30m (SRTM-based), fine for
  a 500m-scale overview but not survey-grade.
- Keep your ArcGIS token out of source control — pass it via `--arcgis-token`
  or an environment variable you read into the CLI, not hardcoded.
