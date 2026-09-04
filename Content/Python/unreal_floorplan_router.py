"""Detect floor-plan walls and create independently editable wall actors.

No Blender, GLB, or FBX. Detection produces local centreline data in Unreal
centimetres. Each result becomes one BP_WallSegment (or the native
WallSegmentActor fallback), so ordinary viewport transforms remain available
before exporting the corrected wall list.
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import unreal

from floorplan_detector import detect_walls_from_path

# --- Scale (Unreal centimetres out) ------------------------------------------
# Image / rasterized PDF: pixels in a known 1-foot measure on the drawing.
IMAGE_PIXELS_PER_FOOT = 50.0

# Vector PDF: 72 points = 1 inch = 2.54 cm.
PDF_POINTS_TO_UNREAL_CM = 2.54 / 72.0

# DXF/DWG drawing units → Unreal cm. Inches=2.54, millimetres=0.1, metres=100, already-cm=1.
DXF_UNITS_TO_UNREAL_CM = 2.54

# --- Detection ---------------------------------------------------------------
PDF_PAGE_INDEX = 0
RASTER_PDF_DPI = 300.0
# Empty = auto (case-insensitive names containing "wall", else all layers).
# Do not hardcode "Walls"; this drawing used lowercase "wall".
CAD_LAYER_FILTER = ""
ODA_CONVERTER_PATH = ""
DEFAULT_WALL_THICKNESS_CM = 15.0
WALL_HEIGHT_CM = 300.0

# --- Editable staging --------------------------------------------------------
WALL_BLUEPRINT_PATH = "/Game/FloorPlan/Blueprints/BP_WallSegment"
WALL_FOLDER = "FloorPlan_Walls"
WALL_TAG = "FloorPlanEditableWall"
DEFAULT_NEW_WALL_LENGTH_CM = 200.0


def _log(message: str) -> None:
    unreal.log(message)


def _actor_subsystem():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def _is_commandlet() -> bool:
    """Selection APIs are unsafe without an interactive level editor in UE 5.7."""
    return "unrealeditor-cmd" in sys.executable.lower()


def _has_wall_tag(actor) -> bool:
    try:
        return any(str(tag) == WALL_TAG for tag in actor.get_editor_property("tags"))
    except Exception:
        return False


def _mark_wall_actor(actor, index: Optional[int] = None) -> None:
    tags = list(actor.get_editor_property("tags"))
    if not any(str(tag) == WALL_TAG for tag in tags):
        tags.append(unreal.Name(WALL_TAG))
        actor.set_editor_property("tags", tags)
    actor.set_folder_path(unreal.Name(WALL_FOLDER))
    if index is not None:
        actor.set_actor_label(f"Wall_{index:03d}")


def get_editable_wall_actors() -> List[Any]:
    """Return this workflow's live wall actors in stable label order."""
    native_type = getattr(unreal, "WallSegmentActor", None)
    actors = []
    for actor in _actor_subsystem().get_all_level_actors():
        if _has_wall_tag(actor) or (native_type and isinstance(actor, native_type)):
            actors.append(actor)
    return sorted(actors, key=lambda item: item.get_actor_label())


def clear_editable_walls() -> int:
    """Delete only actors owned by the editable-wall staging workflow."""
    subsystem = _actor_subsystem()
    actors = get_editable_wall_actors()
    for actor in actors:
        subsystem.destroy_actor(actor)
    return len(actors)


def _load_wall_blueprint():
    """Load the documented thin BP child when the user has created it."""
    if not unreal.EditorAssetLibrary.does_asset_exist(WALL_BLUEPRINT_PATH):
        return None
    return unreal.EditorAssetLibrary.load_asset(WALL_BLUEPRINT_PATH)


def _spawn_wall_actor(location: Optional[Any] = None):
    """Prefer BP_WallSegment; remain usable before the documented BP is made."""
    subsystem = _actor_subsystem()
    location = location or unreal.Vector(0.0, 0.0, 0.0)
    rotation = unreal.Rotator(0.0, 0.0, 0.0)
    blueprint = _load_wall_blueprint()
    if blueprint:
        actor = subsystem.spawn_actor_from_object(blueprint, location, rotation)
    else:
        native_type = getattr(unreal, "WallSegmentActor", None)
        if not native_type:
            raise RuntimeError(
                "WallSegmentActor is unavailable. Build the Floor2Dto3Dplan module and restart Unreal Editor."
            )
        actor = subsystem.spawn_actor_from_class(native_type, location, rotation)
    if not actor:
        raise RuntimeError("Unreal failed to spawn an editable wall actor.")
    return actor


def _set_wall_properties(
    actor,
    start: Sequence[float],
    end: Sequence[float],
    thickness: float,
    height: float,
    generate_collision: bool,
) -> None:
    start_2d = unreal.Vector2D(float(start[0]), float(start[1]))
    end_2d = unreal.Vector2D(float(end[0]), float(end[1]))
    if hasattr(actor, "set_wall"):
        if not actor.set_wall(start_2d, end_2d, float(thickness), float(height), bool(generate_collision)):
            raise RuntimeError(f"{actor.get_name()} rejected invalid wall dimensions.")
        return

    # Supports the pure-Blueprint alternative described in the workflow guide.
    actor.set_editor_property("start", start_2d)
    actor.set_editor_property("end", end_2d)
    actor.set_editor_property("thickness", float(thickness))
    actor.set_editor_property("height", float(height))
    try:
        actor.set_editor_property("generate_collision", bool(generate_collision))
    except Exception:
        pass
    actor.rerun_construction_scripts()


def spawn_detected_walls(
    walls: Sequence[Dict[str, object]],
    wall_height_cm: float = WALL_HEIGHT_CM,
    generate_collision: bool = True,
    clear_existing: bool = True,
) -> List[Any]:
    """Replace the staging set and spawn one selectable actor per wall."""
    if clear_existing:
        removed = clear_editable_walls()
        if removed:
            _log(f"8. Removed {removed} previous editable wall actor(s).")

    if not _load_wall_blueprint():
        unreal.log_warning(
            f"{WALL_BLUEPRINT_PATH} does not exist; using native WallSegmentActor instances. "
            "Create the thin Blueprint child described in Docs/EditableWallWorkflow.md when Blueprint assets are required."
        )

    spawned = []
    try:
        for index, wall in enumerate(walls, start=1):
            actor = _spawn_wall_actor()
            _set_wall_properties(
                actor,
                wall["start"],
                wall["end"],
                float(wall["thickness"]),
                wall_height_cm,
                generate_collision,
            )
            _mark_wall_actor(actor, index)
            spawned.append(actor)
    except Exception:
        for actor in spawned:
            _actor_subsystem().destroy_actor(actor)
        raise

    _log(
        f"9. Spawned {len(spawned)} independently selectable wall actor(s) "
        f"in the '{WALL_FOLDER}' Outliner folder."
    )
    return spawned


def _viewport_floor_point():
    """Project the active editor camera forward onto Z=0; origin is fallback."""
    try:
        level_editor = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        result = level_editor.get_level_viewport_camera_info()
        values = list(result) if isinstance(result, (tuple, list)) else []
        if values and isinstance(values[0], bool):
            if not values[0]:
                return unreal.Vector(0.0, 0.0, 0.0)
            values = values[1:]
        if len(values) < 2:
            return unreal.Vector(0.0, 0.0, 0.0)
        camera_location, camera_rotation = values[0], values[1]
        forward = camera_rotation.rotate_vector(unreal.Vector(1.0, 0.0, 0.0))
        if abs(forward.z) > 1.0e-4:
            distance = -camera_location.z / forward.z
            if distance > 0.0:
                return camera_location + forward * distance
        point = camera_location + forward * 1000.0
        point.z = 0.0
        return point
    except Exception as exc:
        unreal.log_warning(f"Could not read the viewport camera; adding at world origin: {exc}")
        return unreal.Vector(0.0, 0.0, 0.0)


def add_wall(
    length_cm: float = DEFAULT_NEW_WALL_LENGTH_CM,
    thickness_cm: float = DEFAULT_WALL_THICKNESS_CM,
    height_cm: float = WALL_HEIGHT_CM,
    generate_collision: bool = True,
):
    """Spawn and select a short new wall for correction with native gizmos."""
    length_cm = max(float(length_cm), 1.0)
    actor = _spawn_wall_actor(_viewport_floor_point())
    _set_wall_properties(
        actor,
        (-length_cm * 0.5, 0.0),
        (length_cm * 0.5, 0.0),
        thickness_cm,
        height_cm,
        generate_collision,
    )
    _mark_wall_actor(actor)
    actor.set_actor_label(f"Wall_{len(get_editable_wall_actors()):03d}")
    if not _is_commandlet():
        _actor_subsystem().set_selected_level_actors([actor])
    _log(f"Added {actor.get_actor_label()} at the viewport focus plane. Use native grid/rotation snapping to place it.")
    return actor


def _world_wall_record(actor) -> Dict[str, object]:
    start = actor.get_editor_property("start")
    end = actor.get_editor_property("end")
    thickness = float(actor.get_editor_property("thickness"))
    transform = actor.get_actor_transform()

    start_local = unreal.Vector(float(start.x), float(start.y), 0.0)
    end_local = unreal.Vector(float(end.x), float(end.y), 0.0)
    world_start = transform.transform_location(start_local)
    world_end = transform.transform_location(end_local)

    dx = float(end.x - start.x)
    dy = float(end.y - start.y)
    length = math.hypot(dx, dy)
    if length <= 1.0e-6:
        raise ValueError(f"{actor.get_actor_label()} has zero length.")
    perpendicular = unreal.Vector(-dy / length, dx / length, 0.0)
    midpoint = (start_local + end_local) * 0.5
    side_a = transform.transform_location(midpoint - perpendicular * (thickness * 0.5))
    side_b = transform.transform_location(midpoint + perpendicular * (thickness * 0.5))
    world_thickness = (side_b - side_a).length()

    return {
        "start": [round(float(world_start.x), 4), round(float(world_start.y), 4)],
        "end": [round(float(world_end.x), 4), round(float(world_end.y), 4)],
        "thickness": round(float(world_thickness), 4),
    }


def export_corrected_walls(output_path: str = "") -> str:
    """Export all staged actors after applying their current world transforms."""
    actors = get_editable_wall_actors()
    if not actors:
        raise RuntimeError(f"No editable walls were found in '{WALL_FOLDER}'.")

    records = []
    for actor in actors:
        try:
            records.append(_world_wall_record(actor))
        except ValueError as exc:
            unreal.log_warning(str(exc))

    if not records:
        raise RuntimeError("Every editable wall was invalid; nothing was exported.")
    if not output_path:
        output_path = str(Path(unreal.Paths.project_saved_dir()) / "FloorPlan" / "walls.json")
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(records, indent=2), encoding="utf-8")
    _log(f"Exported {len(records)} corrected wall segment(s) to {output}")
    return str(output)


def import_floor_plan_with_options(options: Optional[Dict[str, Any]] = None) -> int:
    """Run the whole pipeline.

    Returns the number of generated wall segments, 0 when nothing was detected,
    and -1 when the run failed before detection could produce a result.
    """
    options = options or {}
    show_dialogs = bool(options.get("show_dialogs", True))

    _log("1. Floor-plan import started (Unreal-native Dynamic Mesh, no Blender).")

    path = str(options.get("file_path", "")).strip()
    if not path:
        if not hasattr(unreal, "FloorPlanImportLibrary"):
            unreal.log_error("FloorPlanImportLibrary is missing. Close the editor, compile C++, then reopen.")
            return -1
        path = unreal.FloorPlanImportLibrary.pick_floor_plan_file()

    if not path:
        _log("Import cancelled: no file selected.")
        return -1

    if not os.path.isfile(path):
        unreal.log_error(f"File not found: {path}")
        return -1

    _log(f"   Selected: {path}")
    walls = detect_walls_from_path(
        path,
        pixels_per_foot=float(options.get("pixels_per_foot", IMAGE_PIXELS_PER_FOOT)),
        pdf_points_to_unreal_cm=float(options.get("pdf_points_to_unreal_cm", PDF_POINTS_TO_UNREAL_CM)),
        dxf_units_to_unreal_cm=float(options.get("dxf_units_to_unreal_cm", DXF_UNITS_TO_UNREAL_CM)),
        pdf_page_index=int(options.get("pdf_page_index", PDF_PAGE_INDEX)),
        raster_dpi=float(options.get("raster_dpi", RASTER_PDF_DPI)),
        cad_layer_filter=str(options.get("cad_layer_filter", CAD_LAYER_FILTER)),
        oda_converter_path=str(options.get("oda_converter_path", ODA_CONVERTER_PATH)),
        default_thickness_cm=float(options.get("default_thickness_cm", DEFAULT_WALL_THICKNESS_CM)),
        log=_log,
    )

    if not walls:
        unreal.log_error("No walls detected. Mesh was not spawned. See numbered log lines above.")
        if show_dialogs:
            unreal.EditorDialog.show_message(
                unreal.Text("Floor Plan Import"),
                unreal.Text("No walls were detected. Check the log for layer counts and routing errors."),
                unreal.AppMsgType.OK,
            )
        return 0

    if not hasattr(unreal, "WallSegmentActor"):
        unreal.log_error(
            "Native WallSegmentActor is missing. Compile Floor2Dto3Dplan and restart Unreal Editor."
        )
        return -1

    wall_height = float(options.get("wall_height_cm", WALL_HEIGHT_CM))
    generate_collision = bool(options.get("generate_collision", True))
    try:
        actors = spawn_detected_walls(
            walls,
            wall_height_cm=wall_height,
            generate_collision=generate_collision,
            clear_existing=bool(options.get("clear_existing_walls", True)),
        )
    except Exception as exc:
        unreal.log_error(f"Could not create editable wall actors: {exc}")
        return -1

    _log(
        "10. Editable staging is ready. Select/Delete/duplicate walls or use viewport "
        "move, rotate, and scale with Unreal's grid snapping."
    )
    return len(actors)


def import_floor_plan(file_path: str = "") -> int:
    """Menu-entry entry point: native file picker plus module defaults."""
    return import_floor_plan_with_options({"file_path": file_path})
