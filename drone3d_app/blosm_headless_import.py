"""
blosm_headless_import.py

This script does NOT run standalone — it runs *inside* Blender, invoked like:

    blender --background --python blosm_headless_import.py -- /path/to/config.json

It reads a JSON config (written by main.py) describing the bounding box and
ArcGIS token, drives the Blosm addon to import OSM buildings + terrain +
ArcGIS satellite imagery for that area, and exports the result.

IMPORTANT — read this before running:
Blosm's internal Python property names have changed across releases and are
not part of a stable public API (the addon is designed to be driven from its
UI panel, not scripted). This script sets properties defensively with
`setattr(..., ...)` only when the attribute exists, and prints a full dump of
`bpy.context.scene.blosm` so you can see exactly what your installed version
exposes. If an import step silently does nothing, run once, read the printed
property dump, and adjust the NAME CANDIDATES lists below to match your
version.
"""

import bpy
import json
import sys
from pathlib import Path


def _get_config():
    argv = sys.argv
    if "--" not in argv:
        raise RuntimeError("Pass the config path after '--', e.g. blender --background --python "
                            "blosm_headless_import.py -- /path/to/config.json")
    config_path = argv[argv.index("--") + 1]
    with open(config_path) as f:
        return json.load(f)


def _ensure_blosm_enabled():
    addon_name = "blosm"
    if addon_name not in bpy.context.preferences.addons:
        try:
            bpy.ops.preferences.addon_enable(module=addon_name)
        except Exception as e:
            raise RuntimeError(
                f"Could not enable the 'blosm' addon. Make sure it is installed "
                f"(Edit > Preferences > Add-ons) under exactly that module name. Original error: {e}"
            )
    return bpy.context.preferences.addons[addon_name]


def _set_first_matching(obj, name_candidates, value, label):
    """Try a list of possible attribute names and set the first one that exists."""
    for name in name_candidates:
        if hasattr(obj, name):
            setattr(obj, name, value)
            print(f"[blosm-import] set {label} -> {name} = {value}")
            return True
    print(f"[blosm-import] WARNING: could not find a property for {label} "
          f"(tried {name_candidates}). Check the property dump below.")
    return False


def _dump_props(obj, label):
    print(f"\n[blosm-import] Available properties on {label}:")
    for attr in sorted(dir(obj)):
        if not attr.startswith("_"):
            print(f"   {attr}")
    print()


def main():
    cfg = _get_config()

    bbox = cfg["bbox"]              # {minLat, minLon, maxLat, maxLon}
    arcgis_token = cfg.get("arcgis_access_token", "")
    import_buildings = cfg.get("import_buildings", True)
    import_terrain = cfg.get("import_terrain", True)
    import_satellite = cfg.get("import_satellite_overlay", True)
    export_base_path = cfg["export_base_path"]     # no extension, e.g. "C:/.../model"
    export_formats = cfg.get("export_formats", ["glb", "ply", "blend"])

    addon = _ensure_blosm_enabled()

    # --- ArcGIS token lives in addon preferences, not scene props ---
    prefs = addon.preferences
    _dump_props(prefs, "addon preferences (blosm)")
    if arcgis_token:
        _set_first_matching(
            prefs,
            ["arcgisAccessToken", "arcgisAccessTokenPro", "arcgisToken", "arcgis_access_token"],
            arcgis_token,
            "ArcGIS access token",
        )

    # --- Bounding box + import toggles live on the scene property group ---
    scene = bpy.context.scene
    if not hasattr(scene, "blosm"):
        raise RuntimeError(
            "scene.blosm not found. The addon may not be enabled correctly, "
            "or this Blosm version stores settings under a different name."
        )
    blosm_props = scene.blosm
    _dump_props(blosm_props, "scene.blosm")

    # Most Blosm versions use minLat/maxLat/minLon/maxLon with a "coordinates as filter" mode.
    _set_first_matching(blosm_props, ["minLat"], bbox["minLat"], "min latitude")
    _set_first_matching(blosm_props, ["maxLat"], bbox["maxLat"], "max latitude")
    _set_first_matching(blosm_props, ["minLon"], bbox["minLon"], "min longitude")
    _set_first_matching(blosm_props, ["maxLon"], bbox["maxLon"], "max longitude")

    _set_first_matching(blosm_props, ["buildings"], import_buildings, "import buildings toggle")
    _set_first_matching(blosm_props, ["water"], True, "import water toggle")
    _set_first_matching(blosm_props, ["forests", "vegetation"], True, "import vegetation toggle")

    if import_terrain:
        _set_first_matching(blosm_props, ["terrain"], True, "import terrain toggle")

    if import_satellite:
        # dataType typically switches between 'osm', 'terrain', 'overlay' imports —
        # you may need to run the import operator multiple times (once per data type)
        # depending on your Blosm version. See README for the manual fallback.
        _set_first_matching(
            blosm_props,
            ["overlayType", "imageOverlayType"],
            "arcgis-satellite",
            "satellite overlay provider",
        )

    # --- Run the import ---
    if hasattr(bpy.ops, "blosm") and hasattr(bpy.ops.blosm, "import_data"):
        print("[blosm-import] Running bpy.ops.blosm.import_data() ...")
        bpy.ops.blosm.import_data()
    else:
        raise RuntimeError(
            "bpy.ops.blosm.import_data not found. Open Blender's Python console with the "
            "addon enabled and run `dir(bpy.ops.blosm)` to find the correct operator name "
            "for your installed version, then update this script."
        )

    # --- Export the result in every requested format ---
    base = Path(export_base_path).expanduser()
    base.parent.mkdir(parents=True, exist_ok=True)

    # Make sure everything imported is selected — several exporters only
    # write the current selection, and background mode starts with nothing selected.
    bpy.ops.object.select_all(action="SELECT")
    mesh_objects = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if mesh_objects:
        bpy.context.view_layer.objects.active = mesh_objects[0]

    written = []

    if "glb" in export_formats:
        path = str(base.with_suffix(".glb"))
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB")
        written.append(path)
        print(f"[blosm-import] Wrote {path}")

    if "ply" in export_formats:
        path = str(base.with_suffix(".ply"))
        # PLY only stores mesh geometry (+ vertex colors if present) — no
        # materials, no separate objects/hierarchy, no satellite texture UVs.
        # Blender 4.x uses wm.ply_export; older versions use export_mesh.ply.
        try:
            if hasattr(bpy.ops.wm, "ply_export"):
                bpy.ops.wm.ply_export(filepath=path, export_selected_objects=True)
            elif hasattr(bpy.ops.export_mesh, "ply"):
                bpy.ops.export_mesh.ply(filepath=path, use_selection=True)
            else:
                raise RuntimeError("No PLY export operator found in this Blender version.")
            written.append(path)
            print(f"[blosm-import] Wrote {path} (geometry only — no materials/textures)")
        except Exception as e:
            print(f"[blosm-import] WARNING: PLY export failed: {e}")

    if "blend" in export_formats:
        path = str(base.with_suffix(".blend"))
        bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
        written.append(path)
        print(f"[blosm-import] Wrote {path} (full scene: materials, hierarchy, satellite texture)")

    if not written:
        raise ValueError(f"No files written — check export_formats: {export_formats}")

    print(f"[blosm-import] Done. Exported: {written}")


if __name__ == "__main__":
    main()
