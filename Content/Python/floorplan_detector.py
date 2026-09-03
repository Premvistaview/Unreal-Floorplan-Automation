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

# Bump when editing this file; the log line proves which copy the editor loaded.
DETECTOR_REVISION = "2026-09-02-opencv5-dedupe"


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
        edges, 1, np.pi / 180.0, threshold=80, minLineLength=max(24, min(width, height) // 40), maxLineGap=10
    )
    if raw is None:
        _log("ERROR: HoughLinesP returned no lines. Check contrast, scale, or DPI.", log)
        return []

    # OpenCV 4 returns (N, 1, 4); OpenCV 5 returns (N, 4).
    lines = np.asarray(raw, dtype=float).reshape(-1, 4)

    snapped: List[Tuple[float, float, float, float]] = []
    angle_limit = math.radians(12.0)
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
            snapped.append((x1, y1, x2, y2))

    _log("6. Nearby parallel wall-pair filtering and merge.", log)
    # Canny reports both sides of every drawn line, so collapse those duplicates
    # first; otherwise wall pairing matches the artifact instead of the wall faces.
    collapsed = _collapse_duplicates(snapped, tol=3.0)
    paired = _pair_parallel_walls(collapsed, min_gap=4.0, max_gap=80.0)
    merged = _merge_colinear(paired)

    if pixels_per_foot <= 1e-6:
        _log("ERROR: IMAGE_PIXELS_PER_FOOT must be > 0.", log)
        return []

    cm_per_pixel = 30.48 / pixels_per_foot
    walls: List[Wall] = []
    for x1, y1, x2, y2, thickness_px in merged:
        # Image Y grows downward; Unreal XY uses Y up on the floor plane.
        start = (x1 * cm_per_pixel, (height - y1) * cm_per_pixel)
        end = (x2 * cm_per_pixel, (height - y2) * cm_per_pixel)
        thickness = max(thickness_px * cm_per_pixel, default_thickness_cm * 0.25)
        walls.append(_seg(start, end, thickness))

    walls = skip_zero_length(walls)
    _log(f"7. Raster route produced {len(walls)} wall segment(s).", log)
    if not walls:
        _log("ERROR: No usable walls after pairing/merge. Try a cleaner scan or different pixels-per-foot.", log)
    return walls


def _collapse_duplicates(
    lines: Sequence[Tuple[float, float, float, float]],
    tol: float,
) -> List[Tuple[float, float, float, float]]:
    """Merge overlapping lines that sit within tol of the same axis offset."""
    horizontals: List[Tuple[float, float, float, float]] = []
    verticals: List[Tuple[float, float, float, float]] = []
    for line in lines:
        if abs(line[3] - line[1]) < abs(line[2] - line[0]):
            horizontals.append(line)
        else:
            verticals.append(line)

    def collapse(group, is_horizontal: bool):
        result: List[Tuple[float, float, float, float]] = []
        for line in group:
            for index, existing in enumerate(result):
                if is_horizontal:
                    same_offset = abs(line[1] - existing[1]) <= tol
                    overlaps = min(line[2], existing[2]) >= max(line[0], existing[0]) - tol
                    if same_offset and overlaps:
                        offset = (line[1] + existing[1]) * 0.5
                        result[index] = (
                            min(line[0], existing[0]), offset,
                            max(line[2], existing[2]), offset,
                        )
                        break
                else:
                    same_offset = abs(line[0] - existing[0]) <= tol
                    overlaps = min(line[3], existing[3]) >= max(line[1], existing[1]) - tol
                    if same_offset and overlaps:
                        offset = (line[0] + existing[0]) * 0.5
                        result[index] = (
                            offset, min(line[1], existing[1]),
                            offset, max(line[3], existing[3]),
                        )
                        break
            else:
                result.append(line)
        return result

    return collapse(horizontals, True) + collapse(verticals, False)


def _pair_parallel_walls(
    lines: Sequence[Tuple[float, float, float, float]],
    min_gap: float,
    max_gap: float,
) -> List[Tuple[float, float, float, float, float]]:
    used = [False] * len(lines)
    result: List[Tuple[float, float, float, float, float]] = []

    def is_horizontal(line: Tuple[float, float, float, float]) -> bool:
        return abs(line[3] - line[1]) < abs(line[2] - line[0])

    for i, a in enumerate(lines):
        if used[i]:
            continue
        best_j = -1
        best_gap = max_gap + 1.0
        a_h = is_horizontal(a)
        for j, b in enumerate(lines):
            if i == j or used[j] or is_horizontal(b) != a_h:
                continue
            if a_h:
                overlap = min(a[2], b[2]) - max(a[0], b[0])
                if overlap < 8.0:
                    continue
                gap = abs((a[1] + a[3]) * 0.5 - (b[1] + b[3]) * 0.5)
            else:
                overlap = min(a[3], b[3]) - max(a[1], b[1])
                if overlap < 8.0:
                    continue
                gap = abs((a[0] + a[2]) * 0.5 - (b[0] + b[2]) * 0.5)
            if min_gap <= gap <= max_gap and gap < best_gap:
                best_gap = gap
                best_j = j

        if best_j >= 0:
            used[i] = used[best_j] = True
            b = lines[best_j]
            if a_h:
                y = ((a[1] + a[3]) + (b[1] + b[3])) * 0.25
                x1, x2 = min(a[0], b[0]), max(a[2], b[2])
                result.append((x1, y, x2, y, best_gap))
            else:
                x = ((a[0] + a[2]) + (b[0] + b[2])) * 0.25
                y1, y2 = min(a[1], b[1]), max(a[3], b[3])
                result.append((x, y1, x, y2, best_gap))
        else:
            used[i] = True
            result.append((a[0], a[1], a[2], a[3], 12.0))

    return result


def _merge_colinear(
    segs: Sequence[Tuple[float, float, float, float, float]],
    gap: float = 12.0,
) -> List[Tuple[float, float, float, float, float]]:
    horizontals = [s for s in segs if abs(s[3] - s[1]) < abs(s[2] - s[0])]
    verticals = [s for s in segs if s not in horizontals]
    merged: List[Tuple[float, float, float, float, float]] = []

    horizontals.sort(key=lambda s: (round(s[1], 1), s[0]))
    group: List[Tuple[float, float, float, float, float]] = []
    for seg in horizontals:
        if not group:
            group = [seg]
            continue
        prev = group[-1]
        if abs(seg[1] - prev[1]) < 3.0 and seg[0] <= prev[2] + gap:
            group[-1] = (prev[0], prev[1], max(prev[2], seg[2]), prev[3], max(prev[4], seg[4]))
        else:
            merged.extend(group)
            group = [seg]
    merged.extend(group)

    verticals.sort(key=lambda s: (round(s[0], 1), s[1]))
    group = []
    for seg in verticals:
        if not group:
            group = [seg]
            continue
        prev = group[-1]
        if abs(seg[0] - prev[0]) < 3.0 and seg[1] <= prev[3] + gap:
            group[-1] = (prev[0], prev[1], prev[2], max(prev[3], seg[3]), max(prev[4], seg[4]))
        else:
            merged.extend(group)
            group = [seg]
    merged.extend(group)
    return merged


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
        color = drawing.get("color")
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
                corners = [
                    (x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)
                ]
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

    vector_walls = skip_zero_length(vector_walls, min_length=pdf_points_to_unreal_cm * 2.0)
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
            walls.extend(
                _entity_to_walls(entity, dxf_units_to_unreal_cm, default_thickness_cm)
            )

    walls = skip_zero_length(walls)
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
        exact = [name for name in names if name == requested]
        if exact:
            return exact
        insensitive = [name for name in names if name.lower() == requested.lower()]
        if insensitive:
            _log(
                f"   Layer filter '{requested}' matched '{insensitive[0]}' case-insensitively.",
                log,
            )
            return insensitive
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
        return detect_walls_from_dxf(file_path, dxf_units_to_unreal_cm, cad_layer_filter, log, default_thickness_cm)
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
