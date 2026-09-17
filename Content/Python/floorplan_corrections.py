"""Pure helpers for the wall-correction workflow. No Unreal imports.

The router stores correction state on the wall actors themselves (tags), so
it survives module reloads and editor restarts. These functions turn plain
records extracted from those actors into the numbers the UI and the
Finalize step report. Keeping them free of `unreal` lets them be tested
outside the editor.
"""

from __future__ import annotations

import math
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

WALL_TAG = "FloorPlanEditableWall"
ORIGIN_TAG_PREFIX = "FloorPlanOrigin:"
INDEX_TAG_PREFIX = "FloorPlanIndex:"
ORIGIN_DETECTED = "detected"
ORIGIN_ADDED = "added"

LABEL_PATTERN = re.compile(r"^Wall_(\d+)$")

# A detected wall counts as "adjusted" when its exported centreline differs
# from the raw detection by more than this, in centimetres.
ADJUST_TOLERANCE_CM = 0.5

Record = Dict[str, object]


# ------------------------------------------------------------------ tags ----
def origin_tag(origin: str) -> str:
    return f"{ORIGIN_TAG_PREFIX}{origin}"


def index_tag(index: int) -> str:
    return f"{INDEX_TAG_PREFIX}{int(index):03d}"


def parse_tags(tags: Iterable[str]) -> Tuple[Optional[str], Optional[int]]:
    """Return (origin, raw_index) encoded in an actor's tags, if present."""
    origin: Optional[str] = None
    index: Optional[int] = None
    for tag in tags:
        text = str(tag)
        if text.startswith(ORIGIN_TAG_PREFIX):
            origin = text[len(ORIGIN_TAG_PREFIX):] or None
        elif text.startswith(INDEX_TAG_PREFIX):
            try:
                index = int(text[len(INDEX_TAG_PREFIX):])
            except ValueError:
                index = None
    return origin, index


# --------------------------------------------------------------- labels -----
def next_wall_label(existing_labels: Iterable[str]) -> str:
    """Wall_NNN one above the highest existing number, so labels stay unique
    even after walls in the middle of the sequence have been removed."""
    highest = 0
    for label in existing_labels:
        match = LABEL_PATTERN.match(str(label))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"Wall_{highest + 1:03d}"


def wall_number(label: str, index: Optional[int]) -> str:
    """Human-facing '#N' for log lines: the raw detection index when known,
    otherwise the number embedded in the label, otherwise the label itself."""
    if index is not None:
        return f"#{index}"
    match = LABEL_PATTERN.match(str(label))
    return f"#{int(match.group(1))}" if match else str(label)


# ------------------------------------------------------------- geometry -----
def segment_length(record: Record) -> float:
    start, end = record["start"], record["end"]
    return math.hypot(float(end[0]) - float(start[0]), float(end[1]) - float(start[1]))


def segment_midpoint(record: Record) -> Tuple[float, float]:
    start, end = record["start"], record["end"]
    return ((float(start[0]) + float(end[0])) * 0.5, (float(start[1]) + float(end[1])) * 0.5)


def describe_wall(record: Record) -> str:
    """Short list-row text: length and approximate position in metres."""
    mid = segment_midpoint(record)
    return "%.2f m at (%.1f, %.1f) m, %.0f cm thick" % (
        segment_length(record) / 100.0,
        mid[0] / 100.0,
        mid[1] / 100.0,
        float(record["thickness"]),
    )


def _records_match(a: Record, b: Record, tolerance: float) -> bool:
    """Same centreline within tolerance, in either direction, same thickness."""
    if abs(float(a["thickness"]) - float(b["thickness"])) > tolerance:
        return False

    def close(p: Sequence[float], q: Sequence[float]) -> bool:
        return math.hypot(float(p[0]) - float(q[0]), float(p[1]) - float(q[1])) <= tolerance

    forward = close(a["start"], b["start"]) and close(a["end"], b["end"])
    reverse = close(a["start"], b["end"]) and close(a["end"], b["start"])
    return forward or reverse


# ---------------------------------------------------------- corrections -----
def compute_corrections(
    raw_records: Sequence[Record],
    current: Sequence[Record],
    tolerance: float = ADJUST_TOLERANCE_CM,
) -> Dict[str, int]:
    """Compare live walls against the raw detection.

    `current` records carry 'origin' and 'index' (from the actor tags) plus
    the exported geometry. Returns counts of removed, added and adjusted
    walls, and their total as 'corrections'.
    """
    raw_by_index = {i: rec for i, rec in enumerate(raw_records, start=1)}
    present_indices = set()
    added = 0
    adjusted = 0

    for record in current:
        origin = record.get("origin")
        index = record.get("index")
        if origin == ORIGIN_ADDED or index is None or index not in raw_by_index:
            added += 1
            continue
        present_indices.add(index)
        if not _records_match(raw_by_index[index], record, tolerance):
            adjusted += 1

    removed = len(raw_by_index) - len(present_indices)
    return {
        "detected": len(raw_by_index),
        "final": len(current),
        "removed": removed,
        "added": added,
        "adjusted": adjusted,
        "corrections": removed + added + adjusted,
    }


def export_records(current: Sequence[Record]) -> List[Record]:
    """Strip correction bookkeeping so the JSON keeps the original schema."""
    return [
        {"start": list(rec["start"]), "end": list(rec["end"]), "thickness": rec["thickness"]}
        for rec in current
    ]
