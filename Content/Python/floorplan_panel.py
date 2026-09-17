"""Bridge between the C++ Floor Plan Import panel and the Python pipeline.

The panel calls run_from_json with the widget values; everything this module
logs through unreal.log/log_warning/log_error is captured by
ExecPythonCommandEx and mirrored into the panel's own log view.

Keep this module thin and stable: the panel imports it once per editor
session, whereas the detector and router are reloaded on every run so on-disk
edits take effect without restarting.
"""

from __future__ import annotations

import base64
import importlib
import json
import traceback

import unreal


def _reload_pipeline():
    """Re-read the detector, correction helpers and router from disk.

    Order matters: the router does `from floorplan_detector import
    detect_walls_from_path` and `import floorplan_corrections`, so those have
    to be reloaded first for the router to pick up the new objects.
    """
    import floorplan_corrections
    import floorplan_detector
    import unreal_floorplan_router as router

    importlib.reload(floorplan_detector)
    importlib.reload(floorplan_corrections)
    importlib.reload(router)
    return router


def _payload(value) -> str:
    """JSON -> base64 so the panel gets it back intact through Python's repr()."""
    return base64.b64encode(json.dumps(value).encode("utf-8")).decode("ascii")


def _report(prefix: str, exc: Exception) -> None:
    unreal.log_error(f"{prefix}: {exc}")
    for line in traceback.format_exc().splitlines():
        unreal.log_error(line)


def run_from_json(payload: str) -> int:
    """Entry point for the panel.

    Returns the generated wall count, 0 when nothing was detected, or -1 on
    failure. The panel turns that number into its status message.
    """
    try:
        options = json.loads(payload)
    except ValueError as exc:
        unreal.log_error(f"Panel sent options that are not valid JSON: {exc}")
        return -1

    try:
        router = _reload_pipeline()
    except Exception as exc:
        unreal.log_error(f"Could not load the detection pipeline: {exc}")
        for line in traceback.format_exc().splitlines():
            unreal.log_error(line)
        return -1

    try:
        return int(router.import_floor_plan_with_options(options))
    except Exception as exc:
        unreal.log_error(f"Import failed: {exc}")
        for line in traceback.format_exc().splitlines():
            unreal.log_error(line)
        return -1


def add_wall(
    length_cm: float = 200.0,
    thickness_cm: float = 15.0,
    height_cm: float = 300.0,
    generate_collision: bool = True,
    combined: bool = True,
) -> int:
    """Editor panel / Python console entry point for Add Wall.

    `combined` decides the staging mode only when nothing is staged yet; an
    existing combined actor or set of wall actors always wins.
    """
    try:
        router = _reload_pipeline()
        return 1 if router.add_wall(length_cm, thickness_cm, height_cm, generate_collision, combined) else 0
    except Exception as exc:
        unreal.log_error(f"Add Wall failed: {exc}")
        for line in traceback.format_exc().splitlines():
            unreal.log_error(line)
        return -1


def export_corrected_walls(output_path: str = "") -> str:
    """Editor Utility Widget / Python console entry point for JSON export."""
    try:
        router = _reload_pipeline()
        return str(router.export_corrected_walls(output_path))
    except Exception as exc:
        _report("Export corrected walls failed", exc)
        return ""


# --- Wall correction UI ------------------------------------------------------
# These back both the native panel's "Wall correction" section and the optional
# EUW_WallCorrection widget described in Docs/EditableWallWorkflow.md.

def list_walls_payload() -> str:
    """Base64 JSON list of live walls: id, label, origin, index, summary, geometry."""
    try:
        router = _reload_pipeline()
        return _payload(router.list_walls())
    except Exception as exc:
        _report("Listing walls failed", exc)
        return ""


def list_walls() -> list:
    """Plain list for Blueprint / console callers."""
    try:
        return _reload_pipeline().list_walls()
    except Exception as exc:
        _report("Listing walls failed", exc)
        return []


def select_wall(wall_id: str) -> int:
    """Select and frame one wall. Accepts the id from list_walls or an actor label."""
    try:
        return 1 if _reload_pipeline().select_wall(wall_id) else 0
    except Exception as exc:
        _report("Select wall failed", exc)
        return -1


def remove_wall(wall_id: str) -> int:
    """Delete one wall as a user correction."""
    try:
        return 1 if _reload_pipeline().remove_wall(wall_id) else 0
    except Exception as exc:
        _report("Remove wall failed", exc)
        return -1


def add_wall_at(
    x1: float, y1: float, x2: float, y2: float,
    thickness_cm: float = 15.0,
    height_cm: float = 300.0,
    generate_collision: bool = True,
    combined: bool = True,
) -> str:
    """Add a wall between two world points drawn in the correction window.
    Returns the new wall id, or "" when nothing was added."""
    try:
        router = _reload_pipeline()
        wall_id = router.add_wall_at((x1, y1), (x2, y2), thickness_cm, height_cm, generate_collision, combined)
        return wall_id or ""
    except Exception as exc:
        _report("Add drawn wall failed", exc)
        return ""


def import_floorplan_texture_payload(image_path: str) -> str:
    """Import the plan image as a Texture2D. Base64 JSON {asset_path, width, height}
    or "" for non-image sources / failure."""
    try:
        router = _reload_pipeline()
        info = router.import_floorplan_texture(image_path)
        return _payload(info) if info else ""
    except Exception as exc:
        _report("Importing the floor plan image failed", exc)
        return ""


def finalize_walls(output_path: str = "") -> str:
    """Apply collision, export walls_corrected.json, and return a base64 JSON
    summary {final, detected, removed, added, adjusted, corrections, path}.
    Empty string on failure."""
    try:
        router = _reload_pipeline()
        return _payload(router.finalize_walls(output_path))
    except Exception as exc:
        _report("Finalize failed", exc)
        return ""


def open_correction_ui() -> int:
    """Open EUW_WallCorrection if it exists. 0 means 'use the native panel'."""
    try:
        return 1 if _reload_pipeline().open_correction_ui() else 0
    except Exception as exc:
        _report("Opening the correction UI failed", exc)
        return -1
