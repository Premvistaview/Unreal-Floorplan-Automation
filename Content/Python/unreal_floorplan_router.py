"""Detect floor-plan walls and stage them in the level for correction.

No Blender, GLB, or FBX. Detection produces centreline data in Unreal
centimetres, which is staged in one of two ways:

  combined   (default) one WallGeneratorActor (or its BP_FloorPlanWalls child)
             whose WallSegments array holds every wall. The correction UI
             edits that array and the actor rebuilds its single Dynamic Mesh.
             Walls can also be edited numerically in the actor's Details.

  individual one WallSegmentActor / BP_WallSegment per wall, so each wall can
             be moved, rotated, and deleted with the ordinary viewport gizmos.

Which mode is in use is derived from the level, so every correction call
(list, select, remove, add, finalize) works without being told.
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import unreal

import floorplan_corrections as corrections
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

# --- Staging -----------------------------------------------------------------
USE_COMBINED_ACTOR = True
WALL_FOLDER = "FloorPlan_Walls"
WALL_TAG = corrections.WALL_TAG
DEFAULT_NEW_WALL_LENGTH_CM = 200.0

# Combined mode: one actor holding every wall.
COMBINED_BLUEPRINT_PATH = "/Game/FloorPlan/Blueprints/BP_FloorPlanWalls"
COMBINED_TAG = "FloorPlanCombinedWalls"
COMBINED_LABEL = "FloorPlan_Walls"

# Individual mode: one actor per wall.
WALL_BLUEPRINT_PATH = "/Game/FloorPlan/Blueprints/BP_WallSegment"

# Source floor-plan images are imported here so the correction window can
# show them behind the detected walls.
TEXTURE_FOLDER = "/Game/FloorPlan/Sources"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}

# --- Correction workflow -----------------------------------------------------
# Raw detection output, written once per run and never touched afterwards.
RAW_WALLS_JSON_NAME = "walls.json"
# What Finalize writes: the staged walls after every removal/addition/move.
CORRECTED_WALLS_JSON_NAME = "walls_corrected.json"
# Optional user-built Editor Utility Widget (see Docs/EditableWallWorkflow.md).
# The native Floor Plan Import panel already hosts the same correction tools,
# so this is only opened when the asset exists.
CORRECTION_WIDGET_PATH = "/Game/FloorPlan/UI/EUW_WallCorrection"

# Final bake: Finalize turns the Dynamic Mesh walls into one Static Mesh asset
# (lightmap UVs, simple collision, optional Nanite) and a Static Mesh Actor.
BAKE_ON_FINALIZE = True
BAKE_MESH_FOLDER = "/Game/FloorPlan/Meshes"
BAKE_BASE_NAME = "FloorPlanWalls"
BAKE_ENABLE_NANITE = False

# Camera placement when "Select in Viewport" frames one wall of the combined actor.
FRAME_DISTANCE_CM = 600.0
FRAME_HEIGHT_CM = 350.0


def _log(message: str) -> None:
    unreal.log(message)


def _actor_subsystem():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def _is_commandlet() -> bool:
    """Selection and camera APIs are unsafe without an interactive level editor in UE 5.7."""
    return "unrealeditor-cmd" in sys.executable.lower()


# =============================================================================
# Shared helpers
# =============================================================================

def _actor_tags(actor) -> List[str]:
    try:
        return [str(tag) for tag in actor.get_editor_property("tags")]
    except Exception:
        return []


def _set_tags(actor, tags: Sequence[str]) -> None:
    actor.set_editor_property("tags", [unreal.Name(tag) for tag in tags])


def _all_level_actors():
    return _actor_subsystem().get_all_level_actors()


def _world_record(transform, start, end, thickness: float, label: str) -> Dict[str, object]:
    """Apply an actor transform to a local centreline; thickness follows scale."""
    start_local = unreal.Vector(float(start.x), float(start.y), 0.0)
    end_local = unreal.Vector(float(end.x), float(end.y), 0.0)
    world_start = transform.transform_location(start_local)
    world_end = transform.transform_location(end_local)

    dx = float(end.x - start.x)
    dy = float(end.y - start.y)
    length = math.hypot(dx, dy)
    if length <= 1.0e-6:
        raise ValueError(f"{label} has zero length.")
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


def _frame_point(target) -> None:
    """Move the active viewport camera to look at a world point from nearby."""
    if _is_commandlet():
        return
    try:
        eye = unreal.Vector(target.x - FRAME_DISTANCE_CM * 0.7, target.y - FRAME_DISTANCE_CM * 0.7,
                            target.z + FRAME_HEIGHT_CM)
        rotation = unreal.MathLibrary.find_look_at_rotation(eye, target)
        unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).set_level_viewport_camera_info(eye, rotation)
    except Exception as exc:
        unreal.log_warning(f"Could not frame the wall in the viewport: {exc}")


def _select(actor) -> None:
    if not _is_commandlet():
        _actor_subsystem().set_selected_level_actors([actor])


def _floorplan_dir() -> Path:
    return Path(unreal.Paths.project_saved_dir()) / "FloorPlan"


def _write_json(path: Path, payload) -> Path:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _read_raw_walls() -> List[Dict[str, object]]:
    """The untouched detection output, or [] when no run has been saved yet."""
    path = _floorplan_dir() / RAW_WALLS_JSON_NAME
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError) as exc:
        unreal.log_warning(f"Could not read {path}: {exc}")
        return []


# =============================================================================
# Combined mode: one WallGeneratorActor holding every wall
# =============================================================================

def _combined_type():
    return getattr(unreal, "WallGeneratorActor", None)


def get_combined_actor():
    """The single staged wall-generator actor, or None."""
    combined_type = _combined_type()
    for actor in _all_level_actors():
        if COMBINED_TAG in _actor_tags(actor):
            return actor
        if combined_type and isinstance(actor, combined_type) and actor.get_actor_label() == COMBINED_LABEL:
            return actor
    return None


def ensure_combined_blueprint() -> bool:
    """Create BP_FloorPlanWalls (parent WallGeneratorActor) if it is missing.

    Makes the staged actor a real Blueprint instance. Skipped in commandlets,
    where UE 5.7's Blueprint factory is not safe to run.
    """
    if unreal.EditorAssetLibrary.does_asset_exist(COMBINED_BLUEPRINT_PATH):
        return True
    if _is_commandlet() or not _combined_type():
        return False
    folder, name = COMBINED_BLUEPRINT_PATH.rsplit("/", 1)
    try:
        factory = unreal.BlueprintFactory()
        factory.set_editor_property("parent_class", _combined_type())
        blueprint = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, None, factory)
        if blueprint is None:
            unreal.log_warning(f"Could not create {COMBINED_BLUEPRINT_PATH}; using the native WallGeneratorActor.")
            return False
        unreal.EditorAssetLibrary.save_asset(COMBINED_BLUEPRINT_PATH)
        _log(f"   Created {COMBINED_BLUEPRINT_PATH} (parent WallGeneratorActor).")
        return True
    except Exception as exc:
        unreal.log_warning(f"Could not create {COMBINED_BLUEPRINT_PATH}: {exc}. Using the native WallGeneratorActor.")
        return False


def _spawn_combined_actor():
    """Spawn the BP_FloorPlanWalls child, creating it on first use; native as fallback."""
    subsystem = _actor_subsystem()
    location = unreal.Vector(0.0, 0.0, 0.0)
    rotation = unreal.Rotator(0.0, 0.0, 0.0)
    if ensure_combined_blueprint():
        actor = subsystem.spawn_actor_from_object(
            unreal.EditorAssetLibrary.load_asset(COMBINED_BLUEPRINT_PATH), location, rotation)
    else:
        combined_type = _combined_type()
        if not combined_type:
            raise RuntimeError(
                "WallGeneratorActor is unavailable. Build the Floor2Dto3Dplan module and restart Unreal Editor."
            )
        actor = subsystem.spawn_actor_from_class(combined_type, location, rotation)
    if not actor:
        raise RuntimeError("Unreal failed to spawn the combined wall actor.")
    _set_tags(actor, [COMBINED_TAG])
    actor.set_folder_path(unreal.Name(WALL_FOLDER))
    actor.set_actor_label(COMBINED_LABEL)
    return actor


def _struct_has_source_index() -> bool:
    """False until the editor has been rebuilt with FWallSegment.SourceIndex.

    Live Coding cannot add UPROPERTYs to a running editor, so the field may be
    in the source but not in the reflection data. Bookkeeping then falls back
    to a sidecar file next to walls.json.
    """
    try:
        unreal.WallSegment().get_editor_property("source_index")
        return True
    except Exception:
        return False


COMBINED_STATE_JSON_NAME = "combined_state.json"
_source_index_warning_shown = False


def _warn_source_index_fallback() -> None:
    global _source_index_warning_shown
    if not _source_index_warning_shown:
        _source_index_warning_shown = True
        unreal.log_warning(
            "FWallSegment.SourceIndex is not compiled into this editor session; tracking detected/added walls in "
            f"Saved/FloorPlan/{COMBINED_STATE_JSON_NAME} instead. Close the editor and do a full build to bake it in."
        )


def _load_state_indices() -> List[Optional[int]]:
    path = _floorplan_dir() / COMBINED_STATE_JSON_NAME
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        values = data.get("source_indices", []) if isinstance(data, dict) else []
        return [int(v) if v is not None else None for v in values]
    except (OSError, ValueError, TypeError) as exc:
        unreal.log_warning(f"Could not read {path}: {exc}")
        return []


def _save_state_indices(indices: Sequence[Optional[int]]) -> None:
    try:
        _write_json(_floorplan_dir() / COMBINED_STATE_JSON_NAME, {"source_indices": list(indices)})
    except OSError as exc:
        unreal.log_warning(f"Could not save {COMBINED_STATE_JSON_NAME}: {exc}")


def _make_segment(start: Sequence[float], end: Sequence[float], thickness: float, source_index: int):
    segment = unreal.WallSegment()
    segment.set_editor_property("start", unreal.Vector2D(float(start[0]), float(start[1])))
    segment.set_editor_property("end", unreal.Vector2D(float(end[0]), float(end[1])))
    segment.set_editor_property("thickness", float(thickness))
    if _struct_has_source_index():
        segment.set_editor_property("source_index", int(source_index))
    return segment


def _segments(actor) -> List[Any]:
    return list(actor.get_editor_property("wall_segments"))


def _combined_add(actor, segment) -> int:
    """Append a segment and rebuild. Uses the undo-friendly UFUNCTION when the
    editor has it; otherwise writes the array directly (pre-rebuild sessions)."""
    if hasattr(actor, "add_wall_segment"):
        return int(actor.add_wall_segment(segment))
    segments = _segments(actor)
    segments.append(segment)
    actor.set_editor_property("wall_segments", segments)
    actor.rebuild_mesh()
    return len(segments) - 1


def _combined_remove(actor, index: int) -> bool:
    if hasattr(actor, "remove_wall_segment_at"):
        return bool(actor.remove_wall_segment_at(index))
    segments = _segments(actor)
    if not 0 <= index < len(segments):
        return False
    del segments[index]
    actor.set_editor_property("wall_segments", segments)
    actor.rebuild_mesh()
    return True


def _source_indices(actor) -> List[Optional[int]]:
    """Raw 1-based detection index per WallSegments entry (None = added by hand)."""
    segments = _segments(actor)
    if _struct_has_source_index():
        result = []
        for segment in segments:
            try:
                value = int(segment.get_editor_property("source_index"))
            except Exception:
                value = -1
            result.append(value if value > 0 else None)
        return result

    _warn_source_index_fallback()
    indices = _load_state_indices()
    if len(indices) != len(segments):
        if indices:
            unreal.log_warning(
                f"{COMBINED_STATE_JSON_NAME} lists {len(indices)} wall(s) but {COMBINED_LABEL} has {len(segments)}; "
                "the WallSegments array was probably edited in Details. Treating every wall as detected by position."
            )
        indices = [i + 1 for i in range(len(segments))]
        _save_state_indices(indices)
    return indices


def _combined_records(actor) -> List[Dict[str, object]]:
    transform = actor.get_actor_transform()
    source_indices = _source_indices(actor)
    records = []
    for i, segment in enumerate(_segments(actor)):
        label = f"Wall_{i + 1:03d}"
        try:
            record = _world_record(
                transform,
                segment.get_editor_property("start"),
                segment.get_editor_property("end"),
                float(segment.get_editor_property("thickness")),
                label,
            )
        except ValueError as exc:
            unreal.log_warning(str(exc))
            continue
        index = source_indices[i] if i < len(source_indices) else None
        record["origin"] = corrections.ORIGIN_DETECTED if index is not None else corrections.ORIGIN_ADDED
        record["index"] = index
        record["label"] = label
        # Array position; the UI refreshes its list after every change.
        record["id"] = str(i)
        records.append(record)
    return records


def _combined_index_from_id(actor, wall_id: str) -> Optional[int]:
    count = len(_segments(actor))
    try:
        index = int(wall_id)
        return index if 0 <= index < count else None
    except (TypeError, ValueError):
        pass
    match = corrections.LABEL_PATTERN.match(str(wall_id))
    if match:
        index = int(match.group(1)) - 1
        return index if 0 <= index < count else None
    return None


# =============================================================================
# Individual mode: one WallSegmentActor per wall
# =============================================================================

def _individual_type():
    return getattr(unreal, "WallSegmentActor", None)


def get_editable_wall_actors() -> List[Any]:
    """Per-wall actors from individual mode, in stable label order."""
    native_type = _individual_type()
    actors = []
    for actor in _all_level_actors():
        if WALL_TAG in _actor_tags(actor) or (native_type and isinstance(actor, native_type)):
            actors.append(actor)
    return sorted(actors, key=lambda item: item.get_actor_label())


def _mark_wall_actor(actor, index: Optional[int] = None,
                     origin: str = corrections.ORIGIN_DETECTED, label: Optional[str] = None) -> None:
    tags = [
        tag for tag in _actor_tags(actor)
        if not tag.startswith((corrections.ORIGIN_TAG_PREFIX, corrections.INDEX_TAG_PREFIX)) and tag != WALL_TAG
    ]
    tags += [WALL_TAG, corrections.origin_tag(origin)]
    if index is not None:
        tags.append(corrections.index_tag(index))
    _set_tags(actor, tags)
    actor.set_folder_path(unreal.Name(WALL_FOLDER))
    if label is not None:
        actor.set_actor_label(label)
    elif index is not None:
        actor.set_actor_label(f"Wall_{index:03d}")


def _spawn_wall_actor(location: Optional[Any] = None):
    subsystem = _actor_subsystem()
    location = location or unreal.Vector(0.0, 0.0, 0.0)
    rotation = unreal.Rotator(0.0, 0.0, 0.0)
    if unreal.EditorAssetLibrary.does_asset_exist(WALL_BLUEPRINT_PATH):
        actor = subsystem.spawn_actor_from_object(
            unreal.EditorAssetLibrary.load_asset(WALL_BLUEPRINT_PATH), location, rotation)
    else:
        native_type = _individual_type()
        if not native_type:
            raise RuntimeError(
                "WallSegmentActor is unavailable. Build the Floor2Dto3Dplan module and restart Unreal Editor."
            )
        actor = subsystem.spawn_actor_from_class(native_type, location, rotation)
    if not actor:
        raise RuntimeError("Unreal failed to spawn an editable wall actor.")
    return actor


def _set_wall_properties(actor, start, end, thickness: float, height: float, generate_collision: bool) -> None:
    start_2d = unreal.Vector2D(float(start[0]), float(start[1]))
    end_2d = unreal.Vector2D(float(end[0]), float(end[1]))
    if hasattr(actor, "set_wall"):
        if not actor.set_wall(start_2d, end_2d, float(thickness), float(height), bool(generate_collision)):
            raise RuntimeError(f"{actor.get_name()} rejected invalid wall dimensions.")
        return
    # Pure-Blueprint alternative from the workflow guide.
    actor.set_editor_property("start", start_2d)
    actor.set_editor_property("end", end_2d)
    actor.set_editor_property("thickness", float(thickness))
    actor.set_editor_property("height", float(height))
    try:
        actor.set_editor_property("generate_collision", bool(generate_collision))
    except Exception:
        pass
    actor.rerun_construction_scripts()


def _individual_records(actors: Sequence[Any]) -> List[Dict[str, object]]:
    records = []
    for actor in actors:
        try:
            record = _world_record(
                actor.get_actor_transform(),
                actor.get_editor_property("start"),
                actor.get_editor_property("end"),
                float(actor.get_editor_property("thickness")),
                actor.get_actor_label(),
            )
        except ValueError as exc:
            unreal.log_warning(str(exc))
            continue
        origin, index = corrections.parse_tags(_actor_tags(actor))
        record["origin"] = origin or corrections.ORIGIN_DETECTED
        record["index"] = index
        record["label"] = actor.get_actor_label()
        record["id"] = actor.get_path_name()
        records.append(record)
    return records


def _find_wall_actor(wall_id: str):
    actors = get_editable_wall_actors()
    for actor in actors:
        if actor.get_path_name() == wall_id:
            return actor
    for actor in actors:
        if actor.get_actor_label() == wall_id:
            return actor
    return None


# =============================================================================
# Mode-agnostic staging API (what the UI calls)
# =============================================================================

def clear_editable_walls() -> int:
    """Delete everything this workflow staged, in either mode."""
    subsystem = _actor_subsystem()
    removed = 0
    combined = get_combined_actor()
    if combined is not None:
        subsystem.destroy_actor(combined)
        removed += 1
    for actor in get_editable_wall_actors():
        subsystem.destroy_actor(actor)
        removed += 1
    return removed


def spawn_detected_walls(
    walls: Sequence[Dict[str, object]],
    wall_height_cm: float = WALL_HEIGHT_CM,
    generate_collision: bool = True,
    clear_existing: bool = True,
    combined: bool = USE_COMBINED_ACTOR,
) -> int:
    """Stage detected walls. Returns how many walls were staged."""
    if clear_existing:
        removed = clear_editable_walls()
        if removed:
            _log(f"   Removed {removed} previously staged wall actor(s).")

    if combined:
        actor = _spawn_combined_actor()
        segments = [
            _make_segment(wall["start"], wall["end"], float(wall["thickness"]), index)
            for index, wall in enumerate(walls, start=1)
        ]
        if not actor.generate_walls(segments, float(wall_height_cm), bool(generate_collision)):
            _actor_subsystem().destroy_actor(actor)
            raise RuntimeError("The combined wall actor rejected the detected segments.")
        if not _struct_has_source_index():
            _warn_source_index_fallback()
            _save_state_indices([i + 1 for i in range(len(segments))])
        _log(
            f"9. Spawned one combined actor '{COMBINED_LABEL}' holding {len(segments)} wall(s) "
            f"in the '{WALL_FOLDER}' Outliner folder. Edit its WallSegments array or use the correction list."
        )
        return len(segments)

    if not unreal.EditorAssetLibrary.does_asset_exist(WALL_BLUEPRINT_PATH):
        unreal.log_warning(
            f"{WALL_BLUEPRINT_PATH} does not exist; using native WallSegmentActor instances. "
            "Create the thin Blueprint child described in Docs/EditableWallWorkflow.md when Blueprint assets are required."
        )
    spawned = []
    try:
        for index, wall in enumerate(walls, start=1):
            actor = _spawn_wall_actor()
            _set_wall_properties(actor, wall["start"], wall["end"], float(wall["thickness"]),
                                 wall_height_cm, generate_collision)
            _mark_wall_actor(actor, index)
            spawned.append(actor)
    except Exception:
        for actor in spawned:
            _actor_subsystem().destroy_actor(actor)
        raise
    _log(f"9. Spawned {len(spawned)} independently selectable wall actor(s) in the '{WALL_FOLDER}' Outliner folder.")
    return len(spawned)


def _current_records() -> Tuple[List[Dict[str, object]], str]:
    """(records, mode) for whatever is staged right now."""
    combined = get_combined_actor()
    if combined is not None:
        return _combined_records(combined), "combined"
    return _individual_records(get_editable_wall_actors()), "individual"


def list_walls() -> List[Dict[str, object]]:
    """Rows for the correction UI: stable id, label, origin and a summary."""
    records, mode = _current_records()
    return [
        {
            "id": record["id"],
            "label": record["label"],
            "origin": record["origin"],
            "index": record["index"],
            "summary": corrections.describe_wall(record),
            "start": record["start"],
            "end": record["end"],
            "thickness": record["thickness"],
            "mode": mode,
        }
        for record in records
    ]


def select_wall(wall_id: str) -> bool:
    """Select the wall and frame it in the active viewport."""
    combined = get_combined_actor()
    if combined is not None:
        index = _combined_index_from_id(combined, wall_id)
        if index is None:
            unreal.log_warning(f"Select: no wall matches '{wall_id}' in {COMBINED_LABEL}.")
            return False
        segment = _segments(combined)[index]
        start = segment.get_editor_property("start")
        end = segment.get_editor_property("end")
        midpoint_local = unreal.Vector((start.x + end.x) * 0.5, (start.y + end.y) * 0.5,
                                       float(combined.get_editor_property("wall_height")) * 0.5)
        _select(combined)
        _frame_point(combined.get_actor_transform().transform_location(midpoint_local))
        _log(f"Selected {COMBINED_LABEL} and framed Wall_{index + 1:03d}. Its values are WallSegments[{index}] in Details.")
        return True

    actor = _find_wall_actor(wall_id)
    if actor is None:
        unreal.log_warning(f"Select: no editable wall matches '{wall_id}'.")
        return False
    _select(actor)
    if not _is_commandlet():
        try:
            world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
            unreal.SystemLibrary.execute_console_command(world, "CAMERA ALIGN ACTIVEVIEWPORTONLY")
        except Exception as exc:
            unreal.log_warning(f"Selected {actor.get_actor_label()} but could not frame it: {exc}")
    return True


def remove_wall(wall_id: str) -> bool:
    """Delete one wall as a user correction. The combined actor rebuilds itself."""
    combined = get_combined_actor()
    if combined is not None:
        index = _combined_index_from_id(combined, wall_id)
        if index is None:
            unreal.log_warning(f"Remove: no wall matches '{wall_id}' in {COMBINED_LABEL}.")
            return False
        source_indices = _source_indices(combined)
        source_index = source_indices[index] if index < len(source_indices) else None
        label = f"Wall_{index + 1:03d}"
        if not _combined_remove(combined, index):
            return False
        if not _struct_has_source_index():
            del source_indices[index]
            _save_state_indices(source_indices)
        _log(f"User removed wall {corrections.wall_number(label, source_index)} ({label}); "
             f"{COMBINED_LABEL} now has {len(_segments(combined))} wall(s).")
        return True

    actor = _find_wall_actor(wall_id)
    if actor is None:
        unreal.log_warning(f"Remove: no editable wall matches '{wall_id}'.")
        return False
    label = actor.get_actor_label()
    _, index = corrections.parse_tags(_actor_tags(actor))
    _actor_subsystem().destroy_actor(actor)
    _log(f"User removed wall {corrections.wall_number(label, index)} ({label}).")
    return True


def add_wall(
    length_cm: float = DEFAULT_NEW_WALL_LENGTH_CM,
    thickness_cm: float = DEFAULT_WALL_THICKNESS_CM,
    height_cm: float = WALL_HEIGHT_CM,
    generate_collision: bool = True,
    combined: bool = USE_COMBINED_ACTOR,
):
    """Add a short wall at the viewport focus for something the detector missed.

    In combined mode it becomes a new WallSegments entry on the single actor;
    otherwise a new selectable actor. `combined` only matters when nothing is
    staged yet; afterwards the existing mode wins.
    """
    length_cm = max(float(length_cm), 1.0)
    focus = _viewport_floor_point()

    combined_actor = get_combined_actor()
    if combined_actor is None and combined and not get_editable_wall_actors():
        combined_actor = _spawn_combined_actor()
        combined_actor.set_editor_property("wall_height", float(height_cm))

    if combined_actor is not None:
        # Store the segment in the actor's local space so its transform still applies.
        local = combined_actor.get_actor_transform().inverse_transform_location(focus)
        half = length_cm * 0.5
        segment = _make_segment((local.x - half, local.y), (local.x + half, local.y), thickness_cm, -1)
        if not _struct_has_source_index():
            # Read before the add so the sidecar length still matches the array.
            source_indices = _source_indices(combined_actor)
        index = _combined_add(combined_actor, segment)
        if not _struct_has_source_index():
            source_indices.append(None)
            _save_state_indices(source_indices)
        if generate_collision:
            combined_actor.generate_collision()
        label = f"Wall_{index + 1:03d}"
        _select(combined_actor)
        _log(f"User added wall {corrections.wall_number(label, None)} ({label}) to {COMBINED_LABEL} at the viewport "
             f"focus plane. Adjust it as WallSegments[{index}] in Details or with the correction list.")
        return combined_actor

    label = corrections.next_wall_label(a.get_actor_label() for a in get_editable_wall_actors())
    actor = _spawn_wall_actor(focus)
    _set_wall_properties(actor, (-length_cm * 0.5, 0.0), (length_cm * 0.5, 0.0),
                         thickness_cm, height_cm, generate_collision)
    _mark_wall_actor(actor, origin=corrections.ORIGIN_ADDED, label=label)
    _select(actor)
    _log(f"User added wall {corrections.wall_number(label, None)} ({label}) at the viewport focus plane. "
         "Use native grid/rotation snapping to place it.")
    return actor


def add_wall_at(
    start: Sequence[float],
    end: Sequence[float],
    thickness_cm: float = DEFAULT_WALL_THICKNESS_CM,
    height_cm: float = WALL_HEIGHT_CM,
    generate_collision: bool = True,
    combined: bool = USE_COMBINED_ACTOR,
) -> Optional[str]:
    """Add a wall between two world-space points (cm), as drawn in the correction window.

    Returns the new wall's id for the UI (array index in combined mode, actor
    path otherwise), or None when the segment is too short to be a wall.
    """
    sx, sy, ex, ey = float(start[0]), float(start[1]), float(end[0]), float(end[1])
    if math.hypot(ex - sx, ey - sy) < 1.0:
        unreal.log_warning("Drawn wall is shorter than 1 cm; ignored.")
        return None

    combined_actor = get_combined_actor()
    if combined_actor is None and combined and not get_editable_wall_actors():
        combined_actor = _spawn_combined_actor()
        combined_actor.set_editor_property("wall_height", float(height_cm))

    if combined_actor is not None:
        transform = combined_actor.get_actor_transform()
        local_start = transform.inverse_transform_location(unreal.Vector(sx, sy, 0.0))
        local_end = transform.inverse_transform_location(unreal.Vector(ex, ey, 0.0))
        segment = _make_segment((local_start.x, local_start.y), (local_end.x, local_end.y), thickness_cm, -1)
        if not _struct_has_source_index():
            source_indices = _source_indices(combined_actor)
        index = _combined_add(combined_actor, segment)
        if not _struct_has_source_index():
            source_indices.append(None)
            _save_state_indices(source_indices)
        if generate_collision:
            combined_actor.generate_collision()
        label = f"Wall_{index + 1:03d}"
        _log(f"User added wall {corrections.wall_number(label, None)} ({label}) by drawing it: "
             f"({sx:.0f}, {sy:.0f}) to ({ex:.0f}, {ey:.0f}) cm.")
        return str(index)

    label = corrections.next_wall_label(a.get_actor_label() for a in get_editable_wall_actors())
    actor = _spawn_wall_actor(unreal.Vector(0.0, 0.0, 0.0))
    _set_wall_properties(actor, (sx, sy), (ex, ey), thickness_cm, height_cm, generate_collision)
    _mark_wall_actor(actor, origin=corrections.ORIGIN_ADDED, label=label)
    _log(f"User added wall {corrections.wall_number(label, None)} ({label}) by drawing it: "
         f"({sx:.0f}, {sy:.0f}) to ({ex:.0f}, {ey:.0f}) cm.")
    return actor.get_path_name()


def _sanitize_asset_name(text: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in text).strip("_")
    return cleaned or "FloorPlan"


def import_floorplan_texture(image_path: str) -> Dict[str, object]:
    """Import a PNG/JPG floor plan as a Texture2D asset for the correction window.

    Returns {"asset_path", "width", "height"} or {} for non-image sources
    (PDF/DXF/DWG have no raster to show) and on failure.
    """
    path = Path(image_path)
    if path.suffix.lower() not in IMAGE_SUFFIXES or not path.is_file():
        return {}

    name = "T_" + _sanitize_asset_name(path.stem)
    asset_path = f"{TEXTURE_FOLDER}/{name}"
    try:
        task = unreal.AssetImportTask()
        task.set_editor_property("filename", str(path))
        task.set_editor_property("destination_path", TEXTURE_FOLDER)
        task.set_editor_property("destination_name", name)
        task.set_editor_property("replace_existing", True)
        task.set_editor_property("automated", True)
        task.set_editor_property("save", False)
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    except Exception as exc:
        unreal.log_warning(f"Could not import {path.name} as a texture: {exc}")
        return {}

    if not unreal.EditorAssetLibrary.does_asset_exist(asset_path):
        unreal.log_warning(f"Texture import produced no asset at {asset_path}.")
        return {}

    texture = unreal.EditorAssetLibrary.load_asset(asset_path)
    try:
        # Plans are line art: keep them crisp, unstreamed and uncompressed-looking.
        texture.set_editor_property("lod_group", unreal.TextureGroup.TEXTUREGROUP_UI)
        texture.set_editor_property("never_stream", True)
        texture.set_editor_property("srgb", True)
    except Exception:
        pass
    unreal.EditorAssetLibrary.save_asset(asset_path)

    try:
        width = int(texture.blueprint_get_size_x())
        height = int(texture.blueprint_get_size_y())
    except Exception:
        width = height = 0
    _log(f"   Imported floor plan image as {asset_path} ({width}x{height}).")
    return {"asset_path": asset_path, "width": width, "height": height, "source": str(path)}


def _ensure_collision() -> None:
    """Geometry Script 'Set Collision From Mesh' equivalent for whichever mode is staged."""
    combined = get_combined_actor()
    if combined is not None:
        combined.rebuild_mesh()
        combined.generate_collision()
        return
    for actor in get_editable_wall_actors():
        try:
            actor.set_editor_property("generate_collision", True)
        except Exception:
            pass
        if hasattr(actor, "rebuild_wall"):
            actor.rebuild_wall()
        else:
            actor.rerun_construction_scripts()


def export_corrected_walls(output_path: str = "") -> str:
    """Write the staged walls, with world transforms applied, to walls_corrected.json."""
    records, _ = _current_records()
    if not records:
        raise RuntimeError(f"No staged walls were found in '{WALL_FOLDER}'.")
    output = _write_json(
        Path(output_path) if output_path else _floorplan_dir() / CORRECTED_WALLS_JSON_NAME,
        corrections.export_records(records),
    )
    _log(f"Exported {len(records)} corrected wall segment(s) to {output}")
    return str(output)


def _staged_actors() -> List[Any]:
    """Whatever holds the walls right now: the combined actor, or every per-wall actor."""
    combined = get_combined_actor()
    return [combined] if combined is not None else get_editable_wall_actors()


def bake_walls_to_static_mesh(
    generate_collision: bool = True,
    remove_sources: bool = True,
    enable_nanite: bool = BAKE_ENABLE_NANITE,
    base_name: str = BAKE_BASE_NAME,
) -> Dict[str, object]:
    """Bake the staged Dynamic Mesh walls into one Static Mesh asset + actor.

    One-directional: after this the Dynamic Mesh actors are gone (unless
    remove_sources is False), so it is only called from finalize_walls once
    the corrections are locked in. Returns {"static_mesh", "actor"} or {}.
    """
    library = getattr(unreal, "FloorPlanAssetLibrary", None)
    if library is None or not hasattr(library, "bake_walls_to_static_mesh"):
        unreal.log_warning(
            "FloorPlanAssetLibrary.bake_walls_to_static_mesh is not compiled into this editor; "
            "skipping the Static Mesh bake. Close the editor and do a full build to enable it."
        )
        return {}

    actors = _staged_actors()
    if not actors:
        return {}

    _log("Baking corrected walls to Static Mesh...")
    result = library.bake_walls_to_static_mesh(
        actors, BAKE_MESH_FOLDER, base_name, bool(generate_collision), bool(remove_sources), bool(enable_nanite)
    )
    # UFUNCTIONs with out-params come back as (ReturnValue, OutStaticMeshPath).
    actor, mesh_path = (result if isinstance(result, (tuple, list)) else (result, ""))
    if actor is None:
        unreal.log_error("Static Mesh bake failed; the Dynamic Mesh actors were left in place. See the log above.")
        return {}
    if not _struct_has_source_index():
        # The combined actor is gone, so the sidecar no longer describes anything.
        _save_state_indices([])
    return {"static_mesh": str(mesh_path), "actor": actor.get_actor_label()}


def finalize_walls(output_path: str = "", bake: bool = BAKE_ON_FINALIZE) -> Dict[str, object]:
    """Lock in the corrections: collision, walls_corrected.json, a diff against
    the raw detection, then (by default) bake everything into one Static Mesh."""
    records, mode = _current_records()
    if not records:
        raise RuntimeError(f"No staged walls were found in '{WALL_FOLDER}'. Detect or add walls first.")

    _ensure_collision()
    records, mode = _current_records()   # re-read after the rebuild

    summary = corrections.compute_corrections(_read_raw_walls(), records)
    output = _write_json(
        Path(output_path) if output_path else _floorplan_dir() / CORRECTED_WALLS_JSON_NAME,
        corrections.export_records(records),
    )
    summary["path"] = str(output)
    summary["mode"] = mode
    target = f"the '{COMBINED_LABEL}' actor" if mode == "combined" else f"{len(records)} wall actors"
    _log(
        f"Finalized: {summary['final']} walls, {summary['corrections']} corrections applied "
        f"({summary['removed']} removed, {summary['added']} added, {summary['adjusted']} adjusted). "
        f"Collision applied to {target}. Wrote {output}"
    )

    # Bake last: the JSON and the correction counts above must come from the
    # live Dynamic Mesh actors, which the bake removes.
    if bake:
        collision = True
        if mode == "combined":
            try:
                collision = bool(get_combined_actor().dynamic_mesh_component.get_collision_enabled()
                                 != unreal.CollisionEnabled.NO_COLLISION)
            except Exception:
                collision = True
        baked = bake_walls_to_static_mesh(generate_collision=collision)
        summary.update(baked)
    return summary


def open_correction_ui() -> bool:
    """Open the optional EUW_WallCorrection widget if the user has built it."""
    _log("Opening wall correction UI...")
    if _is_commandlet():
        return False
    if not unreal.EditorAssetLibrary.does_asset_exist(CORRECTION_WIDGET_PATH):
        _log(f"   {CORRECTION_WIDGET_PATH} not found; use the Wall correction section of the Floor Plan Import panel.")
        return False
    try:
        widget_bp = unreal.EditorAssetLibrary.load_asset(CORRECTION_WIDGET_PATH)
        unreal.get_editor_subsystem(unreal.EditorUtilitySubsystem).spawn_and_register_tab(widget_bp)
        return True
    except Exception as exc:
        unreal.log_warning(f"Could not open {CORRECTION_WIDGET_PATH}: {exc}")
        return False


# =============================================================================
# Pipeline entry point
# =============================================================================

def import_floor_plan_with_options(options: Optional[Dict[str, Any]] = None) -> int:
    """Run the whole pipeline.

    Returns the number of staged walls, 0 when nothing was detected, and -1
    when the run failed before detection could produce a result.
    """
    options = options or {}
    show_dialogs = bool(options.get("show_dialogs", True))
    combined = bool(options.get("combined_actor", USE_COMBINED_ACTOR))

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
        unreal.log_error("No walls detected. Nothing was staged. See numbered log lines above.")
        if show_dialogs:
            unreal.EditorDialog.show_message(
                unreal.Text("Floor Plan Import"),
                unreal.Text("No walls were detected. Check the log for layer counts and routing errors."),
                unreal.AppMsgType.OK,
            )
        return 0

    required = "WallGeneratorActor" if combined else "WallSegmentActor"
    if not hasattr(unreal, required):
        unreal.log_error(f"Native {required} is missing. Compile Floor2Dto3Dplan and restart Unreal Editor.")
        return -1

    # Raw detection output. Finalize writes a separate file, so this stays a
    # faithful record of what the detector produced.
    try:
        raw_path = _write_json(_floorplan_dir() / RAW_WALLS_JSON_NAME, corrections.export_records(walls))
        _log(f"   Raw detection saved to {raw_path}")
    except OSError as exc:
        unreal.log_warning(f"Could not save raw {RAW_WALLS_JSON_NAME}: {exc}")

    try:
        count = spawn_detected_walls(
            walls,
            wall_height_cm=float(options.get("wall_height_cm", WALL_HEIGHT_CM)),
            generate_collision=bool(options.get("generate_collision", True)),
            clear_existing=bool(options.get("clear_existing_walls", True)),
            combined=combined,
        )
    except Exception as exc:
        unreal.log_error(f"Could not stage the detected walls: {exc}")
        return -1

    _log(
        f"10. {count} walls detected. Review them in the Wall correction list: remove false positives, "
        "Add Wall for anything missed, adjust values, then Finalize."
    )
    if bool(options.get("open_correction_ui", True)):
        open_correction_ui()
    return count


def import_floor_plan(file_path: str = "") -> int:
    """Menu-entry entry point: native file picker plus module defaults."""
    return import_floor_plan_with_options({"file_path": file_path})
