"""Editor startup: Tools > Import Floor Plan Walls..."""

import unreal

_MENU_ENTRY = None


@unreal.uclass()
class FloorPlanImportMenuEntry(unreal.ToolMenuEntryScript):
    @unreal.ufunction(override=True)
    def execute(self, context):
        import importlib

        import floorplan_detector
        import unreal_floorplan_router as router

        # Python caches modules for the editor session, so pick up on-disk
        # edits here. The detector must reload first: the router binds
        # detect_walls_from_path by value at import time.
        importlib.reload(floorplan_detector)
        importlib.reload(router)
        router.import_floor_plan()


def _register_menu() -> None:
    global _MENU_ENTRY
    menus = unreal.ToolMenus.get()
    menus.extend_menu("LevelEditor.MainMenu.Tools")
    menu = menus.find_menu("LevelEditor.MainMenu.Tools")
    if not menu:
        unreal.log_warning("Floor plan importer: LevelEditor.MainMenu.Tools was not found.")
        return

    menu.add_section("FloorPlanToWalls", unreal.Text("Floor Plan"))
    _MENU_ENTRY = FloorPlanImportMenuEntry()
    _MENU_ENTRY.init_entry(
        "Floor2Dto3Dplan",
        "LevelEditor.MainMenu.Tools",
        "FloorPlanToWalls",
        "ImportFloorPlanWalls",
        unreal.Text("Quick Import Floor Plan (defaults)..."),
        unreal.Text(
            "One-click import using the defaults in unreal_floorplan_router.py. "
            "For adjustable settings and an inline log, use Tools > Floor Plan Import instead."
        ),
    )
    _MENU_ENTRY.register_menu_entry()
    menus.refresh_all_widgets()
    unreal.log("Floor plan importer ready: Tools > Floor Plan Import (panel), or Quick Import for defaults.")


_register_menu()
