"""Turn a :class:`~floorplan.plan.Plan` into a drawable :class:`~floorplan.drawing.Scene`.

Walls are centred on room boundaries, so the footprint outline is the exterior
wall centreline and a room's gross rect runs to the middle of its walls. The
dimensions printed in each room are the net, inside-face figures.

Drawing order matters: fills, then wall bands, then openings punched through
those bands, then symbols and annotation on top.
"""

from __future__ import annotations

import math
from datetime import date

from .drawing import HAIRLINE, Path, Scene, Text
from .geometry import Rect, Segment, format_feet
from .plan import Plan, PlacedRoom

INK = "#1b1b1b"
WALL = "#2a2a2a"
LIGHT = "#8a8a8a"
PAPER = "#ffffff"

LEFT_MARGIN, RIGHT_MARGIN = 9.0, 14.0
BOTTOM_MARGIN, TOP_MARGIN = 15.0, 9.0
TITLE_HEIGHT = 5.5


def build_scene(plan: Plan, show_dimensions: bool = True) -> Scene:
    bounds = plan.footprint.bounds
    scene = Scene(
        bounds=Rect(
            bounds.x - LEFT_MARGIN,
            bounds.y - BOTTOM_MARGIN,
            bounds.w + LEFT_MARGIN + RIGHT_MARGIN,
            bounds.h + BOTTOM_MARGIN + TOP_MARGIN,
        ),
        title=plan.spec.title,
    )
    _draw_floors(scene, plan)
    _draw_walls(scene, plan)
    _punch_openings(scene, plan)
    _draw_symbols(scene, plan)
    _draw_labels(scene, plan)
    if show_dimensions:
        _draw_dimensions(scene, plan)
    _draw_north(scene, bounds)
    _draw_title_block(scene, plan, bounds)
    return scene


# --------------------------------------------------------------------------
# walls
# --------------------------------------------------------------------------

def _band(seg: Segment, thickness: float, extend: bool = True) -> Rect:
    """The filled rectangle representing a wall centred on ``seg``."""
    half = thickness / 2.0
    cap = half if extend else 0.0
    if seg.vertical:
        lo, hi = sorted((seg.y1, seg.y2))
        return Rect(seg.x1 - half, lo - cap, thickness, (hi - lo) + 2 * cap)
    lo, hi = sorted((seg.x1, seg.x2))
    return Rect(lo - cap, seg.y1 - half, (hi - lo) + 2 * cap, thickness)


def _draw_floors(scene: Scene, plan: Plan) -> None:
    for room in plan.rooms:
        if room.rect.area > 0:
            scene.rect(room.rect, fill=room.room_type.fill, layer="FLOOR")


def _draw_walls(scene: Scene, plan: Plan) -> None:
    spec = plan.spec
    on_boundary = {(e.x1, e.y1, e.x2, e.y2) for e in plan.footprint.edges()}
    for room in plan.rooms:
        if room.rect.area <= 0:
            continue
        for edge in room.rect.edges().values():
            if (edge.x1, edge.y1, edge.x2, edge.y2) in on_boundary:
                continue  # the exterior shell is drawn once, below
            scene.rect(_band(edge, spec.interior_wall), fill=WALL, layer="WALLS")
    for edge in plan.footprint.edges():
        scene.rect(_band(edge, spec.exterior_wall), fill=WALL, layer="WALLS")


def _opening_thickness(plan: Plan, kind: str) -> float:
    exterior = kind in ("entry", "garage", "window")
    return plan.spec.exterior_wall if exterior else plan.spec.interior_wall


def _punch_openings(scene: Scene, plan: Plan) -> None:
    """Erase the wall where each opening sits, leaving the jambs intact."""
    for opening in plan.openings:
        thickness = _opening_thickness(plan, opening.kind) + 0.02
        scene.rect(
            _band(opening.segment, thickness, extend=False), fill=PAPER, layer="OPENINGS"
        )


# --------------------------------------------------------------------------
# door and window symbols
# --------------------------------------------------------------------------

def _swing_normal(plan: Plan, opening) -> tuple[float, float]:
    """Unit vector pointing from the wall into the room the door swings into."""
    seg = opening.segment
    if not opening.rooms:
        return (0.0, 1.0) if seg.horizontal else (1.0, 0.0)
    target = plan.rooms[opening.rooms[0]]
    cx, cy = target.rect.center
    mx, my = seg.midpoint
    if seg.vertical:
        return (1.0, 0.0) if cx > mx else (-1.0, 0.0)
    return (0.0, 1.0) if cy > my else (0.0, -1.0)


def _draw_symbols(scene: Scene, plan: Plan) -> None:
    for opening in plan.openings:
        seg = opening.segment
        if opening.kind == "window":
            _draw_window(scene, plan, opening)
        elif opening.kind == "garage":
            _draw_garage(scene, plan, opening)
        elif opening.kind == "opening":
            _draw_cased(scene, plan, opening)
        else:
            _draw_door(scene, plan, opening)


def _draw_door(scene: Scene, plan: Plan, opening) -> None:
    seg = opening.segment
    width = seg.length
    if width <= 0:
        return
    nx, ny = _swing_normal(plan, opening)
    hinge = (seg.x1, seg.y1) if opening.hinge == "left" else (seg.x2, seg.y2)
    latch = (seg.x2, seg.y2) if opening.hinge == "left" else (seg.x1, seg.y1)
    tip = (hinge[0] + nx * width, hinge[1] + ny * width)
    scene.line(*hinge, *tip, stroke=INK, width=HAIRLINE * 1.6, layer="DOORS")
    start = math.atan2(tip[1] - hinge[1], tip[0] - hinge[0])
    end = math.atan2(latch[1] - hinge[1], latch[0] - hinge[0])
    if end - start > math.pi:
        end -= 2 * math.pi
    elif start - end > math.pi:
        end += 2 * math.pi
    scene.arc(
        hinge[0], hinge[1], width, start, end,
        stroke=LIGHT, width=HAIRLINE, layer="DOORS",
    )


def _draw_cased(scene: Scene, plan: Plan, opening) -> None:
    """A cased opening: no leaf, just the jamb ticks."""
    seg = opening.segment
    thickness = _opening_thickness(plan, opening.kind)
    for point in ((seg.x1, seg.y1), (seg.x2, seg.y2)):
        if seg.vertical:
            scene.line(
                point[0] - thickness / 2, point[1], point[0] + thickness / 2, point[1],
                stroke=WALL, width=HAIRLINE * 1.4, layer="DOORS",
            )
        else:
            scene.line(
                point[0], point[1] - thickness / 2, point[0], point[1] + thickness / 2,
                stroke=WALL, width=HAIRLINE * 1.4, layer="DOORS",
            )


def _draw_window(scene: Scene, plan: Plan, opening) -> None:
    seg = opening.segment
    thickness = _opening_thickness(plan, opening.kind)
    offsets = (-thickness / 2, 0.0, thickness / 2)
    for i, offset in enumerate(offsets):
        width = HAIRLINE * (1.4 if i != 1 else 0.9)
        if seg.vertical:
            scene.line(
                seg.x1 + offset, seg.y1, seg.x1 + offset, seg.y2,
                stroke=WALL if i != 1 else LIGHT, width=width, layer="WINDOWS",
            )
        else:
            scene.line(
                seg.x1, seg.y1 + offset, seg.x2, seg.y1 + offset,
                stroke=WALL if i != 1 else LIGHT, width=width, layer="WINDOWS",
            )


def _draw_garage(scene: Scene, plan: Plan, opening) -> None:
    seg = opening.segment
    thickness = _opening_thickness(plan, opening.kind)
    for offset in (-thickness / 2, thickness / 2):
        if seg.vertical:
            scene.line(seg.x1 + offset, seg.y1, seg.x1 + offset, seg.y2,
                       stroke=WALL, width=HAIRLINE * 1.4, layer="DOORS")
        else:
            scene.line(seg.x1, seg.y1 + offset, seg.x2, seg.y1 + offset,
                       stroke=WALL, width=HAIRLINE * 1.4, layer="DOORS")
    for i in range(1, 4):  # panel divisions
        t = i / 4.0
        px, py = seg.point_at(t)
        if seg.vertical:
            scene.line(px - thickness / 2, py, px + thickness / 2, py,
                       stroke=LIGHT, width=HAIRLINE, layer="DOORS")
        else:
            scene.line(px, py - thickness / 2, px, py + thickness / 2,
                       stroke=LIGHT, width=HAIRLINE, layer="DOORS")


# --------------------------------------------------------------------------
# labels
# --------------------------------------------------------------------------

def _draw_labels(scene: Scene, plan: Plan) -> None:
    for room in plan.rooms:
        if room.rect.area <= 0:
            continue
        net = room.net_rect(plan.spec, plan.footprint)
        cx, cy = room.rect.center
        upright = net.h <= net.w * 1.5 or net.w >= 7.0
        rotate = 0.0 if upright else 90.0
        along = net.w if upright else net.h
        across = net.h if upright else net.w

        name = room.label.upper()
        size = min(0.78, max(0.42, along / max(len(name) * 0.62, 1.0)))
        if across < 2.2 * size or along < size * 2:
            continue  # no room for a legible label

        detail = across >= 4.6 * size
        if detail:
            scene.text(cx, cy + size * 0.75, name, size=size, bold=True, color=INK,
                       rotate=rotate, layer="TEXT")
            scene.text(cx, cy - size * 0.35,
                       f"{format_feet(net.w)} x {format_feet(net.h)}",
                       size=size * 0.7, color=LIGHT, rotate=rotate, layer="TEXT")
            scene.text(cx, cy - size * 1.4, f"{round(net.area)} SF",
                       size=size * 0.7, color=LIGHT, rotate=rotate, layer="TEXT")
        else:
            scene.text(cx, cy - size * 0.35, name, size=size, bold=True, color=INK,
                       rotate=rotate, layer="TEXT")


# --------------------------------------------------------------------------
# dimensions
# --------------------------------------------------------------------------

def _tick(scene: Scene, x: float, y: float, vertical: bool, size: float = 0.28) -> None:
    if vertical:
        scene.line(x - size, y - size, x + size, y + size, stroke=INK, width=HAIRLINE, layer="DIMS")
    else:
        scene.line(x - size, y - size, x + size, y + size, stroke=INK, width=HAIRLINE, layer="DIMS")


def _chain(scene: Scene, values: list[float], at: float, horizontal: bool, text_offset: float) -> None:
    """A dimension chain along one axis at offset ``at``."""
    if len(values) < 2:
        return
    if horizontal:
        scene.line(values[0], at, values[-1], at, stroke=INK, width=HAIRLINE, layer="DIMS")
    else:
        scene.line(at, values[0], at, values[-1], stroke=INK, width=HAIRLINE, layer="DIMS")
    for value in values:
        if horizontal:
            _tick(scene, value, at, False)
        else:
            _tick(scene, at, value, True)
    for lo, hi in zip(values, values[1:]):
        if hi - lo < 1.5:
            continue
        mid = (lo + hi) / 2.0
        if horizontal:
            scene.text(mid, at + text_offset, format_feet(hi - lo), size=0.52,
                       color=INK, layer="DIMS")
        else:
            scene.text(at + text_offset, mid, format_feet(hi - lo), size=0.52,
                       color=INK, rotate=90.0, layer="DIMS")


#: The four faces a plan is dimensioned from, as (chain runs along x, far side).
FACES = (("south", True, False), ("north", True, True),
         ("west", False, False), ("east", False, True))


def _edge_divisions(plan: Plan, along_x: bool, far: bool) -> list[float]:
    """Coordinates where interior walls meet one outer face of the plan.

    The extent comes from the rooms that actually reach that face, not from the
    bounding box, so on an L- or U-shaped footprint the north and east chains
    span only the part of the building that is really there.
    """
    bounds = plan.footprint.bounds
    if along_x:
        face = bounds.y2 if far else bounds.y
    else:
        face = bounds.x2 if far else bounds.x

    values: set[float] = set()
    for room in plan.rooms:
        if room.rect.area <= 0:
            continue
        if along_x:
            near = room.rect.y2 if far else room.rect.y
            if abs(near - face) < 1e-4:
                values.update((room.rect.x, room.rect.x2))
        else:
            near = room.rect.x2 if far else room.rect.x
            if abs(near - face) < 1e-4:
                values.update((room.rect.y, room.rect.y2))
    return _collapse(sorted(values))


def _collapse(values: list[float], tol: float = 0.25) -> list[float]:
    """Merge division marks closer together than a dimension can usefully show."""
    out: list[float] = []
    for value in values:
        if out and value - out[-1] < tol:
            out[-1] = (out[-1] + value) / 2.0
        else:
            out.append(value)
    return out


def _draw_dimensions(scene: Scene, plan: Plan) -> None:
    """Dimension all four faces: room-by-room, then the overall run outboard."""
    bounds = plan.footprint.bounds
    for _name, along_x, far in FACES:
        divisions = _edge_divisions(plan, along_x, far)
        if len(divisions) < 2:
            continue
        sign = 1.0 if far else -1.0
        if along_x:
            face = bounds.y2 if far else bounds.y
        else:
            face = bounds.x2 if far else bounds.x
        _chain(scene, divisions, face + sign * 3.0, along_x, sign * 0.95)
        if len(divisions) > 2:
            _chain(scene, [divisions[0], divisions[-1]], face + sign * 6.0,
                   along_x, sign * 0.95)


# --------------------------------------------------------------------------
# sheet furniture
# --------------------------------------------------------------------------

def _draw_north(scene: Scene, bounds: Rect) -> None:
    cx, cy = bounds.x2 + 10.5, bounds.y2 - 2.5
    scene.polyline(
        [(cx, cy + 1.9), (cx + 0.85, cy - 1.5), (cx, cy - 0.75), (cx - 0.85, cy - 1.5)],
        closed=True, fill=INK, layer="SHEET",
    )
    scene.text(cx, cy + 2.4, "N", size=0.72, bold=True, color=INK, layer="SHEET")


def _draw_title_block(scene: Scene, plan: Plan, bounds: Rect) -> None:
    top = bounds.y - 8.0
    box = Rect(bounds.x, top - TITLE_HEIGHT, bounds.w, TITLE_HEIGHT)
    scene.rect(box, stroke=INK, width=HAIRLINE * 1.5, layer="SHEET")
    scene.line(box.x, box.y2 - 2.2, box.x2, box.y2 - 2.2, stroke=INK,
               width=HAIRLINE, layer="SHEET")

    summary = plan.summary()
    scene.text(box.x + 0.8, box.y2 - 1.55, plan.spec.title, size=1.0, bold=True,
               anchor="start", color=INK, layer="SHEET")
    baths = summary["bathrooms"]
    facts = (
        f"{summary['bedrooms']} BED   {baths} BATH   "
        f"{summary['conditioned_sqft']} SF CONDITIONED   {summary['rooms']} ROOMS"
    )
    scene.text(box.x + 0.8, box.y + 1.15, facts, size=0.6, anchor="start",
               color=INK, layer="SHEET")
    scene.text(box.x2 - 0.8, box.y2 - 1.5, date.today().isoformat(), size=0.6,
               anchor="end", color=LIGHT, layer="SHEET")
    scene.text(box.x2 - 0.8, box.y + 1.15, f"SCHEMATIC  ·  SEED {plan.seed}",
               size=0.6, anchor="end", color=LIGHT, layer="SHEET")
    _draw_scale_bar(scene, box)


def _draw_scale_bar(scene: Scene, box: Rect) -> None:
    length, ticks = 10.0, 5
    x0 = box.center[0] - length / 2.0
    y0 = box.y + 1.4
    step = length / ticks
    for i in range(ticks):
        scene.rect(
            Rect(x0 + i * step, y0, step, 0.32),
            fill=INK if i % 2 == 0 else PAPER,
            stroke=INK,
            width=HAIRLINE * 0.8,
            layer="SHEET",
        )
    scene.text(x0, y0 - 0.85, "0", size=0.5, color=LIGHT, layer="SHEET")
    scene.text(x0 + length, y0 - 0.85, "10 FT", size=0.5, color=LIGHT, layer="SHEET")
