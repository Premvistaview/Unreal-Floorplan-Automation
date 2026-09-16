"""Blender importer for scene.json (buildings + trees).

Run it one of three ways:

  1. Blender UI: Scripting workspace -> Open -> this file -> Run Script.

  2. Command line, with a UI:
       blender --python import_scene.py -- "D:/path/to/scene.json"

  3. Headless:
       blender -b -P import_scene.py -- "D:/path/to/scene.json"

Finding scene.json
------------------
The path is resolved in this order, and the first hit wins:

  1. a path given after '--' on the command line
  2. the JSON_PATH setting below, if you fill it in
  3. the path remembered from the last successful run
  4. auto-detection: scene.json beside this script, beside the open .blend,
     in the current working directory, or in a BlenderScene sub-folder or
     parent of any of those

Because step 3 writes the path to a small file in your Blender user config,
you are only ever asked once. If you pasted this script into an unsaved
text block, Blender cannot tell the script where it lives, so auto-detection
has less to work with; saving the .blend in your project, or setting
JSON_PATH, fixes that for good.

Requires Blender 2.80 or newer (it uses collections).

JSON contract
-------------
buildings[]  name      unique object name
             location  cube CENTRE in metres, [x, y, z]
             size      full extents, [width(X), depth(Y), height(Z)]
             rotation  degrees, [x, y, z], applied about the centre
             color     [r, g, b, a] in 0-1
             roof      false, or true plus roof_height and roof_color;
                       a gable roof is added on top of the cube, ridge
                       running along X
trees[]      name, location [x, y, z] (trunk base), trunk_height,
             trunk_radius, leaves_radius, trunk_color, leaves_color

Note: this script never calls sys.exit(). SystemExit is not caught by
Blender's script runner and would shut the whole application down, which
looks like a crash. Problems raise SceneImportError instead and are
reported in the console.
"""

import json
import math
import os
import sys
import tempfile

import bpy
import bmesh
from mathutils import Euler, Vector


# ------------------------------------------------------------------ config ---
# Pinned to an absolute path so the script never has to search. Set this back
# to "" to re-enable auto-detection (needed if the project folder ever moves).
JSON_PATH = r"D:/Game Project/Floor2Dto3Dplan/BlenderScene/scene.json"
JSON_NAME = "scene.json"  # filename looked for during auto-detection
PROJECT_SUBDIR = "BlenderScene"   # also checked as a sub-folder of each root
ROOT_COLLECTION = "GeneratedScene"
CLEAR_EXISTING = True    # wipe a previous import of this scene before rebuilding
GROUP_BY_PREFIX = True   # sort the cubes into sub-collections in the Outliner
SHADE_ROUGHNESS = 0.65
TRUNK_SEGMENTS = 12
CANOPY_SUBDIVISIONS = 2

# Cubes are filed into these sub-collections by name prefix, first match wins.
GROUP_PREFIXES = (
    "Tower_A", "Tower_B", "Tower_C", "Tower_D",
    "Shop", "Fence", "Gate", "Banner", "Hoarding", "Barricade",
    "Street_Lamp", "Power", "Utility", "Guard",
    "Rebar", "Pipe", "Cement",
    "Road", "Footpath", "Far_Verge", "Yard",
)

# Datablocks this script owns, so a re-import can clean up after itself.
OWNED_PREFIXES = ("SceneMat_", "SceneCube_", "SceneRoof_", "SceneTree_")


class SceneImportError(Exception):
    """Raised for anything the user needs to fix (bad path, bad JSON)."""


# ------------------------------------------------------------------- paths ---
def script_dir():
    """Folder holding this script, or None if it cannot be determined.

    __file__ is unset when the script is pasted into an unsaved text block
    in Blender's Text Editor, so fall back to the text datablock's filepath.
    """
    path = globals().get("__file__")
    if path:
        return os.path.dirname(os.path.abspath(path))
    for area_text in (getattr(getattr(bpy.context, "space_data", None),
                              "text", None),):
        if area_text is not None and area_text.filepath:
            return os.path.dirname(bpy.path.abspath(area_text.filepath))
    for text in bpy.data.texts:
        if text.filepath and text.name.startswith("import_scene"):
            return os.path.dirname(bpy.path.abspath(text.filepath))
    return None


def _dedupe_paths(paths):
    seen, out = set(), []
    for p in paths:
        if not p:
            continue
        full = os.path.abspath(p)
        key = os.path.normcase(full)
        if key not in seen:
            seen.add(key)
            out.append(full)
    return out


def search_dirs():
    """Everywhere worth looking for scene.json, best guess first."""
    roots = [script_dir()]
    if bpy.data.filepath:                       # folder of the open .blend
        roots.append(os.path.dirname(bpy.path.abspath(bpy.data.filepath)))
    roots.append(os.getcwd())

    dirs = list(roots)
    for root in roots:
        if not root:
            continue
        dirs.append(os.path.join(root, PROJECT_SUBDIR))
        parent = os.path.dirname(root)
        dirs.append(parent)
        dirs.append(os.path.join(parent, PROJECT_SUBDIR))
    return _dedupe_paths(dirs)


def config_file():
    """Per-user file used to remember the last JSON that loaded cleanly."""
    try:
        base = bpy.utils.user_resource("CONFIG", path="floor2dto3d",
                                       create=True)
        if base:
            return os.path.join(base, "import_scene.json")
    except (AttributeError, TypeError, OSError):
        pass
    return os.path.join(tempfile.gettempdir(), "floor2dto3d_import_scene.json")


def remembered_path():
    try:
        with open(config_file(), encoding="utf-8") as fh:
            value = json.load(fh).get("json_path")
    except (OSError, ValueError):
        return None
    return value if value and os.path.isfile(value) else None


def remember_path(path):
    """Store the path so later runs never have to ask again."""
    target = config_file()
    try:
        # Do not rely on user_resource(create=True) having made the folder.
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            json.dump({"json_path": path}, fh, indent=2)
    except OSError:
        pass    # convenience only, never fatal


def resolve_json_path():
    """Return (path, how_it_was_found). Path is None if nothing was found,
    in which case the second value lists every location tried."""
    # Only treat argv as ours when Blender was given an explicit '--'.
    if "--" in sys.argv:
        extras = [a for a in sys.argv[sys.argv.index("--") + 1:] if a.strip()]
        if extras:
            return os.path.abspath(extras[0]), "command line"

    if JSON_PATH:
        path = bpy.path.abspath(JSON_PATH)
        if not os.path.isabs(path):
            path = os.path.join(script_dir() or os.getcwd(), path)
        return os.path.abspath(path), "JSON_PATH setting"

    remembered = remembered_path()
    if remembered:
        return remembered, "remembered from last successful run"

    tried = []
    for folder in search_dirs():
        candidate = os.path.join(folder, JSON_NAME)
        tried.append(candidate)
        if os.path.isfile(candidate):
            return candidate, "found next to %s" % folder
    return None, tried


# ------------------------------------------------------------- collections ---
def purge_orphans():
    """Drop unused meshes/materials left by an earlier run of this script."""
    for store in (bpy.data.meshes, bpy.data.materials):
        for item in list(store):
            if item.name.startswith(OWNED_PREFIXES) and item.users == 0:
                store.remove(item)


def purge_collection(name):
    coll = bpy.data.collections.get(name)
    if coll is None:
        return
    for child in list(coll.children):
        purge_collection(child.name)
    for obj in list(coll.objects):
        mesh = obj.data if obj.type == "MESH" else None
        bpy.data.objects.remove(obj, do_unlink=True)
        # Shared meshes only reach zero users once their last object is gone.
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    bpy.data.collections.remove(coll)


def make_collection(name, parent):
    coll = bpy.data.collections.new(name)
    parent.children.link(coll)
    return coll


def group_name(obj_name):
    for prefix in GROUP_PREFIXES:
        if obj_name.startswith(prefix):
            return prefix
    return "Misc"


# ---------------------------------------------------------------- material ---
# These caches hold references to Blender datablocks. They must be cleared at
# the start of every run: a stale reference to a datablock that purge_orphans
# has already freed is a use-after-free and hard-crashes Blender.
_materials = {}
_cube_meshes = {}


def reset_caches():
    _materials.clear()
    _cube_meshes.clear()


def get_material(rgba, name_hint):
    r, g, b, a = (list(rgba) + [1.0, 1.0, 1.0, 1.0])[:4]
    key = (round(r, 4), round(g, 4), round(b, 4), round(a, 4))
    mat = _materials.get(key)
    if mat is not None:
        return mat

    mat = bpy.data.materials.new("SceneMat_%s" % name_hint)
    # Blender 5.0+ builds the node tree on creation and deprecated use_nodes
    # (removal planned in 6.0), so only touch it on older versions that need it.
    if getattr(mat, "node_tree", None) is None and hasattr(mat, "use_nodes"):
        mat.use_nodes = True
    node_tree = getattr(mat, "node_tree", None)
    bsdf = None
    if node_tree is not None:
        bsdf = next((n for n in node_tree.nodes
                     if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (r, g, b, a)
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = SHADE_ROUGHNESS
        if a < 1.0 and "Alpha" in bsdf.inputs:
            bsdf.inputs["Alpha"].default_value = a
    mat.diffuse_color = (r, g, b, a)   # solid-mode viewport colour
    if a < 1.0:
        # Blender 4.2 replaced blend_method with surface_render_method.
        if hasattr(mat, "surface_render_method"):
            mat.surface_render_method = "BLENDED"
        elif hasattr(mat, "blend_method"):
            mat.blend_method = "BLEND"

    _materials[key] = mat
    return mat


# ------------------------------------------------------------------ meshes ---
CUBE_VERTS = [
    (-0.5, -0.5, -0.5), (0.5, -0.5, -0.5), (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5),
    (-0.5, -0.5, 0.5), (0.5, -0.5, 0.5), (0.5, 0.5, 0.5), (-0.5, 0.5, 0.5),
]
CUBE_FACES = [
    (0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
    (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
]


def build_mesh(name, verts, faces, material):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.validate()
    mesh.update()
    mesh.materials.append(material)
    return mesh


def unit_cube_mesh(material):
    """One shared 1x1x1 mesh per material; objects are scaled to their size.

    Because the mesh is shared, editing one cube's geometry in Edit Mode
    changes every cube that uses the same colour.
    """
    mesh = _cube_meshes.get(material.name)
    if mesh is None:
        mesh = build_mesh("SceneCube_%s" % material.name,
                          CUBE_VERTS, CUBE_FACES, material)
        _cube_meshes[material.name] = mesh
    return mesh


def gable_roof_mesh(name, width, depth, height, material):
    """Triangular prism, base at local z = 0, ridge running along X."""
    hw, hd = width / 2.0, depth / 2.0
    verts = [(-hw, -hd, 0.0), (hw, -hd, 0.0), (hw, hd, 0.0), (-hw, hd, 0.0),
             (-hw, 0.0, height), (hw, 0.0, height)]
    faces = [(0, 3, 2, 1), (0, 1, 5, 4), (2, 3, 4, 5), (0, 4, 3), (1, 2, 5)]
    return build_mesh("SceneRoof_%s" % name, verts, faces, material)


def _bmesh_to_mesh(bm, name, material, smooth=False):
    if smooth:
        for face in bm.faces:
            face.smooth = True
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    mesh.materials.append(material)
    return mesh


def cylinder_mesh(name, radius, depth, material):
    """Trunk mesh, origin at its centre. Built with bmesh so it needs no
    operator context (bpy.ops.mesh.primitive_* fails in background mode)."""
    bm = bmesh.new()
    kwargs = dict(cap_ends=True, cap_tris=False, segments=TRUNK_SEGMENTS,
                  depth=depth)
    try:
        bmesh.ops.create_cone(bm, radius1=radius, radius2=radius, **kwargs)
    except TypeError:
        # Blender < 3.0 spelled these diameter1/diameter2.
        bmesh.ops.create_cone(bm, diameter1=radius * 2.0,
                              diameter2=radius * 2.0, **kwargs)
    return _bmesh_to_mesh(bm, name, material)


def icosphere_mesh(name, radius, material):
    bm = bmesh.new()
    try:
        bmesh.ops.create_icosphere(bm, subdivisions=CANOPY_SUBDIVISIONS,
                                   radius=radius)
    except TypeError:
        bmesh.ops.create_icosphere(bm, subdivisions=CANOPY_SUBDIVISIONS,
                                   diameter=radius * 2.0)
    return _bmesh_to_mesh(bm, name, material, smooth=True)


# ------------------------------------------------------------------ builder ---
def as_vec3(value, default=(0.0, 0.0, 0.0)):
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            return tuple(float(v) for v in value[:3])
        except (TypeError, ValueError):
            pass
    return default


def as_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_building(entry, index, collections, buildings_coll, warnings):
    name = entry.get("name") or "Building_%04d" % index
    location = as_vec3(entry.get("location"))
    size = as_vec3(entry.get("size"), (1.0, 1.0, 1.0))
    rotation = as_vec3(entry.get("rotation"))

    if min(size) <= 0.0:
        warnings.append("%s: non-positive size %s, skipped" % (name, list(size)))
        return 0

    euler = Euler([math.radians(a) for a in rotation], "XYZ")
    material = get_material(entry.get("color") or [0.8, 0.8, 0.8, 1.0], name)

    obj = bpy.data.objects.new(name, unit_cube_mesh(material))
    obj.location = location
    obj.scale = size
    obj.rotation_euler = euler

    target = buildings_coll
    if GROUP_BY_PREFIX:
        key = group_name(name)
        if key not in collections:
            collections[key] = make_collection(key, buildings_coll)
        target = collections[key]
    target.objects.link(obj)
    created = 1

    if entry.get("roof"):
        roof_height = as_float(entry.get("roof_height"), 0.5)
        if roof_height <= 0.0:
            warnings.append("%s: roof_height %r ignored"
                            % (name, entry.get("roof_height")))
        else:
            roof_mat = get_material(
                entry.get("roof_color") or entry.get("color")
                or [0.5, 0.3, 0.2, 1.0], name + "_Roof")
            roof = bpy.data.objects.new(
                name + "_Roof",
                gable_roof_mesh(name, size[0], size[1], roof_height, roof_mat))
            # Sit the roof on the cube's top face, respecting any rotation.
            offset = Vector((0.0, 0.0, size[2] / 2.0))
            offset.rotate(euler)
            roof.location = Vector(location) + offset
            roof.rotation_euler = euler
            target.objects.link(roof)
            created += 1

    return created


def build_tree(entry, index, trees_coll, warnings):
    name = entry.get("name") or "Tree_%03d" % index
    x, y, z = as_vec3(entry.get("location"))
    trunk_h = as_float(entry.get("trunk_height"), 4.0)
    trunk_r = as_float(entry.get("trunk_radius"), 0.18)
    leaf_r = as_float(entry.get("leaves_radius"), 1.6)

    if min(trunk_h, trunk_r, leaf_r) <= 0.0:
        warnings.append("%s: non-positive tree dimension, skipped" % name)
        return 0

    trunk_mat = get_material(entry.get("trunk_color") or [0.40, 0.33, 0.24, 1.0],
                             name + "_Trunk")
    leaf_mat = get_material(entry.get("leaves_color") or [0.20, 0.40, 0.20, 1.0],
                            name + "_Leaves")

    trunk = bpy.data.objects.new(
        name + "_Trunk",
        cylinder_mesh("SceneTree_%s_Trunk" % name, trunk_r, trunk_h, trunk_mat))
    trunk.location = (x, y, z + trunk_h / 2.0)

    canopy = bpy.data.objects.new(
        name + "_Canopy",
        icosphere_mesh("SceneTree_%s_Canopy" % name, leaf_r, leaf_mat))
    canopy.location = (x, y, z + trunk_h)

    trees_coll.objects.link(trunk)
    trees_coll.objects.link(canopy)
    return 2


# --------------------------------------------------------------------- main ---
def load_scene(path):
    if not os.path.isfile(path):
        raise SceneImportError(
            "scene JSON not found:\n  %s\n"
            "Set JSON_PATH at the top of this script, or pass the path after "
            "'--' on the command line." % path)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, UnicodeDecodeError) as exc:
        raise SceneImportError("could not read %s: %s" % (path, exc))
    except json.JSONDecodeError as exc:
        raise SceneImportError("%s is not valid JSON: %s" % (path, exc))

    if not isinstance(data, dict):
        raise SceneImportError(
            "expected a JSON object with 'buildings' and 'trees' arrays, "
            "got %s" % type(data).__name__)
    buildings = data.get("buildings") or []
    trees = data.get("trees") or []
    if not isinstance(buildings, list) or not isinstance(trees, list):
        raise SceneImportError("'buildings' and 'trees' must both be arrays")
    return buildings, trees


def run():
    if bpy.app.version < (2, 80):
        raise SceneImportError(
            "this script needs Blender 2.80 or newer (found %d.%d.%d); "
            "collections do not exist in earlier versions" % bpy.app.version)

    path, source = resolve_json_path()
    if path is None:
        raise SceneImportError(
            "could not find %s anywhere. Looked in:\n  %s\n\n"
            "To fix it permanently, set JSON_PATH near the top of this "
            "script to the full path, for example:\n"
            "  JSON_PATH = r\"D:/Game Project/Floor2Dto3Dplan/BlenderScene/"
            "%s\"" % (JSON_NAME, "\n  ".join(source), JSON_NAME))

    buildings, trees = load_scene(path)
    remember_path(path)     # so the next run finds it without being told

    reset_caches()
    if CLEAR_EXISTING:
        purge_collection(ROOT_COLLECTION)
        purge_orphans()

    root = make_collection(ROOT_COLLECTION, bpy.context.scene.collection)
    buildings_coll = make_collection("Buildings", root)
    trees_coll = make_collection("Trees", root)

    warnings = []
    groups = {}
    n_cubes = 0
    for i, entry in enumerate(buildings):
        if isinstance(entry, dict):
            n_cubes += build_building(entry, i, groups, buildings_coll, warnings)
        else:
            warnings.append("buildings[%d] is not an object, skipped" % i)

    n_trees = 0
    for i, entry in enumerate(trees):
        if isinstance(entry, dict):
            n_trees += build_tree(entry, i, trees_coll, warnings)
        else:
            warnings.append("trees[%d] is not an object, skipped" % i)

    print("-" * 60)
    print("imported      : %s" % path)
    print("located via   : %s" % source)
    print("building defs : %d  ->  %d objects" % (len(buildings), n_cubes))
    print("tree defs     : %d  ->  %d objects" % (len(trees), n_trees))
    print("materials     : %d" % len(_materials))
    print("collections   : %s" % (", ".join(sorted(groups)) or "(flat)"))
    if warnings:
        print("warnings      : %d" % len(warnings))
        for w in warnings[:20]:
            print("  - %s" % w)
    print("-" * 60)


def main():
    try:
        run()
    except SceneImportError as exc:
        print("=" * 60)
        print("scene import failed:")
        print(exc)
        print("=" * 60)


main()
