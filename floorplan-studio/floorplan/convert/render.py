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
from ..render import GLASS, INK, LIGHT, TITLE_HEIGHT, WALL, WALL_INTERIOR, _draw_scale_bar, _fit
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
    if level == CLIENT:
        labels = room_labels([e for e in content if e.role == Role.TEXT])
        content = [e for e in content if e.role in CLIENT_ROLES or id(e) in labels]
    elif level == DIMENSION:
        content = [e for e in content if e.role != Role.OTHER or e.kind == "text"]
    if not content:
        raise ValueError("drawing has no content to draw")
    box = _bounds(content)
    f = FEET_PER_METRE
    bounds = Rect(box[0] * f, box[1] * f, (box[2] - box[0]) * f, (box[3] - box[1]) * f)
    # The source's dimensions travel with it, so only the north arrow and the
    # title block need room — not the chains a generated plan gets.
    left, right, top = 1.5, 8.0, 1.5
    bottom = TITLE_GAP + TITLE_HEIGHT + 1.0
    extent = Rect(bounds.x - left, bounds.y - bottom, bounds.w + left + right, bounds.h + bottom + top)
    chosen_sheet, chosen_scale = choose(extent.w, extent.h, units, sheet=sheet, scale=scale)
    scene = Scene(bounds=extent, title=Path(drawing.source).stem or "Converted plan",
                  sheet=chosen_sheet, scale=chosen_scale)

    scene.level = level  # type: ignore[attr-defined]
    for role in (Role.OTHER, Role.GRID, Role.FURNITURE, Role.EQUIPMENT, Role.STAIR,
                 Role.COLUMN, Role.WALL, Role.WINDOW, Role.DOOR, Role.DIMENSION, Role.TEXT):
        for e in content:
            if e.role == role:
                _draw_entity(scene, e, f, level)
    _north(scene, bounds)
    _draw_title_block(scene, drawing, bounds, units, level, drawing_number or "A-101", revision)
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


def room_labels(texts: list[Entity]) -> set[int]:
    """The texts a client plan keeps: every area, and the name lines stacked
    directly above one.

    A room label on a CAD plan is a stack — one or two name lines, then the
    area, then the ceiling height. The area is the anchor; a name is any short
    text whose baseline sits within two line heights above a kept line and
    whose centre lies over it. Captions with no area under them (a furniture
    tag, a "to be precised" note) are not rooms and stay off the client plan.
    """
    kept = {id(e): e for e in texts if _is_area(e)}
    names = [e for e in texts if _is_name(e) and id(e) not in kept]
    for _ in range(2):   # a name line above a name line above the area
        added = False
        for e in names:
            if id(e) in kept:
                continue
            box = _text_box(e)
            if not box:
                continue
            height = box[3] - box[1]
            for k in kept.values():
                kb = _text_box(k)
                if not kb:
                    continue
                gap = box[1] - kb[3]
                overlap = min(box[2], kb[2]) - max(box[0], kb[0])
                if -0.5 * height <= gap <= 1.5 * height and overlap > -height:
                    kept[id(e)] = e
                    added = True
                    break
        if not added:
            break
    return set(kept)


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
    return text


def _north(scene: Scene, bounds: Rect) -> None:
    cx, cy = bounds.x2 + 4.5, bounds.y2 - 2.5
    scene.polyline([(cx, cy + 1.9), (cx + 0.85, cy - 1.5), (cx, cy - 0.75), (cx - 0.85, cy - 1.5)],
                   closed=True, fill=INK, layer="G-ANNO")
    scene.text(cx, cy + 2.4, "N", size=0.72, bold=True, color=INK, layer="G-ANNO")


def _bounds(entities: list[Entity]) -> tuple[float, float, float, float]:
    boxes = [b for b in (e.bounds() for e in entities) if b]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _draw_entity(scene: Scene, e: Entity, f: float, level: str = TECHNICAL) -> None:
    if e.meta.get("hatch_stroke"):
        return  # its region is drawn as a solid wall instead
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
        x, y = pts[0]
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

    fill = FILL_BY_ROLE.get(e.role) if e.filled else None
    weight = {Role.DOOR: 1.4, Role.WINDOW: 0.9, Role.COLUMN: 2.0, Role.DIMENSION: 1.0,
              Role.GRID: 0.8}.get(e.role, 1.0)
    stroke = GLASS if e.role == Role.WINDOW and not inferred else ink
    scene.polyline(pts, closed=e.closed, fill=fill, stroke=None if fill else stroke,
                   width=HAIRLINE * weight, dash=dash, layer=layer)


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
