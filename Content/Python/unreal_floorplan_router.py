"""Unreal Editor router: detect walls and create a Blueprint with a Static Mesh.

No Blender, GLB, or FBX. Mesh units are Unreal centimetres. The native
WallGeneratorActor is only an intermediate editable-geometry builder; a
successful import ends as reusable Static Mesh and Blueprint assets.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

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


def _log(message: str) -> None:
    unreal.log(message)


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

    if not hasattr(unreal, "WallGeneratorActor"):
        unreal.log_error(
            "Native WallGeneratorActor is missing. Compile Floor2Dto3Dplan and restart Unreal Editor."
        )
        return -1

    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actor = subsystem.spawn_actor_from_class(
        unreal.WallGeneratorActor,
        unreal.Vector(0.0, 0.0, 0.0),
        unreal.Rotator(0.0, 0.0, 0.0),
    )
    if not actor:
        unreal.log_error("Failed to spawn WallGeneratorActor in the current level.")
        return -1

    segments: List[unreal.WallSegment] = []
    for wall in walls:
        segment = unreal.WallSegment()
        segment.set_editor_property("start", unreal.Vector2D(wall["start"][0], wall["start"][1]))
        segment.set_editor_property("end", unreal.Vector2D(wall["end"][0], wall["end"][1]))
        segment.set_editor_property("thickness", float(wall["thickness"]))
        segments.append(segment)

    wall_height = float(options.get("wall_height_cm", WALL_HEIGHT_CM))
    generate_collision = bool(options.get("generate_collision", True))

    if not actor.generate_walls(segments, wall_height, generate_collision):
        unreal.log_error("Native GenerateWalls failed; removing the empty actor.")
        subsystem.destroy_actor(actor)
        return -1

    _log(
        f"8. Built {actor.get_name()} with {len(segments)} wall segments, "
        f"height={wall_height} cm."
    )

    if not hasattr(unreal, "FloorPlanAssetLibrary"):
        unreal.log_error(
            "FloorPlanAssetLibrary is missing. Compile Floor2Dto3DplanEditor and restart Unreal Editor."
        )
        subsystem.destroy_actor(actor)
        return -1

    output_folder = str(
        options.get("output_folder", "/Game/Generated/FloorPlans")
    ).strip()
    asset_base_name = os.path.splitext(os.path.basename(path))[0] or "FloorPlan"
    blueprint = unreal.FloorPlanAssetLibrary.finalize_wall_generator_as_blueprint(
        actor,
        output_folder,
        asset_base_name,
        generate_collision,
    )
    if not blueprint:
        unreal.log_error(
            "Could not create the final Blueprint and Static Mesh assets. "
            "The intermediate wall actor was kept when possible for diagnosis."
        )
        return -1

    _log(f"9. Final Blueprint: {blueprint.get_path_name()}")
    _log(
        "10. Final output is a placed Blueprint containing a saved Static Mesh"
        + (" with collision." if generate_collision else " without collision.")
    )

    return len(segments)


def import_floor_plan(file_path: str = "") -> int:
    """Menu-entry entry point: native file picker plus module defaults."""
    return import_floor_plan_with_options({"file_path": file_path})
