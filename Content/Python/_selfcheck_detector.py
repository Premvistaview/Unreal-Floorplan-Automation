"""Standalone sanity check for floorplan_detector outside the editor.

Run with Unreal's bundled interpreter:
    <UE>/Engine/Binaries/ThirdParty/Python3/Win64/python.exe _selfcheck_detector.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import cv2
import numpy as np

import floorplan_detector as fd

print(f"cv2 {cv2.__version__}")
print(f"detector revision {fd.DETECTOR_REVISION}")
print(f"detector file {fd.__file__}")

# 400x300 room outline, 10 px thick walls.
image = np.full((300, 400), 255, dtype=np.uint8)
cv2.rectangle(image, (40, 40), (360, 260), 0, 10)

out = Path(tempfile.gettempdir()) / "floorplan_selfcheck.png"
cv2.imwrite(str(out), image)

walls = fd.detect_walls_from_path(
    str(out),
    pixels_per_foot=10.0,
    pdf_points_to_unreal_cm=1.0,
    dxf_units_to_unreal_cm=1.0,
    pdf_page_index=0,
    raster_dpi=200.0,
    cad_layer_filter="",
    oda_converter_path="",
    default_thickness_cm=15.0,
    log=print,
)

print(f"walls detected: {len(walls)}")
for wall in walls:
    print(f"  {wall}")

if len(walls) != 4:
    raise SystemExit(f"FAIL: expected 4 walls, got {len(walls)}")
print("PASS")
