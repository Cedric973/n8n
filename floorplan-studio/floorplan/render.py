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
from .geometry import Rect, Segment
from .metrics import text_width
from .units import format_area, format_dimensions, format_length, scale_bar_options
from .plan import Plan, PlacedRoom
from .sheet import Scale, Sheet, choose

from .levels import CLIENT, DIMENSION, LEVEL_INFO, TECHNICAL

INK = "#1b1b1b"
WALL = "#1b1b1b"          # exterior walls: the darkest, heaviest thing on the sheet
WALL_INTERIOR = "#3d3d3d"  # interior walls: a step lighter, and they are thinner too
GLASS = "#5f7f9c"          # window glazing lines: a quiet blue-grey, still clear in B&W
LIGHT = "#8a8a8a"
PAPER = "#ffffff"

LEFT_MARGIN, RIGHT_MARGIN = 9.0, 14.0
BOTTOM_MARGIN, TOP_MARGIN = 15.0, 9.0
TITLE_HEIGHT = 5.5


def build_scene(plan: Plan, show_dimensions: bool = True,
                sheet: str | Sheet | None = None,
                scale: str | Scale | None = None,
                level: str = TECHNICAL,
                drawing_number: str | None = None,
                revision: str = "A") -> Scene:
    """Draw ``plan`` onto a standard sheet at a standard architectural scale.

    ``level`` picks how much goes on the sheet: see :mod:`floorplan.levels`.
    """
    if level not in LEVEL_INFO:
        raise ValueError(f"unknown level {level!r}")
    bounds = plan.footprint.bounds
    extent = Rect(
        bounds.x - LEFT_MARGIN,
        bounds.y - BOTTOM_MARGIN,
        bounds.w + LEFT_MARGIN + RIGHT_MARGIN,
        bounds.h + BOTTOM_MARGIN + TOP_MARGIN,
    )
    chosen_sheet, chosen_scale = choose(
        extent.w, extent.h, plan.spec.units, sheet=sheet, scale=scale
    )
    scene = Scene(
        bounds=extent,
        title=plan.spec.title,
        sheet=chosen_sheet,
        scale=chosen_scale,
    )
    scene.level = level  # type: ignore[attr-defined]
    if level != CLIENT:
        _draw_floors(scene, plan)   # room tints help the technical reader; the client plan stays white
    _draw_walls(scene, plan)
    _punch_openings(scene, plan)
    _draw_symbols(scene, plan)
    _draw_fixtures(scene, plan)
    _draw_labels(scene, plan, level)
    if show_dimensions:
        _draw_dimensions(scene, plan, level)
    _draw_north(scene, bounds)
    _draw_title_block(scene, plan, bounds, level, drawing_number or "A-101", revision)
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
            scene.rect(room.rect, fill=room.room_type.fill, layer="A-AREA")


def _draw_walls(scene: Scene, plan: Plan) -> None:
    spec = plan.spec
    on_boundary = {(e.x1, e.y1, e.x2, e.y2) for e in plan.footprint.edges()}
    for room in plan.rooms:
        if room.rect.area <= 0:
            continue
        for edge in room.rect.edges().values():
            if (edge.x1, edge.y1, edge.x2, edge.y2) in on_boundary:
                continue  # the exterior shell is drawn once, below
            scene.rect(_band(edge, spec.interior_wall), fill=WALL_INTERIOR, layer="A-WALL")
    for edge in plan.footprint.edges():
        scene.rect(_band(edge, spec.exterior_wall), fill=WALL, layer="A-WALL")


def _opening_thickness(plan: Plan, kind: str) -> float:
    exterior = kind in ("entry", "garage", "window")
    return plan.spec.exterior_wall if exterior else plan.spec.interior_wall


def _punch_openings(scene: Scene, plan: Plan) -> None:
    """Erase the wall where each opening sits, leaving the jambs intact."""
    for opening in plan.openings:
        thickness = _opening_thickness(plan, opening.kind) + 0.02
        scene.rect(
            _band(opening.segment, thickness, extend=False), fill=PAPER, layer="A-OPEN"
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
    scene.line(*hinge, *tip, stroke=INK, width=HAIRLINE * 1.6, layer="A-DOOR")
    start = math.atan2(tip[1] - hinge[1], tip[0] - hinge[0])
    end = math.atan2(latch[1] - hinge[1], latch[0] - hinge[0])
    if end - start > math.pi:
        end -= 2 * math.pi
    elif start - end > math.pi:
        end += 2 * math.pi
    scene.arc(
        hinge[0], hinge[1], width, start, end,
        stroke=LIGHT, width=HAIRLINE, layer="A-DOOR",
    )


def _draw_cased(scene: Scene, plan: Plan, opening) -> None:
    """A cased opening: no leaf, just the jamb ticks."""
    seg = opening.segment
    thickness = _opening_thickness(plan, opening.kind)
    for point in ((seg.x1, seg.y1), (seg.x2, seg.y2)):
        if seg.vertical:
            scene.line(
                point[0] - thickness / 2, point[1], point[0] + thickness / 2, point[1],
                stroke=WALL, width=HAIRLINE * 1.4, layer="A-DOOR",
            )
        else:
            scene.line(
                point[0], point[1] - thickness / 2, point[0], point[1] + thickness / 2,
                stroke=WALL, width=HAIRLINE * 1.4, layer="A-DOOR",
            )


def _draw_window(scene: Scene, plan: Plan, opening) -> None:
    """The conventional symbol: an opening in the wall, closed by two thin
    glazing lines. Nothing about it looks like wall, at any zoom."""
    seg = opening.segment
    t = _opening_thickness(plan, opening.kind)
    # Jambs: short dark ticks across the wall at each end of the opening.
    for point in ((seg.x1, seg.y1), (seg.x2, seg.y2)):
        if seg.vertical:
            scene.line(point[0] - t / 2, point[1], point[0] + t / 2, point[1],
                       stroke=WALL, width=HAIRLINE * 1.6, layer="A-WIND")
        else:
            scene.line(point[0], point[1] - t / 2, point[0], point[1] + t / 2,
                       stroke=WALL, width=HAIRLINE * 1.6, layer="A-WIND")
    # Glazing: two parallel lines a quarter of the wall in from each face.
    for offset in (-t / 4, t / 4):
        if seg.vertical:
            scene.line(seg.x1 + offset, seg.y1, seg.x1 + offset, seg.y2,
                       stroke=GLASS, width=HAIRLINE * 0.9, layer="A-WIND")
        else:
            scene.line(seg.x1, seg.y1 + offset, seg.x2, seg.y1 + offset,
                       stroke=GLASS, width=HAIRLINE * 0.9, layer="A-WIND")


def _draw_garage(scene: Scene, plan: Plan, opening) -> None:
    seg = opening.segment
    thickness = _opening_thickness(plan, opening.kind)
    for offset in (-thickness / 2, thickness / 2):
        if seg.vertical:
            scene.line(seg.x1 + offset, seg.y1, seg.x1 + offset, seg.y2,
                       stroke=WALL, width=HAIRLINE * 1.4, layer="A-DOOR")
        else:
            scene.line(seg.x1, seg.y1 + offset, seg.x2, seg.y1 + offset,
                       stroke=WALL, width=HAIRLINE * 1.4, layer="A-DOOR")
    for i in range(1, 4):  # panel divisions
        t = i / 4.0
        px, py = seg.point_at(t)
        if seg.vertical:
            scene.line(px - thickness / 2, py, px + thickness / 2, py,
                       stroke=LIGHT, width=HAIRLINE, layer="A-DOOR")
        else:
            scene.line(px, py - thickness / 2, px, py + thickness / 2,
                       stroke=LIGHT, width=HAIRLINE, layer="A-DOOR")


# --------------------------------------------------------------------------
# labels
# --------------------------------------------------------------------------

MIN_LABEL = 0.34  # feet of cap height below which a label is not worth drawing


def _fit(value: str, available: float, preferred: float, bold: bool = False) -> float:
    """Largest cap height at or below ``preferred`` that fits ``value``."""
    unit = text_width(value, 1.0, bold)
    if unit <= 0:
        return preferred
    return min(preferred, available / unit)


def _stack(cx: float, cy: float, offset: float, rotate: float) -> tuple[float, float]:
    """Move ``offset`` perpendicular to a baseline at ``rotate`` degrees.

    Label lines must stack across their own reading direction; offsetting in y
    regardless of rotation piles the lines of a rotated label on top of one
    another.
    """
    angle = math.radians(rotate)
    return (cx - offset * math.sin(angle), cy + offset * math.cos(angle))


def _draw_labels(scene: Scene, plan: Plan, level: str = TECHNICAL) -> None:
    for room in plan.rooms:
        if room.rect.area <= 0:
            continue
        net = room.net_rect(plan.spec, plan.footprint)
        cx, cy = room.rect.center
        upright = net.h <= net.w * 1.5 or net.w >= 7.0
        rotate = 0.0 if upright else 90.0
        along = (net.w if upright else net.h) * 0.88   # keep clear of the walls
        across = (net.h if upright else net.w) * 0.88

        name = room.label.upper()
        size = _fit(name, along, 0.78, bold=True)
        if size < MIN_LABEL or across < 1.6 * size:
            continue  # no room for a legible label
        # A door swinging into a narrow room reaches the middle of it; the
        # label steps along the room's long axis until it is clear.
        cx, cy = _clear_of_swings(plan, room, net, cx, cy, text_width(name, size, True), size * 2.6, upright)

        units = plan.spec.units
        dims = format_dimensions(net.w, net.h, units)
        area = format_area(net.area, units)
        detail_size = min(size * 0.7, _fit(dims, along, size * 0.7), _fit(area, along, size * 0.7))
        if level == CLIENT:
            # Name over area, nothing else. The room's sides are on the dimension plan.
            if across >= 3.0 * size and detail_size >= MIN_LABEL:
                scene.text(*_stack(cx, cy, size * 0.45, rotate), name, size=size, bold=True,
                           color=INK, rotate=rotate, layer="A-TEXT")
                scene.text(*_stack(cx, cy, -size * 0.65, rotate), area, size=detail_size,
                           color=LIGHT, rotate=rotate, layer="A-TEXT")
            else:
                scene.text(cx, cy, name, size=size, bold=True, color=INK,
                           rotate=rotate, layer="A-TEXT")
        elif across >= 4.2 * size and detail_size >= MIN_LABEL:
            scene.text(*_stack(cx, cy, size * 0.80, rotate), name, size=size, bold=True,
                       color=INK, rotate=rotate, layer="A-TEXT")
            scene.text(*_stack(cx, cy, -size * 0.30, rotate), dims, size=detail_size,
                       color=LIGHT, rotate=rotate, layer="A-TEXT")
            scene.text(*_stack(cx, cy, -size * 1.30, rotate), area, size=detail_size,
                       color=LIGHT, rotate=rotate, layer="A-TEXT")
        else:
            scene.text(cx, cy, name, size=size, bold=True, color=INK,
                       rotate=rotate, layer="A-TEXT")


def _swing_boxes(plan: Plan, room: PlacedRoom) -> list[Rect]:
    """The squares each door swings through inside ``room``."""
    boxes = []
    for opening in plan.openings:
        # A door swings into the first room it lists (see _swing_normal); the
        # room on the other side only sees the opening.
        if opening.kind == "window" or not opening.rooms or opening.rooms[0] != room.index:
            continue
        seg = opening.segment
        w = seg.length
        mx, my = seg.midpoint
        nx, ny = _swing_normal(plan, opening)
        if seg.vertical:
            boxes.append(Rect(mx if nx > 0 else mx - w, my - w / 2.0, w, w))
        else:
            boxes.append(Rect(mx - w / 2.0, my if ny > 0 else my - w, w, w))
    return boxes


def _clear_of_swings(plan: Plan, room: PlacedRoom, net: Rect, cx: float, cy: float,
                     box_w: float, box_h: float, upright: bool) -> tuple[float, float]:
    """Move a label's centre along the room's long axis until its box clears
    every door swing, or leave it where it was if nothing clears."""
    swings = _swing_boxes(plan, room)
    if not swings:
        return cx, cy
    if not upright:
        box_w, box_h = box_h, box_w

    def clear(x, y) -> bool:
        box = Rect(x - box_w / 2.0, y - box_h / 2.0, box_w, box_h)
        return not any(_overlaps(box, sw) for sw in swings)

    if clear(cx, cy):
        return cx, cy
    along_x = net.w >= net.h
    limit = (net.w - box_w) / 2.0 if along_x else (net.h - box_h) / 2.0
    step = 0.25
    k = 1
    while k * step <= max(limit, 0.0):
        for sign in (1.0, -1.0):
            x, y = (cx + sign * k * step, cy) if along_x else (cx, cy + sign * k * step)
            if clear(x, y):
                return x, y
        k += 1
    return cx, cy


def _overlaps(a: Rect, b: Rect) -> bool:
    return a.x < b.x2 and b.x < a.x2 and a.y < b.y2 and b.y < a.y2


# --------------------------------------------------------------------------
# fixtures: the few symbols that make a room read as what it is
# --------------------------------------------------------------------------

FIXTURE = "#6f6f6f"


def _draw_fixtures(scene: Scene, plan: Plan) -> None:
    """A bed in each bedroom, the sanitary set in each bath, a counter run
    in the kitchen. Nothing that would fight the label for the room's middle."""
    for room in plan.rooms:
        if room.rect.area <= 0:
            continue
        net = room.net_rect(plan.spec, plan.footprint)
        key = room.type_key
        if key in ("bedroom", "primary_bedroom"):
            _place_bed(scene, plan, room, net, king=(key == "primary_bedroom"))
        elif key in ("bathroom", "primary_bath", "powder"):
            _place_bath(scene, plan, room, net, tub=(key != "powder"))
        elif key == "kitchen":
            _place_kitchen(scene, plan, room, net)


def _free_walls(plan: Plan, room: PlacedRoom, net: Rect) -> list[str]:
    """Sides of the room with no door in them, longest first."""
    doors = [o for o in plan.openings if o.kind != "window" and room.index in o.rooms]
    sides = {"south": net.y, "north": net.y2, "west": net.x, "east": net.x2}
    free = []
    for side, coord in sides.items():
        vertical = side in ("west", "east")
        blocked = any((o.segment.vertical == vertical) and
                      abs((o.segment.x1 if vertical else o.segment.y1) - coord) < 0.6
                      for o in doors)
        if not blocked:
            free.append(side)
    free.sort(key=lambda sd: -(net.h if sd in ("west", "east") else net.w))
    return free


def _against(net: Rect, side: str, along: float, across: float, offset: float = 0.0) -> Rect:
    """A rect of ``along`` x ``across`` centred on ``side`` of ``net``,
    shifted ``offset`` along that side."""
    if side == "south":
        return Rect(net.center[0] - along / 2.0 + offset, net.y, along, across)
    if side == "north":
        return Rect(net.center[0] - along / 2.0 + offset, net.y2 - across, along, across)
    if side == "west":
        return Rect(net.x, net.center[1] - along / 2.0 + offset, across, along)
    return Rect(net.x2 - across, net.center[1] - along / 2.0 + offset, across, along)


def _fits(rect: Rect, net: Rect, swings: list[Rect]) -> bool:
    inside = rect.x >= net.x - 1e-6 and rect.y >= net.y - 1e-6 and rect.x2 <= net.x2 + 1e-6 and rect.y2 <= net.y2 + 1e-6
    return inside and not any(_overlaps(rect, sw) for sw in swings)


def _outline(scene: Scene, r: Rect) -> None:
    scene.rect(r, stroke=FIXTURE, width=HAIRLINE, layer="A-FURN")


def _place_bed(scene: Scene, plan: Plan, room: PlacedRoom, net: Rect, king: bool) -> None:
    head, length = (6.3, 6.7) if king else (5.0, 6.7)
    swings = _swing_boxes(plan, room)
    for side in _free_walls(plan, room, net):
        bed = _against(net, side, head, length)
        if not _fits(bed, net, swings):
            continue
        _outline(scene, bed)
        # Pillows: a band along the headboard.
        if side == "south":
            scene.rect(Rect(bed.x + 0.3, bed.y + 0.3, bed.w - 0.6, 1.0), stroke=FIXTURE, width=HAIRLINE, layer="A-FURN")
        elif side == "north":
            scene.rect(Rect(bed.x + 0.3, bed.y2 - 1.3, bed.w - 0.6, 1.0), stroke=FIXTURE, width=HAIRLINE, layer="A-FURN")
        elif side == "west":
            scene.rect(Rect(bed.x + 0.3, bed.y + 0.3, 1.0, bed.h - 0.6), stroke=FIXTURE, width=HAIRLINE, layer="A-FURN")
        else:
            scene.rect(Rect(bed.x2 - 1.3, bed.y + 0.3, 1.0, bed.h - 0.6), stroke=FIXTURE, width=HAIRLINE, layer="A-FURN")
        for offset in ((head + 1.6) / 2.0, -(head + 1.6) / 2.0):
            stand = _against(net, side, 1.5, 1.5, offset)
            if _fits(stand, net, swings):
                _outline(scene, stand)
        return


def _place_bath(scene: Scene, plan: Plan, room: PlacedRoom, net: Rect, tub: bool) -> None:
    swings = _swing_boxes(plan, room)
    walls = _free_walls(plan, room, net)
    if not walls:
        return
    placed: list[Rect] = []

    def put(rect: Rect) -> bool:
        if _fits(rect, net, swings + placed):
            _outline(scene, rect)
            placed.append(rect)
            return True
        return False

    # Tub along the longest free wall, filling it when the wall is short.
    if tub:
        side = walls[0]
        run = net.h if side in ("west", "east") else net.w
        length = min(5.5, run - 0.2)
        if length >= 4.0:
            put(_against(net, side, length, 2.5))
    # WC and basin on the next wall, or the same one when there is only one.
    side = walls[1] if len(walls) > 1 else walls[0]
    run = net.h if side in ("west", "east") else net.w
    wc = _against(net, side, 1.6, 2.3, -run / 2.0 + 1.2)
    if not put(wc):
        put(_against(net, side, 1.6, 2.3, run / 2.0 - 1.2))
    basin = _against(net, side, 2.0, 1.5, run / 2.0 - 1.4)
    if not put(basin):
        put(_against(net, side, 2.0, 1.5, -run / 2.0 + 1.4))


def _place_kitchen(scene: Scene, plan: Plan, room: PlacedRoom, net: Rect) -> None:
    """A counter run 2 ft deep along the longest door-free wall, with the sink
    and range drawn as squares in it."""
    swings = _swing_boxes(plan, room)
    for side in _free_walls(plan, room, net):
        run = (net.h if side in ("west", "east") else net.w) - 0.4
        counter = _against(net, side, run, 2.0)
        if run < 6.0 or not _fits(counter, net, swings):
            continue
        _outline(scene, counter)
        for offset, size in ((-run / 4.0, 2.0), (run / 4.0, 2.5)):   # sink, range
            unit = _against(net, side, size, 1.6, offset)
            if _fits(unit, net, swings):
                _outline(scene, unit)
        return


# --------------------------------------------------------------------------
# dimensions
# --------------------------------------------------------------------------

def _tick(scene: Scene, x: float, y: float, vertical: bool, size: float = 0.28) -> None:
    if vertical:
        scene.line(x - size, y - size, x + size, y + size, stroke=INK, width=HAIRLINE, layer="A-DIMS")
    else:
        scene.line(x - size, y - size, x + size, y + size, stroke=INK, width=HAIRLINE, layer="A-DIMS")


def _chain(scene: Scene, values: list[float], at: float, horizontal: bool,
           text_offset: float, units: str = "metric") -> None:
    """A dimension chain along one axis at offset ``at``."""
    if len(values) < 2:
        return
    if horizontal:
        scene.line(values[0], at, values[-1], at, stroke=INK, width=HAIRLINE, layer="A-DIMS")
    else:
        scene.line(at, values[0], at, values[-1], stroke=INK, width=HAIRLINE, layer="A-DIMS")
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
            scene.text(mid, at + text_offset, format_length(hi - lo, units), size=0.52,
                       color=INK, layer="A-DIMS")
        else:
            scene.text(at + text_offset, mid, format_length(hi - lo, units), size=0.52,
                       color=INK, rotate=90.0, layer="A-DIMS")


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


def _draw_dimensions(scene: Scene, plan: Plan, level: str = TECHNICAL) -> None:
    """Dimension the faces: room-by-room, then the overall run outboard.

    The client plan dimensions the south and west faces only — enough to read
    the building's size and its bays without ringing it in numbers. The
    dimension and technical plans do all four.
    """
    bounds = plan.footprint.bounds
    units = plan.spec.units
    faces = [f for f in FACES if not (level == CLIENT and f[2])]
    for _name, along_x, far in faces:
        divisions = _edge_divisions(plan, along_x, far)
        if len(divisions) < 2:
            continue
        sign = 1.0 if far else -1.0
        if along_x:
            face = bounds.y2 if far else bounds.y
        else:
            face = bounds.x2 if far else bounds.x
        _chain(scene, divisions, face + sign * 3.0, along_x, sign * 0.95, units)
        if len(divisions) > 2:
            _chain(scene, [divisions[0], divisions[-1]], face + sign * 6.0,
                   along_x, sign * 0.95, units)


# --------------------------------------------------------------------------
# sheet furniture
# --------------------------------------------------------------------------

def _draw_north(scene: Scene, bounds: Rect) -> None:
    cx, cy = bounds.x2 + 10.5, bounds.y2 - 2.5
    scene.polyline(
        [(cx, cy + 1.9), (cx + 0.85, cy - 1.5), (cx, cy - 0.75), (cx - 0.85, cy - 1.5)],
        closed=True, fill=INK, layer="G-ANNO",
    )
    scene.text(cx, cy + 2.4, "N", size=0.72, bold=True, color=INK, layer="G-ANNO")


def _draw_title_block(scene: Scene, plan: Plan, bounds: Rect, level: str = TECHNICAL,
                      drawing_number: str = "A-101", revision: str = "A") -> None:
    """Three ruled cells: identity, scale, issue. Nothing shares a cell.

    The client and dimension plans carry project information only. The
    technical plan adds the level's own caption and the seed, which is what
    lets a reviewer regenerate exactly this sheet.
    """
    top = bounds.y - 8.0
    box = Rect(bounds.x, top - TITLE_HEIGHT, bounds.w, TITLE_HEIGHT)
    scene.rect(box, stroke=INK, width=HAIRLINE * 1.5, layer="G-ANNO")

    identity = box.x + box.w * 0.54
    issue = box.x + box.w * 0.76
    for x in (identity, issue):
        scene.line(x, box.y, x, box.y2, stroke=INK, width=HAIRLINE, layer="G-ANNO")

    summary = plan.summary()
    pad = 0.7
    cell_w = identity - box.x - 2 * pad
    title_size = _fit(plan.spec.title, cell_w, 1.0, bold=True)
    scene.text(box.x + pad, box.y2 - 1.55, plan.spec.title, size=max(title_size, 0.45),
               bold=True, anchor="start", color=INK, layer="G-ANNO")

    caption = LEVEL_INFO[level][1]
    facts = (
        f"{caption}   ·   {summary['bedrooms']} BED   {summary['bathrooms']} BATH   "
        f"{format_area(plan.conditioned_sqft, plan.spec.units)}"
    )
    if level == TECHNICAL:
        facts += f"   ·   {summary['rooms']} ROOMS   ·   SEED {plan.seed}"
    facts_size = _fit(facts, cell_w, 0.6)
    scene.text(box.x + pad, box.y + 1.15, facts, size=max(facts_size, 0.3),
               anchor="start", color=INK, layer="G-ANNO")

    right_w = box.x2 - issue - 2 * pad
    scene.text(box.x2 - pad, box.y2 - 1.5, date.today().isoformat(),
               size=_fit(date.today().isoformat(), right_w, 0.6),
               anchor="end", color=LIGHT, layer="G-ANNO")
    number = f"{drawing_number}   REV {revision}"
    scene.text(box.x2 - pad, box.y + 1.15, number, size=_fit(number, right_w, 0.6),
               anchor="end", color=INK, layer="G-ANNO")
    cell = Rect(identity, box.y, issue - identity, box.h)
    _draw_scale_bar(scene, cell, plan.spec.units)
    if scene.scale is not None:
        label = f"SCALE  {scene.scale.label}"
        scene.text(cell.center[0], cell.y2 - 0.85, label,
                   size=_fit(label, cell.w * 0.92, 0.52), color=INK, layer="G-ANNO")


def _draw_scale_bar(scene: Scene, cell: Rect, units: str = "metric") -> None:
    """A ruled bar with its ends labelled, sized to a round length."""
    options = scale_bar_options(units)
    length, label = next(((n, t) for n, t in options if n <= cell.w * 0.72), options[-1])
    ticks = 5 if length >= options[0][0] * 0.5 else 4
    x0 = cell.center[0] - length / 2.0
    y0 = cell.y + cell.h * 0.46
    step = length / ticks
    for i in range(ticks):
        scene.rect(
            Rect(x0 + i * step, y0, step, cell.h * 0.13),
            fill=INK if i % 2 == 0 else PAPER,
            stroke=INK, width=HAIRLINE * 0.8, layer="G-ANNO",
        )
    # Labelled at each end rather than as one padded string, so the text can
    # never grow wider than the bar it belongs to.
    size = min(0.5, _fit("00 FT", cell.w * 0.4, 0.5))
    scene.text(x0, y0 - 0.8, "0", size=size, anchor="start", color=LIGHT, layer="G-ANNO")
    scene.text(x0 + length, y0 - 0.8, label, size=size, anchor="end",
               color=LIGHT, layer="G-ANNO")
