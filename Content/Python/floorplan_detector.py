"""Wall detection shared by the Unreal Editor importer. No Blender / GLB / FBX."""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

Wall = Dict[str, object]
LogFn = Callable[[str], None]
Line = Tuple[float, float, float, float]
Seg = Tuple[float, float, float, float, float]

# Bump when editing this file; the log line proves which copy the editor loaded.
DETECTOR_REVISION = "2026-09-16-standard-thickness"

# Raster (pixels)
SNAP_ANGLE_DEG = 12.0
COLLAPSE_TOL_PX = 3.0
PAIR_MIN_GAP_PX = 4.0
PAIR_MAX_GAP_PX = 80.0
PAIR_MIN_OVERLAP_PX = 8.0
MERGE_GAP_PX = 12.0
MERGE_OFFSET_PX = 3.0
# Marks a line that found no parallel partner, so its thickness was never
# measured. Negative so _merge_group's max() prefers a measured value when a
# paired and an unpaired fragment of the same wall are merged.
UNPAIRED_THICKNESS_PX = -1.0
# The pair gap is the distance between Canny edge-pixel centres, which sits
# one pixel wide of the drawn stroke (measured as exactly +1.0 px for every
# stroke width from 4 to 22 px). Removed before converting to real units.
EDGE_PAIR_BIAS_PX = 1.0

# Wall thickness standards. A measured parallel-pair gap is snapped to the
# nearest of these (common stud and masonry widths) to remove pixel jitter;
# a gap farther than the tolerance from every standard is treated as a
# false pairing and falls back to the caller's default thickness.
CM_PER_INCH = 2.54
STANDARD_WALL_THICKNESSES_IN: Tuple[float, ...] = (4.0, 6.0, 8.0, 10.0, 12.0)
THICKNESS_SNAP_TOLERANCE_IN = 1.5
MAX_THICKNESS_WARNINGS = 10   # per detection run; the rest are summarised

# World-space cleanup (Unreal centimetres)
JUNCTION_SNAP_CM = 12.0
MIN_WALL_LENGTH_CM = 8.0
MERGE_GAP_CM = 12.0
MERGE_OFFSET_CM = 4.0


def _log(message: str, log: Optional[LogFn]) -> None:
    if log:
        log(message)
    else:
        print(message)


def _seg(start: Sequence[float], end: Sequence[float], thickness: float) -> Wall:
    return {
        "start": [float(start[0]), float(start[1])],
        "end": [float(end[0]), float(end[1])],
        "thickness": float(thickness),
    }


def _length(start: Sequence[float], end: Sequence[float]) -> float:
    return math.hypot(end[0] - start[0], end[1] - start[1])


def skip_zero_length(walls: Iterable[Wall], min_length: float = 1e-6) -> List[Wall]:
    return [w for w in walls if _length(w["start"], w["end"]) > min_length and w["thickness"] > min_length]


def _is_horizontal(x1: float, y1: float, x2: float, y2: float) -> bool:
    return abs(y2 - y1) < abs(x2 - x1)


# ---------------------------------------------------------------------------
# Raster / OpenCV
# ---------------------------------------------------------------------------

def detect_walls_from_image(
    image_path: str,
    pixels_per_foot: float,
    log: Optional[LogFn] = None,
    default_thickness_cm: float = 15.0,
) -> List[Wall]:
    import cv2
    import numpy as np

    _log("3. Loading raster with OpenCV (grayscale).", log)
    image = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if image is None:
        _log(f"ERROR: OpenCV could not read image: {image_path}", log)
        return []

    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    _log("4. Adaptive threshold, morphological open/close, Canny.", log)
    binary = cv2.adaptiveThreshold(
        blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 8
    )
    _, otsu = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    combined = cv2.bitwise_or(binary, otsu)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    opened = cv2.morphologyEx(combined, cv2.MORPH_OPEN, kernel)
    closed = cv2.morphologyEx(opened, cv2.MORPH_CLOSE, kernel)
    edges = cv2.Canny(closed, 50, 150)

    _log("5. HoughLinesP, then horizontal/vertical snap.", log)
    raw = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180.0,
        threshold=80,
        minLineLength=max(24, min(width, height) // 40),
        maxLineGap=10,
    )
    if raw is None:
        _log("ERROR: HoughLinesP returned no lines. Check contrast, scale, or DPI.", log)
        return []

    # OpenCV 4 returns (N, 1, 4); OpenCV 5 returns (N, 4).
    lines = np.asarray(raw, dtype=float).reshape(-1, 4)
    snapped = _snap_axis_aligned(lines)
    _log(f"   Hough produced {len(snapped)} snapped line(s).", log)

    _log("6. Collapse Canny duplicates, pair wall faces, merge colinear runs.", log)
    collapsed = _collapse_duplicates(snapped, COLLAPSE_TOL_PX)
    if pixels_per_foot <= 1e-6:
        _log("ERROR: IMAGE_PIXELS_PER_FOOT must be > 0.", log)
        return []
    cm_per_pixel = 30.48 / pixels_per_foot
    paired = _pair_parallel_walls(collapsed, PAIR_MIN_GAP_PX, PAIR_MAX_GAP_PX, UNPAIRED_THICKNESS_PX)
    merged = _merge_colinear(paired, MERGE_GAP_PX, MERGE_OFFSET_PX)

    _log("7. Snap measured wall thickness to standard widths.", log)
    walls, distribution = _walls_from_pixel_segments(merged, height, cm_per_pixel, default_thickness_cm, log)
    _log_thickness_distribution(distribution, log)

    walls = cleanup_walls(walls)
    _log(f"8. Raster route produced {len(walls)} wall segment(s).", log)
    if not walls:
        _log("ERROR: No usable walls after pairing/merge. Try a cleaner scan or different pixels-per-foot.", log)
    return walls


def snap_wall_thickness(
    measured_cm: float,
    default_cm: float,
    standards_in: Sequence[float] = STANDARD_WALL_THICKNESSES_IN,
    tolerance_in: float = THICKNESS_SNAP_TOLERANCE_IN,
) -> Tuple[float, str]:
    """Snap a measured thickness to the nearest standard wall width.

    Returns (thickness_cm, label). The label is the standard chosen, e.g.
    "6in", or "fallback-default" when the measurement is farther than the
    tolerance from every standard, which normally means the parallel pair
    was not really two faces of one wall.
    """
    if not standards_in:
        return default_cm, "fallback-default"
    nearest = min(standards_in, key=lambda inches: abs(inches * CM_PER_INCH - measured_cm))
    if abs(nearest * CM_PER_INCH - measured_cm) <= tolerance_in * CM_PER_INCH:
        return nearest * CM_PER_INCH, _inch_label(nearest)
    return default_cm, "fallback-default"


def _inch_label(inches: float) -> str:
    return f"{inches:g}in"


def _walls_from_pixel_segments(
    segs: Sequence[Seg],
    image_height: int,
    cm_per_pixel: float,
    default_thickness_cm: float,
    log: Optional[LogFn],
) -> Tuple[List[Wall], Dict[str, int]]:
    """Convert pixel segments to Unreal-cm walls with standards-snapped thickness.

    Also returns how many walls received each thickness label so detection
    quality can be judged from the console.
    """
    walls: List[Wall] = []
    distribution: Dict[str, int] = defaultdict(int)
    fallbacks = 0
    for x1, y1, x2, y2, thickness_px in segs:
        # Image Y grows downward; Unreal XY uses Y up on the floor plane.
        start = (x1 * cm_per_pixel, (image_height - y1) * cm_per_pixel)
        end = (x2 * cm_per_pixel, (image_height - y2) * cm_per_pixel)

        if thickness_px <= 0.0:
            # No parallel partner was found, so nothing was measured.
            thickness, label = default_thickness_cm, "unpaired-default"
        else:
            corrected_px = max(thickness_px - EDGE_PAIR_BIAS_PX, 1.0)
            measured_cm = corrected_px * cm_per_pixel
            thickness, label = snap_wall_thickness(measured_cm, default_thickness_cm)
            if label == "fallback-default":
                fallbacks += 1
                if fallbacks <= MAX_THICKNESS_WARNINGS:
                    _log(
                        f"WARNING: measured wall thickness {measured_cm:.1f} cm "
                        f"({measured_cm / CM_PER_INCH:.1f} in) matches no standard width "
                        f"(likely a false pairing); using default {default_thickness_cm:.1f} cm.",
                        log,
                    )
        distribution[label] += 1
        walls.append(_seg(start, end, thickness))

    if fallbacks > MAX_THICKNESS_WARNINGS:
        _log(
            f"WARNING: {fallbacks - MAX_THICKNESS_WARNINGS} more wall(s) fell back to the default thickness.",
            log,
        )
    return walls, distribution


def _log_thickness_distribution(distribution: Dict[str, int], log: Optional[LogFn]) -> None:
    if not distribution:
        return

    def order(label: str) -> Tuple[int, float]:
        if label.endswith("in"):
            return (0, float(label[:-2]))
        return (1, 0.0) if label == "unpaired-default" else (2, 0.0)

    parts = ", ".join(f"{label}: {distribution[label]} wall(s)" for label in sorted(distribution, key=order))
    _log(f"   Thickness distribution: {parts}", log)


def _snap_axis_aligned(lines: Sequence[Sequence[float]]) -> List[Line]:
    snapped: List[Line] = []
    angle_limit = math.radians(SNAP_ANGLE_DEG)
    for x1, y1, x2, y2 in lines:
        dx, dy = x2 - x1, y2 - y1
        angle = abs(math.atan2(dy, dx))
        if angle < angle_limit or abs(angle - math.pi) < angle_limit:
            y = (y1 + y2) * 0.5
            snapped.append((min(x1, x2), y, max(x1, x2), y))
        elif abs(angle - math.pi / 2.0) < angle_limit:
            x = (x1 + x2) * 0.5
            snapped.append((x, min(y1, y2), x, max(y1, y2)))
        else:
            snapped.append((float(x1), float(y1), float(x2), float(y2)))
    return snapped


def _collapse_duplicates(lines: Sequence[Line], tol: float) -> List[Line]:
    """Merge overlapping lines that sit within tol of the same axis offset."""
    horizontals = [line for line in lines if _is_horizontal(*line)]
    verticals = [line for line in lines if not _is_horizontal(*line)]
    return _collapse_group(horizontals, True, tol) + _collapse_group(verticals, False, tol)


def _collapse_group(group: Sequence[Line], is_horizontal: bool, tol: float) -> List[Line]:
    if not group:
        return []
    ordered = sorted(group, key=lambda line: (line[1], line[0]) if is_horizontal else (line[0], line[1]))
    result: List[Line] = []
    for line in ordered:
        merged = False
        # Nearby offsets live at the end of the sorted result.
        for index in range(len(result) - 1, -1, -1):
            existing = result[index]
            if is_horizontal:
                if existing[1] < line[1] - tol:
                    break
                overlaps = min(line[2], existing[2]) >= max(line[0], existing[0]) - tol
                if overlaps:
                    offset = (line[1] + existing[1]) * 0.5
                    result[index] = (min(line[0], existing[0]), offset, max(line[2], existing[2]), offset)
                    merged = True
                    break
            else:
                if existing[0] < line[0] - tol:
                    break
                overlaps = min(line[3], existing[3]) >= max(line[1], existing[1]) - tol
                if overlaps:
                    offset = (line[0] + existing[0]) * 0.5
                    result[index] = (offset, min(line[1], existing[1]), offset, max(line[3], existing[3]))
                    merged = True
                    break
        if not merged:
            result.append(line)
    return result


def _pair_parallel_walls(
    lines: Sequence[Line],
    min_gap: float,
    max_gap: float,
    unpaired_thickness: float,
) -> List[Seg]:
    horizontals = [line for line in lines if _is_horizontal(*line)]
    verticals = [line for line in lines if not _is_horizontal(*line)]
    return _pair_group(horizontals, True, min_gap, max_gap, unpaired_thickness) + _pair_group(
        verticals, False, min_gap, max_gap, unpaired_thickness
    )


def _pair_group(
    group: Sequence[Line],
    is_horizontal: bool,
    min_gap: float,
    max_gap: float,
    unpaired_thickness: float,
) -> List[Seg]:
    if not group:
        return []
    ordered = sorted(group, key=lambda line: (line[1], line[0]) if is_horizontal else (line[0], line[1]))
    used = [False] * len(ordered)
    result: List[Seg] = []

    def offset(line: Line) -> float:
        return (line[1] + line[3]) * 0.5 if is_horizontal else (line[0] + line[2]) * 0.5

    def overlap(a: Line, b: Line) -> float:
        if is_horizontal:
            return min(a[2], b[2]) - max(a[0], b[0])
        return min(a[3], b[3]) - max(a[1], b[1])

    for i, a in enumerate(ordered):
        if used[i]:
            continue
        best_j = -1
        best_gap = max_gap + 1.0
        a_off = offset(a)
        for j in range(i + 1, len(ordered)):
            if used[j]:
                continue
            gap = offset(ordered[j]) - a_off
            if gap < min_gap:
                continue
            if gap > max_gap:
                break
            if overlap(a, ordered[j]) < PAIR_MIN_OVERLAP_PX:
                continue
            if gap < best_gap:
                best_gap = gap
                best_j = j

        used[i] = True
        if best_j >= 0:
            used[best_j] = True
            b = ordered[best_j]
            if is_horizontal:
                y = (a_off + offset(b)) * 0.5
                result.append((min(a[0], b[0]), y, max(a[2], b[2]), y, best_gap))
            else:
                x = (a_off + offset(b)) * 0.5
                result.append((x, min(a[1], b[1]), x, max(a[3], b[3]), best_gap))
        else:
            result.append((a[0], a[1], a[2], a[3], unpaired_thickness))
    return result


def _merge_colinear(segs: Sequence[Seg], gap: float, offset_tol: float) -> List[Seg]:
    horizontals = [seg for seg in segs if _is_horizontal(seg[0], seg[1], seg[2], seg[3])]
    verticals = [seg for seg in segs if not _is_horizontal(seg[0], seg[1], seg[2], seg[3])]
    return _merge_group(horizontals, True, gap, offset_tol) + _merge_group(verticals, False, gap, offset_tol)


def _merge_group(segs: Sequence[Seg], is_horizontal: bool, gap: float, offset_tol: float) -> List[Seg]:
    if not segs:
        return []
    ordered = sorted(segs, key=lambda seg: (seg[1], seg[0]) if is_horizontal else (seg[0], seg[1]))
    merged: List[Seg] = [ordered[0]]
    for seg in ordered[1:]:
        prev = merged[-1]
        if is_horizontal:
            same_run = abs(seg[1] - prev[1]) < offset_tol and seg[0] <= prev[2] + gap
            if same_run:
                merged[-1] = (prev[0], prev[1], max(prev[2], seg[2]), prev[3], max(prev[4], seg[4]))
                continue
        else:
            same_run = abs(seg[0] - prev[0]) < offset_tol and seg[1] <= prev[3] + gap
            if same_run:
                merged[-1] = (prev[0], prev[1], prev[2], max(prev[3], seg[3]), max(prev[4], seg[4]))
                continue
        merged.append(seg)
    return merged


# ---------------------------------------------------------------------------
# World-space cleanup (all input formats)
# ---------------------------------------------------------------------------

def cleanup_walls(
    walls: Sequence[Wall],
    snap_cm: float = JUNCTION_SNAP_CM,
    min_length_cm: float = MIN_WALL_LENGTH_CM,
) -> List[Wall]:
    """Snap T-junctions and corners, merge colinear runs, drop noise."""
    segs: List[Seg] = []
    for wall in walls:
        start, end = wall["start"], wall["end"]
        x1, y1, x2, y2 = float(start[0]), float(start[1]), float(end[0]), float(end[1])
        if _is_horizontal(x1, y1, x2, y2):
            y = (y1 + y2) * 0.5
            segs.append((min(x1, x2), y, max(x1, x2), y, float(wall["thickness"])))
        elif abs(x2 - x1) < abs(y2 - y1):
            x = (x1 + x2) * 0.5
            segs.append((x, min(y1, y2), x, max(y1, y2), float(wall["thickness"])))
        else:
            segs.append((x1, y1, x2, y2, float(wall["thickness"])))

    segs = _snap_junctions(segs, snap_cm)
    segs = _merge_colinear(segs, MERGE_GAP_CM, MERGE_OFFSET_CM)

    cleaned: List[Wall] = []
    for x1, y1, x2, y2, thickness in segs:
        if math.hypot(x2 - x1, y2 - y1) < min_length_cm or thickness <= 1e-6:
            continue
        cleaned.append(_seg((x1, y1), (x2, y2), thickness))
    return cleaned


def _snap_junctions(segs: Sequence[Seg], snap_cm: float) -> List[Seg]:
    """Pull nearby axis-aligned endpoints onto H/V intersections."""
    mutable = [list(seg) for seg in segs]
    horizontals = [
        item for item in mutable if abs(item[3] - item[1]) < abs(item[2] - item[0])
    ]
    verticals = [
        item for item in mutable if abs(item[3] - item[1]) >= abs(item[2] - item[0])
    ]

    for horizontal in horizontals:
        iy = (horizontal[1] + horizontal[3]) * 0.5
        for vertical in verticals:
            ix = (vertical[0] + vertical[2]) * 0.5
            extra = snap_cm + max(horizontal[4], vertical[4]) * 0.5
            if not (horizontal[0] - extra <= ix <= horizontal[2] + extra):
                continue
            if not (vertical[1] - extra <= iy <= vertical[3] + extra):
                continue
            if abs(horizontal[0] - ix) <= extra:
                horizontal[0] = ix
            if abs(horizontal[2] - ix) <= extra:
                horizontal[2] = ix
            if abs(vertical[1] - iy) <= extra:
                vertical[1] = iy
            if abs(vertical[3] - iy) <= extra:
                vertical[3] = iy
            horizontal[1] = horizontal[3] = iy
            vertical[0] = vertical[2] = ix

    return [tuple(item) for item in mutable]  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PDF (PyMuPDF)
# ---------------------------------------------------------------------------

def detect_walls_from_pdf(
    pdf_path: str,
    page_index: int,
    raster_dpi: float,
    pixels_per_foot: float,
    pdf_points_to_unreal_cm: float,
    log: Optional[LogFn] = None,
    default_thickness_cm: float = 15.0,
) -> List[Wall]:
    import fitz

    _log(f"3. Opening PDF page {page_index} with PyMuPDF.", log)
    document = fitz.open(pdf_path)
    if page_index < 0 or page_index >= document.page_count:
        _log(f"ERROR: PDF page {page_index} is out of range (count={document.page_count}).", log)
        document.close()
        return []

    page = document.load_page(page_index)
    page_height = float(page.rect.height)
    drawings = page.get_drawings()
    vector_walls: List[Wall] = []

    _log(f"4. Inspecting {len(drawings)} vector drawing path(s).", log)
    for drawing in drawings:
        stroke = drawing.get("width") or 1.0
        thickness = max(float(stroke) * pdf_points_to_unreal_cm, default_thickness_cm * 0.2)
        # Skip large filled rooms; keep stroked linework.
        if drawing.get("fill") and not drawing.get("color") and stroke <= 0.0:
            continue
        for item in drawing.get("items", []):
            kind = item[0]
            if kind == "l":
                p1, p2 = item[1], item[2]
                vector_walls.append(
                    _seg(
                        (p1.x * pdf_points_to_unreal_cm, (page_height - p1.y) * pdf_points_to_unreal_cm),
                        (p2.x * pdf_points_to_unreal_cm, (page_height - p2.y) * pdf_points_to_unreal_cm),
                        thickness,
                    )
                )
            elif kind == "re":
                rect = item[1]
                x0, y0, x1, y1 = rect.x0, rect.y0, rect.x1, rect.y1
                corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
                for a, b in zip(corners, corners[1:]):
                    vector_walls.append(
                        _seg(
                            (a[0] * pdf_points_to_unreal_cm, (page_height - a[1]) * pdf_points_to_unreal_cm),
                            (b[0] * pdf_points_to_unreal_cm, (page_height - b[1]) * pdf_points_to_unreal_cm),
                            thickness,
                        )
                    )
            elif kind == "c":
                pts = item[1:]
                samples = _sample_cubic(pts[0], pts[1], pts[2], pts[3], 8)
                for a, b in zip(samples, samples[1:]):
                    vector_walls.append(
                        _seg(
                            (a[0] * pdf_points_to_unreal_cm, (page_height - a[1]) * pdf_points_to_unreal_cm),
                            (b[0] * pdf_points_to_unreal_cm, (page_height - b[1]) * pdf_points_to_unreal_cm),
                            thickness,
                        )
                    )

    vector_walls = cleanup_walls(vector_walls, min_length_cm=max(MIN_WALL_LENGTH_CM, pdf_points_to_unreal_cm * 2.0))
    if vector_walls:
        _log(f"5. Vector PDF produced {len(vector_walls)} wall segment(s).", log)
        document.close()
        return vector_walls

    _log("5. No usable vector walls; rasterizing page and using OpenCV.", log)
    zoom = raster_dpi / 72.0
    pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
        raster_path = handle.name
    pixmap.save(raster_path)
    document.close()
    try:
        return detect_walls_from_image(raster_path, pixels_per_foot, log, default_thickness_cm)
    finally:
        try:
            os.remove(raster_path)
        except OSError:
            pass


def _sample_cubic(p0, p1, p2, p3, steps: int) -> List[Tuple[float, float]]:
    points = []
    for i in range(steps + 1):
        t = i / float(steps)
        u = 1.0 - t
        x = u**3 * p0.x + 3 * u**2 * t * p1.x + 3 * u * t**2 * p2.x + t**3 * p3.x
        y = u**3 * p0.y + 3 * u**2 * t * p1.y + 3 * u * t**2 * p2.y + t**3 * p3.y
        points.append((x, y))
    return points


# ---------------------------------------------------------------------------
# DWG / DXF
# ---------------------------------------------------------------------------

def find_oda_converter(explicit_path: str = "") -> Optional[str]:
    candidates = [explicit_path, os.environ.get("ODA_FILE_CONVERTER", "")]
    program_files = [os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")]
    for root in program_files:
        oda_root = Path(root) / "ODA"
        if oda_root.is_dir():
            candidates.extend(str(path) for path in oda_root.glob("**/ODAFileConverter.exe"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def convert_dwg_to_dxf(dwg_path: str, oda_path: str, log: Optional[LogFn] = None) -> Optional[str]:
    _log("3. Converting DWG → DXF with ODA File Converter.", log)
    work = Path(tempfile.mkdtemp(prefix="ue_dwg_"))
    input_dir = work / "in"
    output_dir = work / "out"
    input_dir.mkdir()
    output_dir.mkdir()
    source = Path(dwg_path)
    shutil.copy2(source, input_dir / source.name)
    command = [oda_path, str(input_dir), str(output_dir), "ACAD2018", "DXF", "0", "1"]
    _log(f"   ODA command: {command}", log)
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        _log(f"ERROR: ODA File Converter failed ({completed.returncode}): {completed.stderr or completed.stdout}", log)
        return None
    dxf_files = list(output_dir.glob("*.dxf"))
    if not dxf_files:
        _log("ERROR: ODA produced no DXF. Check that the DWG is readable.", log)
        return None
    return str(dxf_files[0])


def detect_walls_from_dxf(
    dxf_path: str,
    dxf_units_to_unreal_cm: float,
    layer_filter: str,
    log: Optional[LogFn] = None,
    default_thickness_cm: float = 15.0,
) -> List[Wall]:
    import ezdxf

    _log("4. Reading DXF with ezdxf (LINE, LWPOLYLINE, POLYLINE).", log)
    document = ezdxf.readfile(dxf_path)
    modelspace = document.modelspace()
    supported = ("LINE", "LWPOLYLINE", "POLYLINE")
    layer_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    entities_by_layer: Dict[str, List[object]] = defaultdict(list)

    for entity in modelspace:
        kind = entity.dxftype()
        if kind not in supported:
            continue
        layer_name = str(entity.dxf.layer)
        layer_counts[layer_name][kind] += 1
        entities_by_layer[layer_name].append(entity)

    _log("5. CAD supported-entity counts per layer:", log)
    if not layer_counts:
        _log("ERROR: DXF has no LINE / LWPOLYLINE / POLYLINE entities.", log)
        return []
    for layer_name in sorted(layer_counts):
        counts = layer_counts[layer_name]
        parts = ", ".join(f"{kind}={counts[kind]}" for kind in supported if counts[kind])
        _log(f"   layer '{layer_name}': {parts} (total {sum(counts.values())})", log)

    selected_layers = _select_cad_layers(layer_counts, layer_filter, log)
    walls: List[Wall] = []
    for layer_name in selected_layers:
        for entity in entities_by_layer[layer_name]:
            walls.extend(_entity_to_walls(entity, dxf_units_to_unreal_cm, default_thickness_cm))

    walls = cleanup_walls(walls)
    _log(f"6. CAD route produced {len(walls)} wall segment(s) from layers {selected_layers}.", log)
    if not walls:
        _log(
            "ERROR: Zero walls after extraction. Layer filter likely does not match this drawing "
            "(previous failure was a hardcoded 'Walls' filter vs actual 'wall').",
            log,
        )
    return walls


def _select_cad_layers(
    layer_counts: Dict[str, Dict[str, int]],
    layer_filter: str,
    log: Optional[LogFn],
) -> List[str]:
    names = list(layer_counts.keys())
    requested = (layer_filter or "").strip()
    if requested:
        wanted = {part.strip().lower() for part in requested.split(",") if part.strip()}
        matched = [name for name in names if name.lower() in wanted]
        if matched:
            if any(name.lower() != requested.lower() for name in matched) or "," in requested:
                _log(f"   Layer filter '{requested}' matched {matched}.", log)
            return matched
        _log(
            f"WARNING: Layer filter '{requested}' matched no layer. Falling back to auto-detect.",
            log,
        )

    wallish = [name for name in names if "wall" in name.lower()]
    if wallish:
        _log(f"   Auto-selected wall-like layer(s): {wallish}", log)
        return wallish

    _log("   No wall-like layer name; using every layer that has supported entities.", log)
    return names


def _entity_to_walls(entity, scale: float, default_thickness_cm: float) -> List[Wall]:
    thickness = default_thickness_cm
    if hasattr(entity.dxf, "thickness"):
        raw = float(entity.dxf.thickness or 0.0)
        if raw > 0.0:
            thickness = raw * scale

    kind = entity.dxftype()
    if kind == "LINE":
        start = entity.dxf.start
        end = entity.dxf.end
        return [_seg((start.x * scale, start.y * scale), (end.x * scale, end.y * scale), thickness)]

    points: List[Tuple[float, float]] = []
    closed = False
    if kind == "LWPOLYLINE":
        points = [(float(p[0]) * scale, float(p[1]) * scale) for p in entity.get_points("xy")]
        closed = bool(entity.closed)
    elif kind == "POLYLINE":
        points = [(float(v.dxf.location.x) * scale, float(v.dxf.location.y) * scale) for v in entity.vertices]
        closed = bool(entity.is_closed)

    walls: List[Wall] = []
    for a, b in zip(points, points[1:]):
        walls.append(_seg(a, b, thickness))
    if closed and len(points) >= 2:
        walls.append(_seg(points[-1], points[0], thickness))
    return walls


def detect_walls_from_path(
    file_path: str,
    *,
    pixels_per_foot: float,
    pdf_points_to_unreal_cm: float,
    dxf_units_to_unreal_cm: float,
    pdf_page_index: int,
    raster_dpi: float,
    cad_layer_filter: str,
    oda_converter_path: str,
    default_thickness_cm: float,
    log: Optional[LogFn] = None,
) -> List[Wall]:
    _log(f"Detector revision {DETECTOR_REVISION}", log)
    suffix = Path(file_path).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg"}:
        _log("2. Routing image through OpenCV.", log)
        return detect_walls_from_image(file_path, pixels_per_foot, log, default_thickness_cm)
    if suffix == ".pdf":
        _log("2. Routing PDF through PyMuPDF (vector first, raster fallback).", log)
        return detect_walls_from_pdf(
            file_path, pdf_page_index, raster_dpi, pixels_per_foot, pdf_points_to_unreal_cm, log, default_thickness_cm
        )
    if suffix == ".dxf":
        _log("2. Routing DXF through ezdxf.", log)
        return detect_walls_from_dxf(dxf_path=file_path, dxf_units_to_unreal_cm=dxf_units_to_unreal_cm, layer_filter=cad_layer_filter, log=log, default_thickness_cm=default_thickness_cm)
    if suffix == ".dwg":
        _log("2. Routing DWG through ODA File Converter, then ezdxf.", log)
        oda = find_oda_converter(oda_converter_path)
        if not oda:
            _log(
                "ERROR: ODA File Converter not found. Set ODA_CONVERTER_PATH or install ODA File Converter. "
                "Python cannot read DWG directly.",
                log,
            )
            return []
        dxf_path = convert_dwg_to_dxf(file_path, oda, log)
        if not dxf_path:
            return []
        return detect_walls_from_dxf(dxf_path, dxf_units_to_unreal_cm, cad_layer_filter, log, default_thickness_cm)

    _log(f"ERROR: Unsupported extension '{suffix}'. Use png, jpg, jpeg, pdf, dwg, or dxf.", log)
    return []
