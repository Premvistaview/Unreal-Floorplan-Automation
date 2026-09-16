"""Generates scene.json for the Blender cube-based scene importer.

Scene: an Indian arterial-road frontage. A steel & cement trader's yard sits
behind a black palisade fence with a banner stretched across the entrance;
a mustard two-storey shop with RAMCO boards stands on the left; four grey /
off-white apartment towers rise behind the yard; a billboard hoarding on a
single pole stands across the road.

Importer conventions assumed:
  location = cube centre, size = full [X, Y, Z] extents, rotation in degrees,
  color = RGBA 0-1. Ground plane is z = 0, X is width, Y is depth, Z is up.

Everything faces -Y (the road). Each block declares the y of its front
facade; the body extends toward +Y and facade details protrude into -Y so no
detail face is coplanar with the mass it sits on.
"""

import json
import os

BUILDINGS = []
TREES = []

# ---------------------------------------------------------------- palette ----
TOWER_LIGHT = [0.878, 0.878, 0.859, 1.0]
TOWER_GREY = [0.706, 0.714, 0.706, 1.0]
PANEL_DARK = [0.400, 0.408, 0.404, 1.0]
PANEL_LIGHT = [0.910, 0.906, 0.882, 1.0]
ACCENT_GREY = [0.545, 0.553, 0.545, 1.0]
TRIM = [0.941, 0.937, 0.914, 1.0]
GLASS_DARK = [0.153, 0.180, 0.196, 1.0]
GLASS = [0.239, 0.290, 0.325, 1.0]
METAL_DARK = [0.098, 0.102, 0.106, 1.0]
STEEL = [0.478, 0.494, 0.510, 1.0]
LAMP_GREY = [0.596, 0.612, 0.627, 1.0]
CONCRETE = [0.741, 0.729, 0.694, 1.0]
BANNER_RED = [0.741, 0.114, 0.114, 1.0]
BANNER_YELLOW = [0.949, 0.808, 0.102, 1.0]
RAMCO_BLUE = [0.098, 0.278, 0.588, 1.0]
SHOP_YELLOW = [0.898, 0.706, 0.180, 1.0]
BOARD_FACE = [0.851, 0.867, 0.878, 1.0]
BLUE_SHEET = [0.196, 0.365, 0.639, 1.0]
ASPHALT = [0.212, 0.212, 0.220, 1.0]
DIRT = [0.678, 0.612, 0.494, 1.0]
TANK_BLACK = [0.129, 0.133, 0.145, 1.0]


def _r(values):
    return [round(float(v), 3) for v in values]


def add(name, centre, size, color, rotation=(0.0, 0.0, 0.0),
        roof=False, roof_height=0.5, roof_color=None):
    item = {
        "name": name,
        "location": _r(centre),
        "size": _r(size),
        "rotation": _r(rotation),
        "color": _r(color),
        "roof": bool(roof),
    }
    if roof:
        item["roof_height"] = round(float(roof_height), 3)
        item["roof_color"] = _r(roof_color or CONCRETE)
    BUILDINGS.append(item)
    return item


def box(name, xr, yr, zr, color, rotation=(0.0, 0.0, 0.0), **kw):
    """Add a cube from min/max ranges instead of centre + size."""
    (x0, x1), (y0, y1), (z0, z1) = xr, yr, zr
    centre = ((x0 + x1) / 2.0, (y0 + y1) / 2.0, (z0 + z1) / 2.0)
    size = (x1 - x0, y1 - y0, z1 - z0)
    return add(name, centre, size, color, rotation, **kw)


def palm(name, x, y, trunk_height, canopy_radius, trunk_radius=0.16):
    TREES.append({
        "name": name,
        "location": _r((x, y, 0.0)),
        "trunk_height": round(float(trunk_height), 3),
        "trunk_radius": round(float(trunk_radius), 3),
        "leaves_radius": round(float(canopy_radius), 3),
        "trunk_color": [0.400, 0.325, 0.243, 1.0],
        "leaves_color": [0.204, 0.400, 0.196, 1.0],
    })


# ========================================================= facade details ===
def window(tag, cx, z0, fy, width=1.30, height=1.45, glass=GLASS_DARK):
    hw = width / 2.0
    box(tag + "_Frame", (cx - hw - 0.11, cx + hw + 0.11), (fy - 0.10, fy + 0.02),
        (z0 - 0.11, z0 + height + 0.11), TRIM)
    box(tag + "_Glass", (cx - hw, cx + hw), (fy - 0.17, fy - 0.09),
        (z0, z0 + height), glass)


def balcony(tag, cx, z0, fy, panel, width=3.20, depth=1.35, simple=False):
    """Cantilevered slab with a solid parapet, as on the reference towers."""
    hw = width / 2.0
    yo = fy - depth
    box(tag + "_Slab", (cx - hw, cx + hw), (yo, fy), (z0 - 0.20, z0), TRIM)
    box(tag + "_Parapet", (cx - hw, cx + hw), (yo, yo + 0.14),
        (z0, z0 + 1.05), panel)
    if not simple:
        box(tag + "_Parapet_Left", (cx - hw, cx - hw + 0.14), (yo, fy),
            (z0, z0 + 1.05), panel)
        box(tag + "_Parapet_Right", (cx + hw - 0.14, cx + hw), (yo, fy),
            (z0, z0 + 1.05), panel)
    box(tag + "_Coping", (cx - hw - 0.05, cx + hw + 0.05),
        (yo - 0.05, yo + 0.19), (z0 + 1.05, z0 + 1.14), TRIM)
    box(tag + "_Door_Glass", (cx - 1.00, cx + 1.00), (fy - 0.16, fy - 0.08),
        (z0 + 0.05, z0 + 2.20), GLASS)
    if not simple:
        box(tag + "_Door_Frame", (cx - 1.12, cx + 1.12), (fy - 0.08, fy + 0.02),
            (z0, z0 + 2.32), TRIM)


def bay_centres(x0, x1, bays):
    bay_w = (x1 - x0) / bays
    return [x0 + bay_w * (i + 0.5) for i in range(bays)]


def roof_kit(tag, x0, x1, fy, depth, height):
    """Parapet ring plus the lift overrun, stair box and water tanks."""
    by = fy + depth
    box(tag + "_Roof_Slab", (x0 - 0.30, x1 + 0.30), (fy - 0.30, by + 0.30),
        (height, height + 0.24), CONCRETE)
    box(tag + "_Parapet_Front", (x0 - 0.30, x1 + 0.30), (fy - 0.30, fy - 0.02),
        (height + 0.24, height + 1.05), TRIM)
    box(tag + "_Parapet_Back", (x0 - 0.30, x1 + 0.30), (by + 0.02, by + 0.30),
        (height + 0.24, height + 1.05), TRIM)
    box(tag + "_Parapet_Left", (x0 - 0.30, x0 - 0.02), (fy - 0.30, by + 0.30),
        (height + 0.24, height + 1.05), TRIM)
    box(tag + "_Parapet_Right", (x1 + 0.02, x1 + 0.30), (fy - 0.30, by + 0.30),
        (height + 0.24, height + 1.05), TRIM)

    mid = (x0 + x1) / 2.0
    zr = height + 0.24
    box(tag + "_Lift_Overrun", (mid - 2.20, mid + 0.60),
        (fy + depth * 0.45, fy + depth * 0.80), (zr, zr + 3.10), TOWER_GREY)
    box(tag + "_Stair_Head", (mid + 0.90, mid + 3.00),
        (fy + depth * 0.50, fy + depth * 0.78), (zr, zr + 2.40), TOWER_GREY)
    for k, off in enumerate((-0.30, 0.30)):
        tx = mid + off * (x1 - x0) * 0.5 - 0.75
        box("%s_Tank_Stand_%d" % (tag, k + 1), (tx, tx + 1.50),
            (fy + depth * 0.18, fy + depth * 0.34), (zr, zr + 1.20), STEEL)
        box("%s_Water_Tank_%d" % (tag, k + 1), (tx - 0.15, tx + 1.65),
            (fy + depth * 0.14, fy + depth * 0.38), (zr + 1.20, zr + 2.30),
            TANK_BLACK)


def tower(tag, x0, width, fy, depth, floors, floor_h, body, accent, bays,
          balcony_bays=(), pattern="uniform", simple_balcony=False):
    x1 = x0 + width
    height = floors * floor_h

    add(tag + "_Mass", (x0 + width / 2.0, fy + depth / 2.0, height / 2.0),
        (width, depth, height), body)

    # Slab-edge bands between floors.
    for f in range(1, floors):
        z = f * floor_h
        box("%s_Band_%d" % (tag, f), (x0 - 0.14, x1 + 0.14),
            (fy - 0.16, fy - 0.02), (z - 0.10, z + 0.10), TRIM)

    # Vertical facade accents: corner pilasters plus bay dividers.
    box(tag + "_Pilaster_Left", (x0 - 0.12, x0 + 0.62), (fy - 0.18, fy),
        (0.0, height), accent)
    box(tag + "_Pilaster_Right", (x1 - 0.62, x1 + 0.12), (fy - 0.18, fy),
        (0.0, height), accent)
    bay_w = width / bays
    for i in range(1, bays):
        x = x0 + bay_w * i
        box("%s_Accent_%d" % (tag, i), (x - 0.26, x + 0.26), (fy - 0.22, fy),
            (0.25, height - 0.25), accent)

    # Ground-floor plinth and recessed openings.
    box(tag + "_Plinth", (x0 - 0.16, x1 + 0.16), (fy - 0.20, fy),
        (0.0, 0.95), CONCRETE)
    centres = bay_centres(x0, x1, bays)
    for i, cx in enumerate(centres):
        box("%s_F0_B%d_Recess" % (tag, i), (cx - 1.60, cx + 1.60),
            (fy - 0.14, fy - 0.04), (1.05, 2.85), GLASS_DARK)

    # Upper floors.
    for f in range(1, floors):
        base = f * floor_h
        for i, cx in enumerate(centres):
            label = "%s_F%d_B%d" % (tag, f, i)
            if i in balcony_bays:
                if pattern == "checker":
                    panel = PANEL_DARK if (f + i) % 2 == 0 else PANEL_LIGHT
                elif pattern == "stack":
                    panel = PANEL_DARK if i % 2 == 0 else PANEL_LIGHT
                else:
                    panel = PANEL_LIGHT
                balcony(label + "_Balcony", cx, base + 0.32, fy, panel,
                        simple=simple_balcony)
            else:
                window(label + "_Win", cx, base + 1.05, fy)

    roof_kit(tag, x0, x1, fy, depth, height)
    return x1, height


# ================================================================ towers ====
# Left tower, partly hidden by the shop in the reference. Its front sits clear
# of the shop's rear wall so the balconies do not intersect the shop mass.
tower("Tower_A", -32.0, 14.0, 1.0, 12.0, 9, 3.05, TOWER_LIGHT, ACCENT_GREY,
      bays=4, balcony_bays=(1, 2), pattern="uniform")

# Tall central slab: dark vertical strips, balconies on the outer bays.
tower("Tower_B", -16.0, 16.0, 0.0, 13.0, 11, 3.05, TOWER_GREY, PANEL_DARK,
      bays=4, balcony_bays=(0, 3), pattern="stack")

# Narrow white tower set further back.
tower("Tower_C", 2.0, 12.0, 3.0, 11.0, 10, 3.05, TOWER_LIGHT, ACCENT_GREY,
      bays=3, balcony_bays=(1,), pattern="uniform")

# Right-hand tower with the grey/white chequerboard balcony pattern.
tower("Tower_D", 16.0, 15.0, -1.0, 12.0, 11, 3.05, TOWER_LIGHT, PANEL_DARK,
      bays=4, balcony_bays=(0, 1, 2, 3), pattern="checker",
      simple_balcony=True)

# ==================================== mustard shop with RAMCO signboards ====
SH_X0, SH_X1 = -30.0, -19.0
SH_FY, SH_BY = -8.5, -0.5
SH_H = 7.20
box("Shop_Mass", (SH_X0, SH_X1), (SH_FY, SH_BY), (0.0, SH_H), SHOP_YELLOW)
box("Shop_Ground_Facade", (SH_X0 - 0.12, SH_X1 + 0.12), (SH_FY - 0.14, SH_FY),
    (0.0, 3.45), TRIM)
box("Shop_Cornice", (SH_X0 - 0.25, SH_X1 + 0.25), (SH_FY - 0.28, SH_FY),
    (SH_H - 0.45, SH_H), TRIM)
box("Shop_Roof_Slab", (SH_X0 - 0.30, SH_X1 + 0.30), (SH_FY - 0.30, SH_BY + 0.30),
    (SH_H, SH_H + 0.22), CONCRETE)
box("Shop_Parapet_Front", (SH_X0 - 0.30, SH_X1 + 0.30), (SH_FY - 0.30, SH_FY),
    (SH_H + 0.22, SH_H + 0.80), TRIM)

# Rooftop water tank on a stilt frame, as in the reference.
box("Shop_Tank_Frame", (SH_X0 + 1.20, SH_X0 + 3.40), (SH_FY + 2.20, SH_FY + 4.00),
    (SH_H + 0.22, SH_H + 2.60), STEEL)
box("Shop_Water_Tank", (SH_X0 + 1.00, SH_X0 + 3.60), (SH_FY + 2.00, SH_FY + 4.20),
    (SH_H + 2.60, SH_H + 3.90), TANK_BLACK)

# Upper-floor windows, kept above the banner line so they stay visible.
for k, cx in enumerate((-27.6, -23.4, -20.6)):
    window("Shop_Upper_Win_%d" % (k + 1), cx, 5.45, SH_FY, 1.20, 1.20, GLASS)

# RAMCO SUPERGRADE boards, sitting in the gap between fence top and banner.
for k, (bx0, bx1) in enumerate(((-29.4, -24.6), (-23.9, -21.1))):
    tag = "Shop_Ramco_Board_%d" % (k + 1)
    box(tag, (bx0, bx1), (SH_FY - 0.30, SH_FY - 0.14), (2.30, 3.95), RAMCO_BLUE)
    box(tag + "_Face", (bx0 + 0.22, bx1 - 0.22), (SH_FY - 0.38, SH_FY - 0.30),
        (2.55, 3.70), TRIM)
    box(tag + "_Frame_Top", (bx0 - 0.08, bx1 + 0.08), (SH_FY - 0.34, SH_FY - 0.14),
        (3.95, 4.09), STEEL)

# Red trader nameplate below the boards.
box("Shop_Name_Strip", (-29.6, -20.4), (SH_FY - 0.32, SH_FY - 0.18),
    (1.50, 2.20), BANNER_RED)

# Shop front: glazing, mullion and doorway.
box("Shop_Front_Glazing", (-20.9, -19.3), (SH_FY - 0.20, SH_FY - 0.08),
    (0.20, 2.60), GLASS_DARK)
box("Shop_Front_Mullion", (-20.15, -20.03), (SH_FY - 0.26, SH_FY - 0.14),
    (0.20, 2.60), TRIM)
box("Shop_Door_Frame", (-24.5, -23.0), (SH_FY - 0.24, SH_FY - 0.12),
    (0.0, 2.45), TRIM)
box("Shop_Door_Leaf", (-24.36, -23.14), (SH_FY - 0.30, SH_FY - 0.24),
    (0.05, 2.30), METAL_DARK)

# =========================================== palisade fence along the road ==
FEN_Y = -14.0
GATE_X0, GATE_X1 = -4.0, 4.0
FEN_X0, FEN_X1 = -34.0, 32.0
FEN_H = 2.25

box("Fence_Kerb", (FEN_X0, FEN_X1), (FEN_Y - 0.22, FEN_Y + 0.22),
    (0.0, 0.20), CONCRETE)

for tag, sx0, sx1 in (("Fence_West", FEN_X0, GATE_X0),
                      ("Fence_East", GATE_X1, FEN_X1)):
    box(tag + "_Rail_Bottom", (sx0, sx1), (FEN_Y - 0.06, FEN_Y + 0.06),
        (0.28, 0.44), METAL_DARK)
    box(tag + "_Rail_Mid", (sx0, sx1), (FEN_Y - 0.06, FEN_Y + 0.06),
        (1.16, 1.28), METAL_DARK)
    box(tag + "_Rail_Top", (sx0, sx1), (FEN_Y - 0.06, FEN_Y + 0.06),
        (FEN_H - 0.16, FEN_H), METAL_DARK)
    n_bars = int((sx1 - sx0) / 0.90)
    step = (sx1 - sx0) / (n_bars + 1)
    for b in range(n_bars):
        bx = sx0 + step * (b + 1)
        box("%s_Bar_%02d" % (tag, b + 1), (bx - 0.035, bx + 0.035),
            (FEN_Y - 0.04, FEN_Y + 0.04), (0.20, FEN_H + 0.14), METAL_DARK)

fence_posts = [-33.0, -29.0, -25.0, -21.0, -17.0, -13.0, -9.0,
               9.0, 13.0, 17.0, 21.0, 25.0, 29.0, 31.5]
for i, px in enumerate(fence_posts):
    box("Fence_Post_%02d" % (i + 1), (px - 0.09, px + 0.09),
        (FEN_Y - 0.11, FEN_Y + 0.11), (0.0, FEN_H + 0.22), METAL_DARK)

# Concrete piers flanking the vehicle gate.
for side, gx in (("West", GATE_X0), ("East", GATE_X1)):
    sgn = -1.0 if side == "West" else 1.0
    cx = gx + sgn * 0.30
    box("Gate_Pier_%s" % side, (cx - 0.30, cx + 0.30),
        (FEN_Y - 0.32, FEN_Y + 0.32), (0.0, 2.90), CONCRETE)
    box("Gate_Pier_%s_Cap" % side, (cx - 0.40, cx + 0.40),
        (FEN_Y - 0.42, FEN_Y + 0.42), (2.90, 3.08), TRIM)

# Twin gate leaves, barred to match the fence.
for side, lx0, lx1 in (("West", GATE_X0, -0.06), ("East", 0.06, GATE_X1)):
    box("Gate_Leaf_%s_Rail_Bottom" % side, (lx0, lx1), (FEN_Y - 0.07, FEN_Y + 0.07),
        (0.22, 0.42), METAL_DARK)
    box("Gate_Leaf_%s_Rail_Top" % side, (lx0, lx1), (FEN_Y - 0.07, FEN_Y + 0.07),
        (1.95, 2.15), METAL_DARK)
    box("Gate_Leaf_%s_Stile_A" % side, (lx0, lx0 + 0.11), (FEN_Y - 0.07, FEN_Y + 0.07),
        (0.22, 2.15), METAL_DARK)
    box("Gate_Leaf_%s_Stile_B" % side, (lx1 - 0.11, lx1), (FEN_Y - 0.07, FEN_Y + 0.07),
        (0.22, 2.15), METAL_DARK)
    span = lx1 - lx0
    for b in range(9):
        bx = lx0 + span * (b + 1) / 10.0
        box("Gate_Leaf_%s_Bar_%d" % (side, b + 1), (bx - 0.035, bx + 0.035),
            (FEN_Y - 0.045, FEN_Y + 0.045), (0.30, 2.05), METAL_DARK)

# ===================================== banner stretched across the frontage =
BAN_Y = -15.10
box("Banner_Main", (-31.0, 30.0), (BAN_Y - 0.05, BAN_Y + 0.05), (4.05, 5.35),
    BANNER_RED)
box("Banner_Main_Hem_Top", (-31.0, 30.0), (BAN_Y - 0.09, BAN_Y + 0.01),
    (5.35, 5.47), BANNER_YELLOW)
box("Banner_Main_Hem_Bottom", (-31.0, 30.0), (BAN_Y - 0.09, BAN_Y + 0.01),
    (3.93, 4.05), BANNER_YELLOW)
box("Banner_Main_Divider", (10.4, 10.6), (BAN_Y - 0.09, BAN_Y + 0.01),
    (4.05, 5.35), BANNER_YELLOW)

# Secondary yellow banner hung slightly behind and above, as in the reference.
box("Banner_Secondary", (4.0, 31.5), (BAN_Y - 0.75, BAN_Y - 0.66),
    (5.85, 6.95), BANNER_YELLOW)
box("Banner_Secondary_Hem_Top", (4.0, 31.5), (BAN_Y - 0.79, BAN_Y - 0.70),
    (6.95, 7.05), BANNER_RED)
box("Banner_Secondary_Hem_Bottom", (4.0, 31.5), (BAN_Y - 0.79, BAN_Y - 0.70),
    (5.75, 5.85), BANNER_RED)

# Banner supports: a concrete post, a lattice mast and slim intermediate posts.
box("Banner_Post_Concrete", (-11.60, -11.00), (BAN_Y - 0.30, BAN_Y + 0.30),
    (0.0, 5.90), CONCRETE)
box("Banner_Post_Concrete_Collar", (-11.72, -10.88), (BAN_Y - 0.40, BAN_Y + 0.40),
    (5.90, 6.08), STEEL)

MAST_X = 12.60
box("Banner_Mast_Leg_West", (MAST_X - 0.55, MAST_X - 0.37),
    (BAN_Y - 0.30, BAN_Y - 0.12), (0.0, 7.40), STEEL)
box("Banner_Mast_Leg_East", (MAST_X + 0.37, MAST_X + 0.55),
    (BAN_Y - 0.30, BAN_Y - 0.12), (0.0, 7.40), STEEL)
for k in range(5):
    z = 0.90 + k * 1.45
    box("Banner_Mast_Brace_%d" % (k + 1), (MAST_X - 0.55, MAST_X + 0.55),
        (BAN_Y - 0.28, BAN_Y - 0.14), (z, z + 0.11), STEEL)
box("Banner_Mast_Cap", (MAST_X - 0.65, MAST_X + 0.65),
    (BAN_Y - 0.36, BAN_Y - 0.06), (7.40, 7.56), STEEL)

for k, px in enumerate((-27.0, -19.5, 2.0, 22.0, 29.4)):
    box("Banner_Support_Post_%d" % (k + 1), (px - 0.10, px + 0.10),
        (BAN_Y - 0.14, BAN_Y + 0.02), (0.0, 5.70), STEEL)

# Garland strips draped from the banner on the right-hand side.
for k, px in enumerate((15.5, 18.0, 20.5, 23.0, 25.5, 28.0)):
    box("Banner_Garland_%d" % (k + 1), (px - 0.16, px + 0.16),
        (BAN_Y - 0.16, BAN_Y - 0.06), (2.55, 4.05), BANNER_YELLOW)

# ============================================== billboard hoarding, roadside =
BB_Y = -26.00
BB_X0, BB_X1 = 22.00, 36.00
BB_MID = (BB_X0 + BB_X1) / 2.0
box("Hoarding_Pole", (BB_MID - 0.45, BB_MID + 0.45), (BB_Y - 0.45, BB_Y + 0.45),
    (0.0, 12.60), LAMP_GREY)
box("Hoarding_Pole_Base", (BB_MID - 0.70, BB_MID + 0.70),
    (BB_Y - 0.70, BB_Y + 0.70), (0.0, 0.65), CONCRETE)
box("Hoarding_Board", (BB_X0, BB_X1), (BB_Y - 0.18, BB_Y + 0.12), (8.60, 14.60),
    BOARD_FACE)
box("Hoarding_Frame_Top", (BB_X0 - 0.20, BB_X1 + 0.20), (BB_Y - 0.24, BB_Y + 0.18),
    (14.60, 14.82), STEEL)
box("Hoarding_Frame_Bottom", (BB_X0 - 0.20, BB_X1 + 0.20), (BB_Y - 0.24, BB_Y + 0.18),
    (8.38, 8.60), STEEL)
box("Hoarding_Frame_Left", (BB_X0 - 0.20, BB_X0), (BB_Y - 0.24, BB_Y + 0.18),
    (8.38, 14.82), STEEL)
box("Hoarding_Frame_Right", (BB_X1, BB_X1 + 0.20), (BB_Y - 0.24, BB_Y + 0.18),
    (8.38, 14.82), STEEL)
box("Hoarding_Panel_Split", (BB_X0 + 9.60, BB_X0 + 9.76), (BB_Y - 0.22, BB_Y + 0.14),
    (8.60, 14.60), STEEL)
for k, z in enumerate((9.60, 13.40)):
    box("Hoarding_Truss_%d" % (k + 1), (BB_X0 + 0.20, BB_X1 - 0.20),
        (BB_Y + 0.12, BB_Y + 0.28), (z, z + 0.18), STEEL)
for k, ang in ((1, 34.0), (2, -34.0)):
    box("Hoarding_Brace_%d" % k, (BB_MID - 0.20, BB_MID + 0.20),
        (BB_Y + 0.20, BB_Y + 2.40), (9.20, 12.20), STEEL,
        rotation=(ang, 0.0, 0.0))

# Floodlight arms on top of the hoarding.
for k, px in enumerate((BB_X0 + 1.80, BB_X0 + 5.40, BB_X0 + 9.00, BB_X0 + 12.60)):
    box("Hoarding_Floodlight_Arm_%d" % (k + 1), (px - 0.07, px + 0.07),
        (BB_Y - 0.10, BB_Y + 0.04), (14.82, 16.90), STEEL)
    box("Hoarding_Floodlight_%d" % (k + 1), (px - 0.34, px + 0.34),
        (BB_Y - 0.28, BB_Y + 0.10), (16.90, 17.22), LAMP_GREY)

# ===== blue sheet barricade closing the west end of the boundary line ========
# In the reference this continues the yard boundary where the palisade stops,
# so it stays on the fence line rather than crossing the field of view.
BAR_Y = FEN_Y
box("Barricade_Sheet", (-40.5, FEN_X0), (BAR_Y - 0.08, BAR_Y + 0.08),
    (0.0, 2.30), BLUE_SHEET)
box("Barricade_Rail_Top", (-40.5, FEN_X0), (BAR_Y - 0.14, BAR_Y + 0.14),
    (2.30, 2.44), STEEL)
for k in range(4):
    px = -39.6 + k * 1.90
    box("Barricade_Post_%d" % (k + 1), (px - 0.09, px + 0.09),
        (BAR_Y - 0.16, BAR_Y + 0.16), (0.0, 2.52), STEEL)

# ================================================ street and power furniture =
for k, px in enumerate((-24.0, -6.0, 12.0, 30.0)):
    box("Street_Lamp_Pole_%d" % (k + 1), (px - 0.13, px + 0.13),
        (-17.10, -16.84), (0.0, 9.20), LAMP_GREY)
    box("Street_Lamp_Arm_%d" % (k + 1), (px - 0.09, px + 0.09),
        (-18.40, -16.90), (9.05, 9.22), LAMP_GREY)
    box("Street_Lamp_Head_%d" % (k + 1), (px - 0.24, px + 0.24),
        (-18.75, -18.15), (8.78, 9.06), LAMP_GREY)

for k, px in enumerate((-34.5, 8.0)):
    box("Power_Pole_%d" % (k + 1), (px - 0.16, px + 0.16), (-17.80, -17.48),
        (0.0, 11.20), CONCRETE)
    for c, z in enumerate((9.40, 10.40)):
        box("Power_Crossarm_%d_%d" % (k + 1, c + 1), (px - 1.30, px + 1.30),
            (-17.76, -17.58), (z, z + 0.14), STEEL)

for k, (y, z) in enumerate(((-17.62, 10.44), (-17.70, 10.46),
                            (-17.66, 9.44), (-17.72, 9.46))):
    box("Power_Line_%d" % (k + 1), (-35.0, 34.0), (y, y + 0.05), (z, z + 0.05),
        METAL_DARK)

# Roadside electrical cabinet, present in both reference photos.
box("Utility_Cabinet", (1.30, 2.20), (-13.70, -13.05), (0.0, 1.05), TRIM)
box("Utility_Cabinet_Door", (1.40, 2.10), (-13.78, -13.70), (0.12, 0.92), STEEL)
box("Utility_Cabinet_Lid", (1.20, 2.30), (-13.80, -12.95), (1.05, 1.14), STEEL)

# ================================================= gate guard cabin =========
box("Guard_Cabin", (6.00, 8.40), (-13.40, -11.00), (0.0, 2.50), TRIM,
    roof=True, roof_height=0.45, roof_color=METAL_DARK)
box("Guard_Cabin_Window", (6.25, 8.15), (-13.50, -13.40), (1.10, 1.90), GLASS)
box("Guard_Cabin_Sill", (6.15, 8.25), (-13.58, -13.40), (0.98, 1.10), CONCRETE)

# ============================================== yard stock: rebar and pipes ==
for k, (x0, y0, ang) in enumerate(((-16.0, -12.60, 0.0), (-16.6, -11.20, -3.0),
                                   (10.0, -12.40, 2.0), (10.6, -10.90, 0.0))):
    box("Rebar_Bundle_%d" % (k + 1), (x0, x0 + 11.0), (y0, y0 + 1.15),
        (0.0, 0.55), METAL_DARK, rotation=(0.0, 0.0, ang))

for k, (x0, y0) in enumerate(((5.0, -27.7), (10.8, -27.7), (16.4, -28.0))):
    box("Pipe_Stack_%d" % (k + 1), (x0, x0 + 5.20), (y0, y0 + 1.60),
        (0.0, 1.15), CONCRETE)
    box("Pipe_Stack_%d_Upper" % (k + 1), (x0 + 0.80, x0 + 4.40),
        (y0 + 0.10, y0 + 1.50), (1.15, 2.05), CONCRETE)

box("Cement_Pallet_1", (-9.0, -5.6), (-8.6, -6.9), (0.0, 1.30), TRIM)
box("Cement_Pallet_2", (-5.2, -2.2), (-8.4, -6.9), (0.0, 1.05), TRIM)

# ---------------------------------------------------------- ground planes ----
box("Road", (-40.0, 40.0), (-24.00, -16.40), (-0.06, 0.0), ASPHALT)
box("Road_Kerb_Near", (-40.0, 40.0), (-16.60, -16.40), (-0.06, 0.22), CONCRETE)
box("Road_Kerb_Far", (-40.0, 40.0), (-24.20, -24.00), (-0.06, 0.22), CONCRETE)
box("Footpath", (-40.0, 40.0), (-16.40, -14.20), (-0.02, 0.16), CONCRETE)
box("Far_Verge", (-40.0, 40.0), (-28.40, -24.20), (-0.02, 0.14), DIRT)
box("Yard_Ground", (-38.0, 38.0), (-14.20, 16.00), (-0.02, 0.12), DIRT)

# ----------------------------------------------------------------- palms -----
palm("Palm_01", 38.0, -11.5, 7.20, 2.60)
palm("Palm_02", 34.0, -8.00, 5.80, 2.20)
palm("Palm_03", -36.5, -10.5, 6.40, 2.40)
palm("Palm_04", -30.5, -12.0, 5.10, 2.00)
palm("Palm_05", 20.0, -4.00, 6.80, 2.50)

# ----------------------------------------------------------------- output ----
scene = {"buildings": BUILDINGS, "trees": TREES}
out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scene.json")
with open(out_path, "w", encoding="utf-8") as fh:
    json.dump(scene, fh, indent=2)
    fh.write("\n")

print("buildings: %d" % len(BUILDINGS))
print("trees:     %d" % len(TREES))
print("wrote:     %s" % out_path)
