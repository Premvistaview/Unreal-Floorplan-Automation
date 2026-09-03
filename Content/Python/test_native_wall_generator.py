"""Headless/editor smoke test for AWallGeneratorActor."""

import unreal


def run() -> None:
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actor = subsystem.spawn_actor_from_class(
        unreal.WallGeneratorActor,
        unreal.Vector(0.0, 0.0, 0.0),
        unreal.Rotator(0.0, 0.0, 0.0),
    )
    if not actor:
        raise RuntimeError("Could not spawn WallGeneratorActor")

    try:
        segments = []
        for start, end, thickness in (
            ((0.0, 0.0), (400.0, 0.0), 15.0),
            ((400.0, 0.0), (400.0, 300.0), 20.0),
        ):
            segment = unreal.WallSegment()
            segment.set_editor_property("start", unreal.Vector2D(*start))
            segment.set_editor_property("end", unreal.Vector2D(*end))
            segment.set_editor_property("thickness", thickness)
            segments.append(segment)

        if not actor.generate_walls(segments, 300.0, True):
            raise RuntimeError("GenerateWalls returned false")

        component = actor.get_editor_property("dynamic_mesh_component")
        triangle_count = component.get_dynamic_mesh().get_triangle_count()
        generated_count = actor.get_editor_property("generated_wall_count")

        if generated_count != 2 or triangle_count != 24:
            raise RuntimeError(
                f"Expected 2 walls / 24 triangles, got "
                f"{generated_count} walls / {triangle_count} triangles"
            )

        unreal.log("WALL_GENERATOR_TEST_PASS: 2 walls, 24 triangles, collision requested")
    finally:
        subsystem.destroy_actor(actor)


run()
