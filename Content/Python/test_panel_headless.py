"""Headless end-to-end test of editable per-wall import and JSON export.

Run with:
    UnrealEditor-Cmd.exe <uproject> -run=pythonscript
        -script="<project>/Content/Python/test_panel_headless.py"
        -unattended -nullrhi -nosplash

Use forward slashes in the -script path; backslashes get eaten as escapes.
"""

import json
import tempfile
from pathlib import Path

import unreal

import floorplan_panel

EXPECTED_WALLS = 4


def build_synthetic_plan() -> str:
    import cv2
    import numpy as np

    image = np.full((300, 400), 255, dtype=np.uint8)
    cv2.rectangle(image, (40, 40), (360, 260), 0, 10)
    path = Path(tempfile.gettempdir()) / "panel_headless_plan.png"
    cv2.imwrite(str(path), image)
    return str(path)


def run() -> None:
    plan_path = build_synthetic_plan()
    unreal.log(f"Synthetic plan written to {plan_path}")
    payload = json.dumps({
        "file_path": plan_path,
        "pixels_per_foot": 10.0,
        "wall_height_cm": 275.0,
        "default_thickness_cm": 15.0,
        "dxf_units_to_unreal_cm": 2.54,
        "raster_dpi": 300.0,
        "pdf_page_index": 0,
        "cad_layer_filter": "",
        "oda_converter_path": "",
        "generate_collision": True,
        "show_dialogs": False,
    }, separators=(",", ":"))

    result = floorplan_panel.run_from_json(payload)
    unreal.log(f"run_from_json returned {result!r}")

    if result != EXPECTED_WALLS:
        raise RuntimeError(f"Expected {EXPECTED_WALLS} walls, got {result!r}")

    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    combined_actors = [
        actor for actor in subsystem.get_all_level_actors()
        if isinstance(actor, unreal.WallGeneratorActor)
    ]
    if combined_actors:
        raise RuntimeError("Legacy combined WallGeneratorActor should not be created.")

    import unreal_floorplan_router as router
    editable = router.get_editable_wall_actors()
    if len(editable) != EXPECTED_WALLS:
        raise RuntimeError(f"Expected {EXPECTED_WALLS} editable actors, got {len(editable)}.")
    if not all(isinstance(actor, unreal.WallSegmentActor) for actor in editable):
        raise RuntimeError("At least one generated actor is not a WallSegmentActor/BP child.")
    if not all(
        any(str(tag) == router.WALL_TAG for tag in actor.get_editor_property("tags"))
        for actor in editable
    ):
        raise RuntimeError("At least one generated actor is missing the editable-wall tag.")

    first = editable[0]
    local_start = first.get_editor_property("start")
    first.set_actor_location(unreal.Vector(25.0, 10.0, 0.0), False, False)
    first.set_actor_rotation(unreal.Rotator(0.0, 0.0, 30.0), False)
    first.set_actor_scale3d(unreal.Vector(1.5, 2.0, 1.0))
    expected_start = first.get_actor_transform().transform_location(
        unreal.Vector(float(local_start.x), float(local_start.y), 0.0)
    )
    export_path = str(Path(tempfile.gettempdir()) / "floorplan_corrected_walls.json")
    written_path = router.export_corrected_walls(export_path)
    records = json.loads(Path(written_path).read_text(encoding="utf-8"))
    if len(records) != EXPECTED_WALLS:
        raise RuntimeError(f"Expected {EXPECTED_WALLS} exported records, got {len(records)}.")
    if records[0]["start"] != [
        round(float(expected_start.x), 4),
        round(float(expected_start.y), 4),
    ]:
        raise RuntimeError("Export did not apply the wall actor's translation, rotation, and scale.")

    unreal.log(
        f"PASS: spawned {len(editable)} independent walls and exported corrected transforms to {written_path}."
    )


run()
