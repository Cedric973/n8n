"""Second opinions on scale: room areas, and dimensions written without a unit.

A drawing with no printed scale and no dimension strings can still be
calibrated if its rooms carry their areas, as many do ("51.88 m²"). The label
sits inside the room; flood-filling outward from it across a raster of the
drawing's linework reaches the walls (and the door leaves, which close the
openings) and stops. The enclosed count of cells, in paper units, against the
printed area in real units, gives the scale — squared, since it is an area.

Furniture drawn inside the room is an island the fill flows around, so each
reading runs a little small; the median of several rooms and their spread are
reported so the report can say how much to trust it.
"""

from __future__ import annotations

import math
import re
import statistics
from collections import deque

from .model import Drawing, Entity

_AREA = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:m2|m²|sqm|sq\.?\s*m)\b", re.I)
_BARE = re.compile(r"^\s*(\d{3,5})\s*$")

CELL_PT = 0.75         # raster cell size in paper points
MIN_ROOM_CELLS = 400   # smaller than this and the fill hit a symbol, not a room
MAX_ROOM_SHARE = 0.5   # larger than this share of the page and the fill leaked


def area_labels(drawing: Drawing) -> list[tuple[Entity, float]]:
    out = []
    for e in drawing.texts():
        m = _AREA.search(e.text or "")
        if m:
            out.append((e, float(m.group(1).replace(",", "."))))
    return out


def bare_millimetres(text: str) -> float | None:
    """A bare integer of plausible size is a CAD dimension in millimetres."""
    m = _BARE.match(text or "")
    if not m:
        return None
    value = int(m.group(1))
    return value / 1000.0 if 200 <= value <= 60000 else None


def calibrate_by_areas(drawing: Drawing, per_unit: float) -> dict | None:
    """Scale ratio from room-area labels; ``per_unit`` is paper metres per drawing unit.

    Returns ``{"ratio", "samples", "spread", "readings"}`` or None.
    """
    labels = area_labels(drawing)
    if not labels:
        return None
    box = drawing.bounds()
    if not box:
        return None
    x0, y0, x1, y1 = box
    w = int((x1 - x0) / CELL_PT) + 2
    h = int((y1 - y0) / CELL_PT) + 2
    if w * h > 12_000_000:
        return None  # a page this dense would take too long to raster in pure Python
    grid = bytearray(w * h)

    def cell(x: float, y: float) -> tuple[int, int]:
        return (int((x - x0) / CELL_PT), int((y - y0) / CELL_PT))

    def plot(x: int, y: int) -> None:
        if 0 <= x < w and 0 <= y < h:
            grid[y * w + x] = 1

    def line(a, b) -> None:
        (ax, ay), (bx, by) = cell(*a), cell(*b)
        steps = max(abs(bx - ax), abs(by - ay), 1)
        for i in range(steps + 1):
            t = i / steps
            x, y = round(ax + (bx - ax) * t), round(ay + (by - ay) * t)
            plot(x, y); plot(x + 1, y); plot(x, y + 1)  # two cells wide so thin walls seal

    for e in drawing.entities:
        if e.kind == "text":
            continue
        if e.kind in ("arc", "circle") and e.center and e.radius:
            a0 = math.radians(e.start_angle or 0.0)
            a1 = math.radians(e.end_angle if e.end_angle is not None else 360.0)
            if a1 < a0:
                a1 += 2 * math.pi
            n = max(8, int(e.radius * (a1 - a0) / CELL_PT))
            pts = [(e.center[0] + e.radius * math.cos(a0 + (a1 - a0) * i / n),
                    e.center[1] + e.radius * math.sin(a0 + (a1 - a0) * i / n)) for i in range(n + 1)]
            for p, q in zip(pts, pts[1:]):
                line(p, q)
            continue
        for p, q in e.segments():
            line(p, q)

    readings = []
    page_cells = w * h
    for label, real_m2 in labels:
        count = _room_cells(grid, w, h, cell, label, page_cells)
        if count is None:
            continue
        paper_m2 = count * (CELL_PT * per_unit) ** 2
        readings.append((label.text, real_m2, count, math.sqrt(real_m2 / paper_m2)))
    if not readings:
        return None
    # Rooms whose readings agree are the ones the fill measured correctly; a
    # leak into the corridor or a fill trapped inside a desk lands far away.
    ratios = sorted(r[3] for r in readings)
    best = max((sorted(v for v in ratios if abs(v - c) <= 0.12 * c) for c in ratios), key=len)
    median = statistics.median(best)
    spread = (max(best) - min(best)) / median if median else 1.0
    return {"ratio": median, "samples": len(readings), "agreeing": len(best), "spread": spread,
            "readings": [(t, real, round(ratio, 1)) for t, real, _, ratio in readings]}


def _room_cells(grid: bytearray, w: int, h: int, cell, label: Entity, page_cells: int) -> int | None:
    """Fill from several points around the label and keep the reading they agree on.

    The label's anchor can sit on a glyph of a neighbouring symbol, or inside a
    piece of furniture drawn as a closed outline. Seeds are spread along and
    around the label; fills that stay tiny were trapped, fills that swallow the
    page leaked, and the median of the rest is the room.
    """
    h_pt = max(label.height or 6.0, 4.0)
    x, y = label.points[0]
    rad = math.radians(label.rotation)
    ux, uy = math.cos(rad), math.sin(rad)
    along = [0.0, 2 * h_pt, 4 * h_pt, -2 * h_pt]
    across = [0.5 * h_pt, -1.5 * h_pt, 2.5 * h_pt]
    counts = []
    seen: set[tuple[int, int]] = set()
    for a in along:
        for b in across:
            sx, sy = cell(x + ux * a - uy * b, y + uy * a + ux * b)
            if (sx, sy) in seen:
                continue
            seen.add((sx, sy))
            snapshot = bytearray(grid)
            n = _flood(snapshot, w, h, sx, sy)
            if MIN_ROOM_CELLS <= n <= MAX_ROOM_SHARE * page_cells:
                counts.append(n)
    if len(counts) < 2:
        return None
    return int(statistics.median(counts))


def _flood(grid: bytearray, w: int, h: int, sx: int, sy: int) -> int:
    """Cells reachable from (sx, sy) without crossing linework; marks them as it goes."""
    if not (0 <= sx < w and 0 <= sy < h) or grid[sy * w + sx]:
        # The label's anchor may sit on a glyph or a wall; try just beside it.
        for dx, dy in ((2, 0), (-2, 0), (0, 2), (0, -2), (4, 4)):
            if 0 <= sx + dx < w and 0 <= sy + dy < h and not grid[(sy + dy) * w + sx + dx]:
                sx, sy = sx + dx, sy + dy
                break
        else:
            return 0
    count = 0
    queue = deque([(sx, sy)])
    grid[sy * w + sx] = 2
    limit = int(MAX_ROOM_SHARE * w * h) + 1
    while queue:
        x, y = queue.popleft()
        count += 1
        if count > limit:
            return count
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h:
                i = ny * w + nx
                if grid[i] == 0:
                    grid[i] = 2
                    queue.append((nx, ny))
    return count
