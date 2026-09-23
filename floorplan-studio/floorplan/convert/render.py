"""Draw an analysed :class:`~floorplan.convert.model.Drawing` on a standard sheet.

The generator's scene builder knows rooms; this one knows entities and roles.
It reuses the same sheet furniture — title block, scale bar, north arrow —
and the same backends, so a re-issued plan is indistinguishable in finish
from a generated one, with one deliberate exception: anything the analyzer
*inferred* is drawn dashed, so a reader can tell recognised geometry from
confirmed geometry at a glance.
"""

from __future__ import annotations

import math
import re
from datetime import date
from pathlib import Path

from ..drawing import HAIRLINE, Scene
from ..geometry import Rect
from ..levels import CLIENT, DIMENSION, LEVEL_INFO, TECHNICAL
from ..render import (GLASS, INK, LIGHT, TITLE_HEIGHT, WALL, WALL_INTERIOR, _chain, _collapse,
                      _draw_scale_bar, _fit)
from ..sheet import Scale, Sheet, choose
from ..units import DEFAULT_UNITS, FEET_PER_METRE, format_area
from .model import AIA_LAYER, Drawing, Entity, Provenance, Role

INFERRED_INK = "#8a5a00"
TITLE_GAP = 2.0                # feet between the drawing and the title block
INFERRED_DASH = (0.45, 0.2)   # feet
DEFAULT_WALL = 0.20            # metres, when a wall line has no measured thickness

FILL_BY_ROLE = {Role.WALL: WALL, Role.COLUMN: WALL, Role.STAIR: "#d9d9d9",
                Role.FURNITURE: "#ececec", Role.EQUIPMENT: "#e4e9ec"}


def build_drawing_scene(drawing: Drawing, sheet: str | Sheet | None = None,
                        scale: str | Scale | None = None, units: str = DEFAULT_UNITS,
                        keep_sheet_furniture: bool = False, level: str = TECHNICAL,
                        drawing_number: str | None = None, revision: str = "A") -> Scene:
    """``drawing`` must be in metres (the analyzer's output).

    ``level`` (see :mod:`floorplan.levels`) decides what is drawn: the client
    plan shows walls, openings, names and areas only, in plain black; the
    technical plan shows everything and marks what was inferred.
    """
    if level not in LEVEL_INFO:
        raise ValueError(f"unknown level {level!r}")
    content = [e for e in drawing.entities if keep_sheet_furniture or e.role != Role.SHEET]
    stacks = label_stacks([e for e in content if e.role == Role.TEXT])
    if level == CLIENT:
        labels = {id(e) for stack in stacks for e in stack}
        content = [e for e in content if e.role in CLIENT_ROLES or id(e) in labels]
    elif level == DIMENSION:
        content = [e for e in content if e.role != Role.OTHER or e.kind == "text"]
    if not content:
        raise ValueError("drawing has no content to draw")
    # On the presentation drawings each room label is set in the middle of
    # its room, wherever the source had it. The technical plan keeps the
    # source's positions, as it keeps everything else the source did.
    moved = {} if level == TECHNICAL else recentre_labels(drawing, stacks)
    box = _bounds(content)
    f = FEET_PER_METRE
    bounds = Rect(box[0] * f, box[1] * f, (box[2] - box[0]) * f, (box[3] - box[1]) * f)
    # Our own chains go where the source has none to show: always on the
    # client plan, which drops the source's dimensions, and on the others
    # only when the source never had any. A plan is not dimensioned twice.
    chains = exterior_chains(drawing) if level == CLIENT or not drawing.by_role(Role.DIMENSION) else ([], [])
    # Room for the north arrow, the title block and, on the south and west
    # faces, the dimension chains measured off the reconstructed walls.
    left, right, top = (1.5 + CHAIN_SPACE if chains[1] else 1.5), 8.0, 1.5
    below = CHAIN_SPACE if chains[0] else 0.0
    bottom = TITLE_GAP + TITLE_HEIGHT + 1.0 + below
    extent = Rect(bounds.x - left, bounds.y - bottom, bounds.w + left + right, bounds.h + bottom + top)
    chosen_sheet, chosen_scale = choose(extent.w, extent.h, units, sheet=sheet, scale=scale)
    scene = Scene(bounds=extent, title=Path(drawing.source).stem or "Converted plan",
                  sheet=chosen_sheet, scale=chosen_scale)

    scene.level = level  # type: ignore[attr-defined]
    for role in (Role.OTHER, Role.GRID, Role.FURNITURE, Role.EQUIPMENT, Role.STAIR,
                 Role.COLUMN, Role.WALL, Role.WINDOW, Role.DOOR, Role.DIMENSION, Role.TEXT):
        for e in content:
            if e.role == role:
                _draw_entity(scene, e, f, level, moved.get(id(e)))
    _draw_chains(scene, chains, bounds, f, units)
    _north(scene, bounds)
    _draw_title_block(scene, drawing, Rect(bounds.x, bounds.y - below, bounds.w, bounds.h + below),
                      units, level, drawing_number or "A-101", revision)
    return scene


MIN_TEXT_PAPER_M = 0.002   # 2 mm on the printed sheet
CLIENT_ROLES = {Role.WALL, Role.WINDOW, Role.DOOR, Role.COLUMN, Role.STAIR}


AREA_TEXT = re.compile(r"\d+(?:[.,]\d+)?\s*m[²2]\b", re.IGNORECASE)
NOT_A_NAME = re.compile(r"ceil|c\.h|height|\d\s*x\s*\d|:", re.IGNORECASE)


def _is_area(e: Entity) -> bool:
    return bool(e.text) and not e.meta.get("unreadable") and bool(AREA_TEXT.search(e.text))


def _is_name(e: Entity) -> bool:
    text = (e.text or "").strip()
    if not text or e.meta.get("unreadable") or NOT_A_NAME.search(text):
        return False
    return len(text) <= 28 and not re.fullmatch(r"[\d.,\s]+", text)


def label_stacks(texts: list[Entity]) -> list[list[Entity]]:
    """Room labels as stacks: the name lines, top to bottom, then the area.

    A room label on a CAD plan is a stack — one or two name lines, then the
    area, then the ceiling height. The area is the anchor; a name is any short
    text whose baseline sits within two line heights above a kept line and
    whose centre lies over it. Captions with no area under them (a furniture
    tag, a "to be precised" note) are not rooms and stay off the client plan.
    """
    stacks = [[e] for e in texts if _is_area(e)]
    owner = {id(stack[0]): stack for stack in stacks}
    names = [e for e in texts if _is_name(e) and id(e) not in owner]
    for _ in range(2):   # a name line above a name line above the area
        added = False
        for e in names:
            if id(e) in owner:
                continue
            box = _text_box(e)
            if not box:
                continue
            height = box[3] - box[1]
            for kid, stack in list(owner.items()):
                k = next(m for m in stack if id(m) == kid)
                kb = _text_box(k)
                if not kb:
                    continue
                gap = box[1] - kb[3]
                overlap = min(box[2], kb[2]) - max(box[0], kb[0])
                if -0.5 * height <= gap <= 1.5 * height and overlap > -height:
                    stack.insert(0, e)
                    owner[id(e)] = stack
                    added = True
                    break
        if not added:
            break
    return stacks


def room_labels(texts: list[Entity]) -> set[int]:
    """The texts a client plan keeps: every area and the names stacked over it."""
    return {id(e) for stack in label_stacks(texts) for e in stack}


ROOM_CELL = 0.05   # metres; the grid the room fill runs on


def recentre_labels(drawing: Drawing, stacks: list[list[Entity]]) -> dict[int, tuple[float, float]]:
    """Where each label stack should sit: the middle of the room it names.

    Every line the source drew is plotted on a grid — walls, but also the
    glass partitions and pods that bound a room without being walls — and
    the room is flooded from several points around the label. The fill is
    trusted only when its area agrees with the area printed in the label: a
    fill that leaked through an undrawn opening into the corridor, or was
    trapped inside a desk, measures something else, and the label stays
    where the source put it. Returns new anchor points keyed by entity id.
    """
    if not stacks:
        return {}
    walls = drawing.by_role(Role.WALL)
    boxes = [b for b in (e.bounds() for e in walls) if b]
    if not boxes:
        return {}
    x0, y0 = min(b[0] for b in boxes) - 0.5, min(b[1] for b in boxes) - 0.5
    x1, y1 = max(b[2] for b in boxes) + 0.5, max(b[3] for b in boxes) + 0.5
    w, h = int((x1 - x0) / ROOM_CELL) + 2, int((y1 - y0) / ROOM_CELL) + 2
    if w * h > 3_000_000:
        return {}
    grid = bytearray(w * h)

    def cell(x, y):
        return int((x - x0) / ROOM_CELL), int((y - y0) / ROOM_CELL)

    def plot_line(a, b, thick=0):
        (ax, ay), (bx, by) = cell(*a), cell(*b)
        n = max(abs(bx - ax), abs(by - ay), 1)
        for i in range(n + 1):
            cx, cy = round(ax + (bx - ax) * i / n), round(ay + (by - ay) * i / n)
            for dx in range(-thick, thick + 1):
                for dy in range(-thick, thick + 1):
                    if 0 <= cx + dx < w and 0 <= cy + dy < h:
                        grid[(cy + dy) * w + cx + dx] = 1

    for e in drawing.entities:
        if e.kind == "text" or e.role in (Role.SHEET, Role.DIMENSION) or e.meta.get("hatch_stroke"):
            continue
        if e.role == Role.WALL and e.filled and e.closed:
            b = e.bounds()
            cx0, cy0 = cell(b[0], b[1]); cx1, cy1 = cell(b[2], b[3])
            for cy in range(max(cy0, 0), min(cy1, h - 1) + 1):
                row = cy * w
                for cx in range(max(cx0, 0), min(cx1, w - 1) + 1):
                    grid[row + cx] = 1
            continue
        thick = max(0, int((e.thickness or 0.0) / ROOM_CELL / 2)) if e.role == Role.WALL else 0
        if e.kind in ("arc", "circle") and e.center and e.radius:
            a0 = math.radians(e.start_angle or 0.0)
            a1 = math.radians(e.end_angle if e.end_angle is not None else 360.0)
            if a1 < a0:
                a1 += 2 * math.pi
            n = max(8, int(e.radius * (a1 - a0) / ROOM_CELL))
            pts = [(e.center[0] + e.radius * math.cos(a0 + (a1 - a0) * i / n),
                    e.center[1] + e.radius * math.sin(a0 + (a1 - a0) * i / n)) for i in range(n + 1)]
            for a, b in zip(pts, pts[1:]):
                plot_line(a, b)
            continue
        for a, b in e.segments():
            plot_line(a, b, thick)
        if e.meta.get("leaf"):
            plot_line(tuple(e.meta["leaf"][0]), tuple(e.meta["leaf"][1]))

    moved: dict[int, tuple[float, float]] = {}
    anchors = []
    for stack in stacks:
        centres = [_text_box(e) for e in stack]
        if any(c is None for c in centres):
            anchors.append(None)
            continue
        anchors.append((sum((c[0] + c[2]) / 2 for c in centres) / len(centres),
                        sum((c[1] + c[3]) / 2 for c in centres) / len(centres),
                        max(c[3] - c[1] for c in centres)))
    for n, stack in enumerate(stacks):
        printed = _printed_area(stack[-1].text or "")
        if printed is None or anchors[n] is None:
            continue
        sx, sy, height = anchors[n]
        others = [(ax, ay) for k, a in enumerate(anchors) if a and k != n for ax, ay, _ in [a]]
        best = None
        for dx, dy in ((0, 0), (0, -1.5 * height), (0, 1.5 * height), (-2 * height, 0), (2 * height, 0)):
            region = _flood(grid, w, h, *cell(sx + dx, sy + dy))
            if region is None:
                continue
            count, cx_sum, cy_sum, (bx0, by0, bx1, by1) = region
            error = abs(count * ROOM_CELL ** 2 - printed) / printed
            if error > 0.35 or (best is not None and error >= best[0]):
                continue
            # One room, one label: a region holding another room's label is
            # that room, however well its area happens to agree.
            rx0, ry0 = x0 + bx0 * ROOM_CELL, y0 + by0 * ROOM_CELL
            rx1, ry1 = x0 + (bx1 + 1) * ROOM_CELL, y0 + (by1 + 1) * ROOM_CELL
            if any(rx0 <= ax <= rx1 and ry0 <= ay <= ry1 for ax, ay in others):
                continue
            best = (error, count, cx_sum, cy_sum)
        if best is None:
            continue
        _, count, cx_sum, cy_sum = best
        gx, gy = x0 + (cx_sum / count + 0.5) * ROOM_CELL, y0 + (cy_sum / count + 0.5) * ROOM_CELL
        for e in stack:
            ex, ey = e.points[0]
            moved[id(e)] = (ex + gx - sx, ey + gy - sy)
    return moved


def _printed_area(text: str) -> float | None:
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*m[²2]", text, re.IGNORECASE)
    return float(m.group(1).replace(",", ".")) if m else None


def _flood(grid: bytearray, w: int, h: int, sx: int, sy: int, limit: int = 400_000):
    """Cells reachable from (sx, sy): (count, sum x, sum y, cell bbox), or
    None if the fill hits the grid edge (the label is outside every room)."""
    if not (0 <= sx < w and 0 <= sy < h):
        return None
    if grid[sy * w + sx]:
        for dx, dy in ((0, -3), (0, 3), (-3, 0), (3, 0)):
            if 0 <= sx + dx < w and 0 <= sy + dy < h and not grid[(sy + dy) * w + sx + dx]:
                sx, sy = sx + dx, sy + dy
                break
        else:
            return None
    seen = bytearray(w * h)
    stack = [sy * w + sx]
    seen[stack[0]] = 1
    count = xs = ys = 0
    bx0 = by0 = 10 ** 9
    bx1 = by1 = -1
    while stack:
        i = stack.pop()
        cx, cy = i % w, i // w
        if cx == 0 or cy == 0 or cx == w - 1 or cy == h - 1:
            return None
        count += 1; xs += cx; ys += cy
        bx0, by0, bx1, by1 = min(bx0, cx), min(by0, cy), max(bx1, cx), max(by1, cy)
        if count > limit:
            return None
        for j in (i + 1, i - 1, i + w, i - w):
            if not seen[j] and not grid[j]:
                seen[j] = 1
                stack.append(j)
    return count, xs, ys, (bx0, by0, bx1, by1)


def exterior_chains(drawing: Drawing) -> tuple[list[float], list[float]]:
    """Dimension marks along the south and west faces, in metres.

    Read off the reconstructed walls. The face is the longest straight
    exterior wall on that side (an oblique or stepped wall never is); a mark
    is where a wall running the other way meets it, and each end of a window
    or door sitting in it. The values are measured at whatever scale the
    analyzer established, so on a source with an inferred scale they inherit
    that uncertainty.
    """
    rects = [e.bounds() for e in drawing.by_role(Role.WALL)
             if e.kind == "polyline" and e.closed and e.filled and e.bounds()]
    if len(rects) < 4:
        return [], []
    openings = [e for e in drawing.entities if e.role == Role.WINDOW and e.meta.get("symbol")]

    def face(axis: int) -> list[float]:
        other = 1 - axis
        # The dominant wall on the low side: the 10 cm slice of the other
        # coordinate that carries the most wall length running along the face.
        along_rects = [b for b in rects if (b[axis + 2] - b[axis]) > (b[other + 2] - b[other])]
        weight: dict[int, float] = {}
        for b in along_rects:
            weight[int(b[other] / 0.1)] = weight.get(int(b[other] / 0.1), 0.0) + (b[axis + 2] - b[axis])
        if not weight:
            return []
        low_bucket = min(k for k, v in weight.items() if v >= 0.5 * max(weight.values()))
        low = low_bucket * 0.1
        band = [b for b in along_rects if low - 0.05 <= b[other] <= low + 0.6]
        if not band:
            return []
        marks = {min(b[axis] for b in band), max(b[axis + 2] for b in band)}
        for b in rects:
            along, across = b[axis + 2] - b[axis], b[other + 2] - b[other]
            if across >= 0.9 and along < across and b[other] <= low + 0.9 and b[other + 2] >= low:
                marks.add((b[axis] + b[axis + 2]) / 2.0)
        for e in openings:
            (ax, ay), (bx, by) = e.points
            if abs((ay if axis == 0 else ax) - (low + 0.15)) <= 0.45 and abs((ay - by) if axis == 0 else (ax - bx)) < 0.05:
                marks.update((min(ax, bx), max(ax, bx)) if axis == 0 else (min(ay, by), max(ay, by)))
        lo, hi = min(marks), max(marks)
        inner = [m for m in _collapse(sorted(marks), tol=0.3) if lo + 0.3 <= m <= hi - 0.3]
        return [lo] + inner + [hi]

    return face(0), face(1)


CHAIN_SPACE = 6.5   # feet the chains need outboard of the drawing


def _draw_chains(scene: Scene, chains, bounds: Rect, f: float, units: str) -> None:
    """The bay chain 3 ft off the drawing's edge, the overall run 6 ft off."""
    south, west = chains
    if south:
        _chain(scene, [v * f for v in south], bounds.y - 3.0, True, -0.95, units)
        if len(south) > 2:
            _chain(scene, [south[0] * f, south[-1] * f], bounds.y - 6.0, True, -0.95, units)
    if west:
        _chain(scene, [v * f for v in west], bounds.x - 3.0, False, -0.95, units)
        if len(west) > 2:
            _chain(scene, [west[0] * f, west[-1] * f], bounds.x - 6.0, False, -0.95, units)



def _text_box(e: Entity) -> tuple[float, float, float, float] | None:
    """A text's footprint from its origin, height and an average glyph width.

    Readers give a text one anchor point, so its own bounds are that point.
    The label rule needs to know whether two lines sit over each other, so
    the width is estimated at 0.55 heights per character — Helvetica's
    average — laid out from the anchor in the text's anchor direction.
    """
    if not e.points or not e.text:
        return None
    x, y = e.points[0]
    height = e.height or 0.25
    width = 0.55 * height * len(e.text)
    anchor = str(e.meta.get("anchor", "start"))
    if anchor == "middle":
        x -= width / 2.0
    elif anchor == "end":
        x -= width
    return (x, y, x + width, y + height)


def _is_room_label(e: Entity) -> bool:
    """Kept for callers that classify one text on its own."""
    return _is_area(e) or _is_name(e)


def display_text(text: str) -> str:
    """Put back the spaces a PDF font without a space glyph dropped.

    "KitchenLunchRoom" and "Meetingroom1" are one word each to the reader
    only because the export had no space to emit. Word boundaries a reader
    can still see — a lower-case letter before a capital, a letter before a
    digit — are restored. Text that already has spaces is left alone.
    """
    if " " in text.strip():
        return text
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    text = re.sub(r"(?<=[A-Za-z][A-Za-z])(?=\d)", " ", text)   # not the 2 of m2
    return " ".join(_split_words(w) for w in text.split(" "))


# Words a room name is made of, longest first so "bathroom" wins over "bath".
_WORDS = sorted({
    "hallway", "corridor", "entrance", "bathroom", "bedroom", "kitchen", "meeting", "resting",
    "rented", "working", "office", "living", "dining", "lunch", "space", "store", "storage",
    "room", "hall", "bath", "bed", "lobby", "pantry", "laundry", "closet", "garage", "toilet",
    "utility", "reception", "waiting", "server", "print", "copy", "break", "staff", "open",
    "chambre", "cuisine", "salon", "salle", "bain", "bureau", "entree", "couloir", "sejour",
    "cellier", "dressing", "buanderie", "terrasse", "douche", "manger", "eau", "wc",
}, key=len, reverse=True)


def _split_words(token: str) -> str:
    """"Rentedspace" -> "Rented space", when the whole token is dictionary
    words; anything else is left exactly as it came."""
    parts = token.split("-")
    if len(parts) > 1:
        return "-".join(_split_words(p) for p in parts)
    lower = token.lower()
    if not lower.isalpha() or lower in _WORDS or len(lower) < 6:
        return token
    words, i = [], 0
    while i < len(lower):
        for w in _WORDS:
            if lower.startswith(w, i):
                words.append(token[i:i + len(w)])
                i += len(w)
                break
        else:
            return token
    return " ".join(words) if len(words) > 1 else token


def _north(scene: Scene, bounds: Rect) -> None:
    cx, cy = bounds.x2 + 4.5, bounds.y2 - 2.5
    scene.polyline([(cx, cy + 1.9), (cx + 0.85, cy - 1.5), (cx, cy - 0.75), (cx - 0.85, cy - 1.5)],
                   closed=True, fill=INK, layer="G-ANNO")
    scene.text(cx, cy + 2.4, "N", size=0.72, bold=True, color=INK, layer="G-ANNO")


def _bounds(entities: list[Entity]) -> tuple[float, float, float, float]:
    boxes = [b for b in (e.bounds() for e in entities) if b]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _draw_entity(scene: Scene, e: Entity, f: float, level: str = TECHNICAL,
                 at: tuple[float, float] | None = None) -> None:
    if e.meta.get("hatch_stroke") or e.meta.get("glazing"):
        return  # its region is drawn as a solid wall / its window as a symbol instead
    layer = AIA_LAYER[e.role]
    # Only the technical plan marks inference; the others are presentation
    # drawings and the uncertainty lives in the report and the technical sheet.
    inferred = e.provenance == Provenance.INFERRED and level == TECHNICAL
    ink = INFERRED_INK if inferred else INK
    dash = INFERRED_DASH if inferred else None
    wall_fill = "#9a7a45" if inferred else WALL
    pts = [(x * f, y * f) for x, y in e.points]

    if e.kind == "text":
        if not e.text or e.meta.get("unreadable"):
            return
        # Never smaller on paper than a reader can make out: 2 mm at the
        # chosen scale, whatever the source's 1 mm dimension text was.
        floor = MIN_TEXT_PAPER_M * scene.scale.ratio * f if scene.scale else 0.3
        size = max((e.height or 0.25) * f, 0.3, floor)
        x, y = (at[0] * f, at[1] * f) if at else pts[0]
        anchor = {"start": "start", "middle": "middle", "end": "end"}.get(
            str(e.meta.get("anchor", "start")), "start")
        # The source gives a baseline; the scene centres text on its anchor.
        # Step half a height off the baseline, perpendicular to it.
        rad = math.radians(e.rotation)
        x, y = x - math.sin(rad) * size * 0.5, y + math.cos(rad) * size * 0.5
        shown = e.text if level == TECHNICAL else display_text(e.text)
        scene.text(x, y, shown, size=size, anchor=anchor,
                   color=LIGHT if e.role == Role.DIMENSION else ink,
                   rotate=e.rotation, layer=layer)
        return

    if e.kind in ("arc", "circle") and e.center and e.radius:
        cx, cy = e.center[0] * f, e.center[1] * f
        if e.kind == "circle":
            scene.arc(cx, cy, e.radius * f, 0.0, 2 * math.pi, segments=48,
                      stroke=ink, width=HAIRLINE * 1.2, dash=dash, layer=layer)
        else:
            a0, a1 = math.radians(e.start_angle or 0.0), math.radians(e.end_angle or 0.0)
            if a1 < a0:
                a1 += 2 * math.pi
            scene.arc(cx, cy, e.radius * f, a0, a1, stroke=ink, width=HAIRLINE * 1.2,
                      dash=dash, layer=layer)
        return

    if e.role == Role.WALL:
        if e.filled and e.closed:
            scene.polyline(pts, closed=True, fill=wall_fill, layer=layer)
        elif e.kind == "line" and len(pts) == 2:
            thickness = (e.thickness or DEFAULT_WALL) * f
            scene.polyline(_band(pts[0], pts[1], thickness), closed=True,
                           fill=wall_fill, layer=layer)
        else:
            scene.polyline(pts, closed=e.closed, stroke=ink, width=HAIRLINE * 3.0,
                           dash=dash, layer=layer)
        return

    if e.role == Role.WINDOW and e.meta.get("symbol") and len(pts) == 2:
        _draw_window_symbol(scene, pts[0], pts[1], (e.thickness or DEFAULT_WALL) * f, ink if inferred else GLASS,
                            dash, layer)
        return
    if e.role == Role.DOOR:
        scene.polyline(pts, closed=False, stroke=LIGHT if not inferred else ink, width=HAIRLINE,
                       dash=dash, layer=layer)
        if e.meta.get("leaf"):
            (hx, hy), (tx, ty) = e.meta["leaf"]
            scene.line(hx * f, hy * f, tx * f, ty * f, stroke=ink, width=HAIRLINE * 1.6, dash=dash, layer=layer)
        return

    fill = FILL_BY_ROLE.get(e.role) if e.filled else None
    weight = {Role.DOOR: 1.4, Role.WINDOW: 0.9, Role.COLUMN: 2.0, Role.DIMENSION: 1.0,
              Role.GRID: 0.8}.get(e.role, 1.0)
    stroke = GLASS if e.role == Role.WINDOW and not inferred else ink
    scene.polyline(pts, closed=e.closed, fill=fill, stroke=None if fill else stroke,
                   width=HAIRLINE * weight, dash=dash, layer=layer)


def _draw_window_symbol(scene: Scene, a, b, thickness: float, glass: str, dash, layer: str) -> None:
    """The conventional symbol: jamb ticks across the wall at each end and two
    thin glazing lines along it — the same symbol the generator draws."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    d = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / d, dx / d
    for p in (a, b):
        scene.line(p[0] - nx * thickness / 2, p[1] - ny * thickness / 2,
                   p[0] + nx * thickness / 2, p[1] + ny * thickness / 2,
                   stroke=WALL, width=HAIRLINE * 1.6, layer=layer)
    for k in (-0.25, 0.25):
        scene.line(a[0] + nx * thickness * k, a[1] + ny * thickness * k,
                   b[0] + nx * thickness * k, b[1] + ny * thickness * k,
                   stroke=glass, width=HAIRLINE * 0.9, dash=dash, layer=layer)


def _band(a, b, thickness):
    dx, dy = b[0] - a[0], b[1] - a[1]
    d = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / d * thickness / 2, dx / d * thickness / 2
    return [(a[0] + nx, a[1] + ny), (b[0] + nx, b[1] + ny), (b[0] - nx, b[1] - ny), (a[0] - nx, a[1] - ny)]


def _draw_title_block(scene: Scene, drawing: Drawing, bounds: Rect, units: str,
                      level: str = TECHNICAL, drawing_number: str = "A-101",
                      revision: str = "A") -> None:
    """Three ruled cells. Provenance appears on the technical plan only."""
    top = bounds.y - TITLE_GAP
    box = Rect(bounds.x, top - TITLE_HEIGHT, bounds.w, TITLE_HEIGHT)
    scene.rect(box, stroke=INK, width=HAIRLINE * 1.5, layer="G-ANNO")
    identity = box.x + box.w * 0.54
    issue = box.x + box.w * 0.76
    for x in (identity, issue):
        scene.line(x, box.y, x, box.y2, stroke=INK, width=HAIRLINE, layer="G-ANNO")
    pad = 0.7
    cell_w = identity - box.x - 2 * pad

    title = scene.title.upper()
    scene.text(box.x + pad, box.y2 - 1.45, title, size=max(_fit(title, cell_w, 0.95, True), 0.45),
               bold=True, anchor="start", color=INK, layer="G-ANNO")
    if level == TECHNICAL:
        prov = drawing.provenance_counts()
        facts = (f"{LEVEL_INFO[level][1]}  ·  SOURCE {drawing.format.upper()}  ·  QUALITY {drawing.quality}  ·  "
                 f"VERIFIED {prov.get('verified', 0)}  CALCULATED {prov.get('calculated', 0)}  "
                 f"INFERRED {prov.get('inferred', 0)}  UNKNOWN {prov.get('unknown', 0)}")
        if prov.get("inferred"):
            legend = "DASHED / TINTED = INFERRED, NOT CONFIRMED BY THE SOURCE"
            scene.text(box.x + pad, box.y + 2.35, legend, size=max(_fit(legend, cell_w, 0.5), 0.3),
                       anchor="start", color=INFERRED_INK, layer="G-ANNO")
    else:
        facts = f"{LEVEL_INFO[level][1]}  ·  PRELIMINARY — NOT FOR CONSTRUCTION"
    scene.text(box.x + pad, box.y + 1.15, facts, size=max(_fit(facts, cell_w, 0.55), 0.3),
               anchor="start", color=INK, layer="G-ANNO")

    cell = Rect(identity, box.y, issue - identity, box.h)
    _draw_scale_bar(scene, cell, units)
    label = f"SCALE  {scene.scale.label}"
    scene.text(cell.center[0], cell.y2 - 0.85, label, size=_fit(label, cell.w * 0.92, 0.52),
               color=INK, layer="G-ANNO")

    right_w = box.x2 - issue - 2 * pad
    scene.text(box.x2 - pad, box.y2 - 1.5, date.today().isoformat(),
               size=_fit(date.today().isoformat(), right_w, 0.6), anchor="end", color=LIGHT, layer="G-ANNO")
    if level == TECHNICAL:
        tail = f"SOURCE {drawing.scale_label or 'SCALE UNKNOWN'} [{drawing.scale_provenance.value.upper()}]"
    else:
        tail = f"{drawing_number}   REV {revision}"
    scene.text(box.x2 - pad, box.y + 1.15, tail, size=_fit(tail, right_w, 0.55),
               anchor="end", color=INK if level != TECHNICAL else LIGHT, layer="G-ANNO")
