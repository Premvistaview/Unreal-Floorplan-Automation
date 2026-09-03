"""Headless end-to-end test of the Floor Plan Import panel's Python bridge.

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
    output_folder = "/Game/Generated/FloorPlanTests"
    assets_before = set(
        unreal.EditorAssetLibrary.list_assets(output_folder, recursive=True)
    )

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
        "output_folder": output_folder,
    }, separators=(",", ":"))

    result = floorplan_panel.run_from_json(payload)
    unreal.log(f"run_from_json returned {result!r}")

    if result != EXPECTED_WALLS:
        raise RuntimeError(f"Expected {EXPECTED_WALLS} walls, got {result!r}")

    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    intermediate_actors = [
        actor for actor in subsystem.get_all_level_actors()
        if isinstance(actor, unreal.WallGeneratorActor)
    ]
    if intermediate_actors:
        raise RuntimeError("The intermediate WallGeneratorActor was not removed.")

    assets_after = set(
        unreal.EditorAssetLibrary.list_assets(output_folder, recursive=True)
    )
    new_assets = assets_after - assets_before
    blueprint_assets = [
        path for path in new_assets
        if "/BP_" in path and not path.endswith("_C")
    ]
    static_mesh_assets = [path for path in new_assets if "/SM_" in path]
    if len(blueprint_assets) != 1 or len(static_mesh_assets) != 1:
        raise RuntimeError(
            "Expected one new Blueprint and one new Static Mesh; "
            f"created assets were {sorted(new_assets)}"
        )

    matching_instances = []
    for actor in subsystem.get_all_level_actors():
        mesh_component = actor.get_component_by_class(unreal.StaticMeshComponent)
        if not mesh_component:
            continue
        static_mesh = mesh_component.get_editor_property("static_mesh")
        if static_mesh and static_mesh.get_path_name().startswith(
            static_mesh_assets[0].split(".")[0]
        ):
            matching_instances.append(actor)

    if len(matching_instances) != 1:
        raise RuntimeError(
            "Expected one placed Blueprint instance using the generated Static Mesh, "
            f"got {len(matching_instances)}."
        )

    unreal.log(
        "PASS: final output is Blueprint "
        f"{blueprint_assets[0]} with Static Mesh {static_mesh_assets[0]}."
    )


run()
