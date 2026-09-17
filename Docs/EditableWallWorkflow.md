# Editable wall correction workflow

Detected walls are staged in the level in one of two modes, chosen with the
**Single combined actor** checkbox in the Floor Plan Import panel. Both modes
use the same correction list, the same JSON files, and the same Finalize step.

## Combined mode (default): one actor holding every wall

Detection spawns a single `WallGeneratorActor` — or, if it exists, your
`/Game/FloorPlan/Blueprints/BP_FloorPlanWalls` child of it — labelled
`FloorPlan_Walls`, tagged `FloorPlanCombinedWalls`, in the `FloorPlan_Walls`
Outliner folder. Every wall is one entry in its `WallSegments` array
(`Start`, `End`, `Thickness`, and an advanced `SourceIndex` that remembers
which raw detection it came from). The actor rebuilds its one Dynamic Mesh
whenever that array changes, so the correction UI and the Details panel both
edit the same generated actor live:

- **Remove** in the list deletes that array entry; the mesh updates at once.
- **Add Wall** appends an entry at the viewport focus, in the actor's local
  space, so moving the whole actor still moves every wall with it.
- **Select in Viewport** selects the actor and points the camera at that wall;
  the log tells you which `WallSegments[N]` entry it is so you can type exact
  values in Details.
- Editing `WallSegments`, `WallHeight`, or the actor's transform in Details or
  the viewport also rebuilds it. Adding or deleting array entries by hand is
  fine; entries you add that way count as *added* because their
  `SourceIndex` is -1.

What you give up compared with individual mode is grabbing one wall with the
move gizmo: with one actor, gizmos move the whole plan. Use the list plus the
`WallSegments` array for per-wall changes.

The combined actor is a Blueprint instance: on first use detection creates
`/Game/FloorPlan/Blueprints/BP_FloorPlanWalls` (parent **WallGeneratorActor**)
and spawns that. You can open and extend the Blueprint like any other; do not
add another mesh component, because the inherited `DynamicMeshComponent`,
`WallSegments`, and `WallHeight` are already there. If the asset cannot be
created (for example in a commandlet) the native class is used instead.

## Individual mode: one actor per wall

Untick **Single combined actor** and detection creates one actor per wall
instead, each placed in the `FloorPlan_Walls` folder and tagged
`FloorPlanEditableWall`. This is the mode to use when you want to drag,
rotate, or scale single walls with the ordinary viewport gizmos.

## Recommended BP_WallSegment setup (individual mode)

The implementation uses native class `AWallSegmentActor` for reliable mesh
construction and exposes it to Blueprint. Create this thin child once:

`/Game/FloorPlan/Blueprints/BP_WallSegment`

To create it manually:

1. In the Content Browser, create **Blueprint Class**.
2. Choose **All Classes > WallSegmentActor**.
3. Save it as `BP_WallSegment` under
   `/Game/FloorPlan/Blueprints`.
4. Open it and compile. Do not add another mesh component or duplicate the
   variables. The inherited `DynamicMesh`, `Start`, `End`, `Thickness`,
   `Height`, and `Generate Collision` properties are already present.

The native parent performs the same work a Blueprint Construction Script
would perform and rebuilds automatically when a property changes. Keeping the
Blueprint thin avoids fragile Geometry Script node serialization while still
making every imported instance a normal Blueprint actor.

Until this asset exists, imports deliberately fall back to native
`WallSegmentActor` instances so the correction workflow remains usable. The
importer does not auto-create the Blueprint: UE 5.7's Blueprint factory can
crash in headless editor/commandlet runs.

### Pure-Blueprint alternative

Use this only if the project must not use `AWallSegmentActor`.

1. Create an Actor Blueprint at the same path and name.
2. Add a **Dynamic Mesh Component**, make it the root, and enable
   **Run Construction Script on Drag** in Class Settings.
3. Add instance-editable variables:
   - `Start`: Vector2D, default `(-100, 0)`
   - `End`: Vector2D, default `(100, 0)`
   - `Thickness`: Float, default `15`
   - `Height`: Float, default `300`
   - `GenerateCollision`: Boolean, default true
4. In the Construction Script:
   - `Delta = End - Start`
   - `Length = Vector2D Length(Delta)`
   - `Midpoint = (Start + End) * 0.5`
   - `Yaw = Radians To Degrees(Atan2(Delta.Y, Delta.X))`
   - Call **Get Dynamic Mesh** on the root component.
   - Call **Reset Dynamic Mesh**.
   - Call Geometry Script **Append Box** with:
     - Dimensions `(Length, Thickness, Height)`
     - Transform translation `(Midpoint.X, Midpoint.Y, Height * 0.5)`
     - Transform rotation `(Pitch=0, Yaw=Yaw, Roll=0)`
     - Primitive origin **Center**
   - When `GenerateCollision` is true, configure the Dynamic Mesh Component
     for complex-as-simple collision and notify collision data changed.
5. Guard against `Length <= 0.01`, `Thickness <= 0`, or `Height <= 0`.

The Python code supports either version because it writes the same property
names. The native-backed version is recommended and tested by the project.

## Review and correct walls: the Wall Correction window

Run **Tools > Floor Plan > Floor Plan Import**, choose the source, and press
**Detect Editable Walls**. When detection succeeds the panel imports the plan
image into the project as `/Game/FloorPlan/Sources/T_<name>` (PNG/JPG only),
logs `Opening wall correction UI...`, and opens the separate **Wall
Correction** window. You can reopen it any time from **Tools > Floor Plan >
Wall Correction...** or the **Open Wall Correction** button; it remembers the
last plan and scale across editor restarts.

The window is a 2D view of the plan with the staged walls drawn over it at
true scale (blue = detected, green = added, orange = selected), a list of
those walls on the right, and a toolbar:

- **Select** mode: click a wall on the plan to select it; the list follows.
  Press **Delete** (or **Remove Selected**) to delete it. Use this for false
  positives such as furniture, text, dimension lines, or door arcs. The log
  records `User removed wall #N`.
- **Draw** mode: drag on the plan to add a wall the detector missed. With
  **Snap** on, the wall stays horizontal or vertical and its ends join onto
  nearby wall ends. Walls shorter than 10 cm are ignored. The log records
  `User added wall #N ... by drawing it`.
- **Add Wall** drops a 2 m wall in the middle of the view for you to fix up.
- **Fit** (or **F**) zooms to the whole plan. Right- or middle-drag pans, the
  mouse wheel zooms about the cursor, **Escape** cancels a drag or clears the
  selection.
- Each list row has **3D**, which selects the wall's actor and frames that
  wall in the level viewport, and **Remove**.
- **Refresh** re-reads the walls after editing the actor in Details.
- **Finalize** locks the result in (see below).

Every edit is applied immediately to the single `FloorPlan_Walls` actor;
nothing is re-detected or re-imported. Vector sources (PDF paths, DXF, DWG)
have no raster, so the window shows the wall lines on a plain background and
drawing still works.

Scale comes from **Pixels per foot**: the image is placed so that image pixel
`(x, y)` sits at world `(x * cm/px, (height - y) * cm/px)`, the same mapping
the detector used, so drawn walls land exactly where they appear on the plan.

Every wall is still an ordinary actor, so the viewport tools keep working
alongside the list:

- Select and press **Delete** to remove a false positive.
- Use **W/E/R** for move, rotate, and scale.
- **Alt-drag** duplicates actors in Unreal's default keymap.
- Multi-select walls in `FloorPlan_Walls` to move or isolate the set.
- Edit Start, End, Thickness, and Height directly in Details for precise
  values.

Enable Unreal's viewport translation and rotation snap toggles before moving
walls. The importer does not bypass actor transforms, so the normal grid,
rotation, and scale snapping behavior applies without custom placement code.

For predictable JSON thickness, scale the actor uniformly or use the
`Thickness` property. The exporter supports non-uniform scaling, but direct
property editing is easier to reason about.

All corrections happen live on the actors. Nothing is re-detected or
re-imported.

### How corrections are tracked

In combined mode each `WallSegments` entry carries `SourceIndex`: the wall's
1-based position in the raw detection, or -1 for a wall added by hand.

In individual mode each wall actor carries tags in addition to
`FloorPlanEditableWall`:

- `FloorPlanOrigin:detected` or `FloorPlanOrigin:added`
- `FloorPlanIndex:NNN` — the wall's 1-based position in the raw detection

Either way the state lives in the level, so it survives Python reloads and
editor restarts, and Finalize can always compare the result against the raw
output. The correction calls (`list_walls`, `select_wall`, `remove_wall`,
`add_wall`, `finalize_walls`) detect which mode is staged and act
accordingly; `add_wall`'s `combined` argument only matters when the level has
no staged walls yet.

## Finalize

**Finalize** (panel button, or `floorplan_panel.finalize_walls()`):

1. Enables complex-as-simple collision on every remaining wall by rebuilding
   it with `Generate Collision` on. This is the native equivalent of Geometry
   Script's *Set Collision From Mesh*.
2. Reads each actor's current Start/End/Thickness, applies its full world
   transform, and derives world thickness from the transformed perpendicular
   axis, so moves, rotations, and scales are all reflected.
3. Compares the result with the raw detection and logs
   `Finalized: N walls, M corrections applied (R removed, A added, J adjusted)`.
   A detected wall counts as adjusted when its centreline or thickness moved
   by more than 0.5 cm.
4. Writes `<Project>/Saved/FloorPlan/walls_corrected.json`.

The raw detection is saved separately, once per run, to
`<Project>/Saved/FloorPlan/walls.json` and is never modified afterwards, so
you can always diff what the detector produced against what you finalized.
Both files use the same schema:

```json
[
  {
    "start": [0.0, 0.0],
    "end": [300.0, 0.0],
    "thickness": 15.0
  }
]
```

To export to a different path, or to export without touching collision:

```python
import floorplan_panel
floorplan_panel.finalize_walls(r"D:\Exports\walls_corrected.json")
floorplan_panel.export_corrected_walls()   # write only, no collision pass
```

## Python API used by the UI

These live in `Content/Python/floorplan_panel.py` and are safe to call from
the Python console, Blueprints, or an Editor Utility Widget:

| Function | Purpose |
| --- | --- |
| `list_walls()` | List of `{id, label, origin, index, summary, start, end, thickness, mode}` for every staged wall. `id` is the `WallSegments` index in combined mode or the actor path name in individual mode; pass it (or the `Wall_NNN` label) to the calls below. |
| `select_wall(id)` | Select the actor and frame it in the active viewport. Returns 1/0. |
| `remove_wall(id)` | Delete the actor and log `User removed wall #N`. Returns 1/0. |
| `add_wall(length_cm, thickness_cm, height_cm, generate_collision, combined=True)` | Add a wall at the viewport focus (a new `WallSegments` entry, or a new actor) and log `User added wall #N`. Returns 1/0. |
| `add_wall_at(x1, y1, x2, y2, thickness_cm, height_cm, generate_collision, combined=True)` | Add a wall between two world points (cm), as drawn in the Wall Correction window. Returns the new wall id or "". |
| `import_floorplan_texture_payload(image_path)` | Import a PNG/JPG as `/Game/FloorPlan/Sources/T_<name>`. Base64 JSON `{asset_path, width, height}` or "" for vector sources. |
| `finalize_walls(output_path="")` | Collision + `walls_corrected.json` + summary log. Returns base64 JSON of `{final, detected, removed, added, adjusted, corrections, path}`. |
| `open_correction_ui()` | Opens `EUW_WallCorrection` if that asset exists; returns 0 when the native panel should be used instead. |

## Optional: EUW_WallCorrection Editor Utility Widget

Build this only if you want a UMG version of the correction list, for
example to embed it in a larger tool. Save it as
`/Game/FloorPlan/UI/EUW_WallCorrection`; when that asset exists the import
pipeline opens it automatically after spawning walls (from the Tools menu or
`import_floor_plan()`), in addition to the native panel refreshing itself.

### Layout (Designer)

1. Content Browser: **Editor Utilities > Editor Utility Widget**, name it
   `EUW_WallCorrection`, save it under `/Game/FloorPlan/UI`.
2. Root: **Vertical Box**.
3. Row 1: **Text Block** named `SummaryText` (bind it to a `Summary` text
   variable).
4. Row 2: **Scroll Box** named `WallList`, set to fill the remaining height.
5. Row 3: **Horizontal Box** with three Buttons: **Add Wall**, **Refresh**,
   **Finalize**.
6. Create a second widget `EUW_WallRow` (also an Editor Utility Widget) with a
   Horizontal Box containing a Text Block `RowText` and two Buttons
   **Select in Viewport** and **Remove**. Give it two variables:
   `WallId` (String) and `Label` (String), both *Instance Editable* and
   *Expose on Spawn*.

### Graph

Every action is one **Execute Python Command** node (Python Script Plugin)
whose result is read back as text. Build the row list like this:

- **Refresh** (also called from *Event Construct*):
  1. `Clear Children` on `WallList`.
  2. Execute Python:
     `import json, floorplan_panel; print(json.dumps(floorplan_panel.list_walls()))`
     and parse the printed JSON with the Json Blueprint Utilities plugin, or
     simpler, call it once per row using
     `print(len(floorplan_panel.list_walls()))` to get the count and then
     `print(floorplan_panel.list_walls()[i]["id"] + "|" + floorplan_panel.list_walls()[i]["label"] + "|" + floorplan_panel.list_walls()[i]["summary"])`
     inside a For Loop, splitting on `|`.
  3. For each wall, `Create Widget` (class `EUW_WallRow`), set `WallId`,
     `Label`, and `RowText` to `Label + "  " + Summary`, then `Add Child` to
     `WallList`.
  4. Set `Summary` to `"{count} walls detected"`.
- **EUW_WallRow > Select in Viewport > On Clicked**:
  `import floorplan_panel; floorplan_panel.select_wall("{WallId}")`
  (build the string with *Format Text* so the id is inserted).
- **EUW_WallRow > Remove > On Clicked**:
  `import floorplan_panel; floorplan_panel.remove_wall("{WallId}")`, then
  `Remove From Parent` on the row and tell the parent to refresh its summary
  (an Event Dispatcher on the row is the tidy way).
- **Add Wall > On Clicked**:
  `import floorplan_panel; floorplan_panel.add_wall()`, then Refresh.
- **Finalize > On Clicked**:
  `import floorplan_panel; floorplan_panel.finalize_walls()`. The summary
  line is written to the Output Log by Python; if you want it in the widget,
  use `import base64, json, floorplan_panel; print(json.loads(base64.b64decode(floorplan_panel.finalize_walls()))["corrections"])`
  and read the printed value.

Compile and save. Right-click the asset and choose **Run Editor Utility
Widget** to test it; afterwards the pipeline will open it for you.

## Console log messages

The pipeline prints these as it goes so a run can be audited from the Output
Log or the panel's log view:

- `Opening wall correction UI...`
- `User removed wall #N (Wall_NNN).`
- `User added wall #N (Wall_NNN) at the viewport focus plane. ...`
- `Finalized: N walls, M corrections applied (R removed, A added, J adjusted). Wrote <path>`
