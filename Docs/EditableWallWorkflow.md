# Editable wall correction workflow

The importer now creates one actor per detected wall instead of immediately
baking every wall into one combined mesh. Each actor is placed in the
`FloorPlan_Walls` World Outliner folder and tagged `FloorPlanEditableWall`.

## Recommended BP_WallSegment setup

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

## Correcting walls in the viewport

Run **Tools > Floor Plan > Floor Plan Import**, choose the source, and press
**Detect Editable Walls**.

Each result is a standard independently selectable actor:

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

## Add Wall Editor Utility Widget

1. In the Content Browser choose **Editor Utilities > Editor Utility Widget**.
2. Name it `EUW_FloorPlanWallTools`.
3. In Designer, add a Vertical Box and a Button containing text **Add Wall**.
4. In Graph, bind the Button's **On Clicked** event.
5. Add the Python Script Plugin node **Execute Python Command** with:

   `import floorplan_panel; floorplan_panel.add_wall()`

6. Optionally add a second button named **Export walls.json**, using:

   `import floorplan_panel; floorplan_panel.export_corrected_walls()`

7. Compile, save, right-click the widget asset, and choose **Run Editor
   Utility Widget**.

Add Wall projects the active viewport camera onto the Z=0 floor plane. If
camera information is unavailable, it uses world origin. The new 200 cm wall
is selected automatically, placed in `FloorPlan_Walls`, and can immediately
be corrected with normal snapped viewport transforms.

## Export corrected geometry

The default export command is:

```python
import floorplan_panel
floorplan_panel.export_corrected_walls()
```

It writes:

`<Project>/Saved/FloorPlan/walls.json`

To choose a path:

```python
import floorplan_panel
floorplan_panel.export_corrected_walls(r"D:\Exports\walls.json")
```

The exporter reads every tagged editable wall actor, applies its complete
world transform to local Start/End, derives world thickness from its
transformed perpendicular axis, skips zero-length walls, and writes:

```json
[
  {
    "start": [0.0, 0.0],
    "end": [300.0, 0.0],
    "thickness": 15.0
  }
]
```

This means native move, rotate, scale, delete, and duplicate corrections are
all represented in the exported centerline list.
