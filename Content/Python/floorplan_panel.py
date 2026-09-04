"""Bridge between the C++ Floor Plan Import panel and the Python pipeline.

The panel calls run_from_json with the widget values; everything this module
logs through unreal.log/log_warning/log_error is captured by
ExecPythonCommandEx and mirrored into the panel's own log view.

Keep this module thin and stable: the panel imports it once per editor
session, whereas the detector and router are reloaded on every run so on-disk
edits take effect without restarting.
"""

from __future__ import annotations

import importlib
import json
import traceback

import unreal


def _reload_pipeline():
    """Re-read the detector and router from disk.

    Order matters: the router does `from floorplan_detector import
    detect_walls_from_path`, so the detector has to be reloaded first for the
    router to pick up the new function object.
    """
    import floorplan_detector
    import unreal_floorplan_router as router

    importlib.reload(floorplan_detector)
    importlib.reload(router)
    return router


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


def add_wall() -> int:
    """Editor Utility Widget / Python console entry point for Add Wall."""
    try:
        router = _reload_pipeline()
        return 1 if router.add_wall() else 0
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
        unreal.log_error(f"Export corrected walls failed: {exc}")
        for line in traceback.format_exc().splitlines():
            unreal.log_error(line)
        return ""
