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
from datetime import date
from pathlib import Path

from ..drawing import HAIRLINE, Scene
from ..geometry import Rect
from ..render import INK, LIGHT, TITLE_HEIGHT, WALL, _draw_scale_bar, _fit
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
                        keep_sheet_furniture: bool = False) -> Scene:
    """``drawing`` must be in metres (the analyzer's output)."""
    content = [e for e in drawing.entities if keep_sheet_furniture or e.role != Role.SHEET]
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

    for role in (Role.OTHER, Role.GRID, Role.FURNITURE, Role.EQUIPMENT, Role.STAIR,
                 Role.COLUMN, Role.WALL, Role.WINDOW, Role.DOOR, Role.DIMENSION, Role.TEXT):
        for e in content:
            if e.role == role:
                _draw_entity(scene, e, f)
    _north(scene, bounds)
    _draw_title_block(scene, drawing, bounds, units)
    return scene


def _north(scene: Scene, bounds: Rect) -> None:
    cx, cy = bounds.x2 + 4.5, bounds.y2 - 2.5
    scene.polyline([(cx, cy + 1.9), (cx + 0.85, cy - 1.5), (cx, cy - 0.75), (cx - 0.85, cy - 1.5)],
                   closed=True, fill=INK, layer="G-ANNO")
    scene.text(cx, cy + 2.4, "N", size=0.72, bold=True, color=INK, layer="G-ANNO")


def _bounds(entities: list[Entity]) -> tuple[float, float, float, float]:
    boxes = [b for b in (e.bounds() for e in entities) if b]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _draw_entity(scene: Scene, e: Entity, f: float) -> None:
    layer = AIA_LAYER[e.role]
    inferred = e.provenance == Provenance.INFERRED
    ink = INFERRED_INK if inferred else INK
    dash = INFERRED_DASH if inferred else None
    pts = [(x * f, y * f) for x, y in e.points]

    if e.kind == "text":
        if not e.text:
            return
        size = max((e.height or 0.25) * f, 0.3)
        x, y = pts[0]
        anchor = {"start": "start", "middle": "middle", "end": "end"}.get(
            str(e.meta.get("anchor", "start")), "start")
        # The source gives a baseline; the scene centres text on its anchor.
        # Step half a height off the baseline, perpendicular to it.
        rad = math.radians(e.rotation)
        x, y = x - math.sin(rad) * size * 0.5, y + math.cos(rad) * size * 0.5
        scene.text(x, y, e.text, size=size, anchor=anchor,
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
            scene.polyline(pts, closed=True, fill=WALL if not inferred else "#9a7a45", layer=layer)
        elif e.kind == "line" and len(pts) == 2:
            thickness = (e.thickness or DEFAULT_WALL) * f
            scene.polyline(_band(pts[0], pts[1], thickness), closed=True,
                           fill=WALL if not inferred else "#9a7a45", layer=layer)
        else:
            scene.polyline(pts, closed=e.closed, stroke=ink, width=HAIRLINE * 3.0,
                           dash=dash, layer=layer)
        return

    fill = FILL_BY_ROLE.get(e.role) if e.filled else None
    weight = {Role.DOOR: 1.4, Role.WINDOW: 1.4, Role.COLUMN: 2.0, Role.DIMENSION: 1.0,
              Role.GRID: 0.8}.get(e.role, 1.0)
    scene.polyline(pts, closed=e.closed, fill=fill, stroke=None if fill else ink,
                   width=HAIRLINE * weight, dash=dash, layer=layer)


def _band(a, b, thickness):
    dx, dy = b[0] - a[0], b[1] - a[1]
    d = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / d * thickness / 2, dx / d * thickness / 2
    return [(a[0] + nx, a[1] + ny), (b[0] + nx, b[1] + ny), (b[0] - nx, b[1] - ny), (a[0] - nx, a[1] - ny)]


def _draw_title_block(scene: Scene, drawing: Drawing, bounds: Rect, units: str) -> None:
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
    prov = drawing.provenance_counts()
    facts = (f"SOURCE {drawing.format.upper()}  ·  QUALITY {drawing.quality}  ·  "
             f"VERIFIED {prov.get('verified', 0)}  CALCULATED {prov.get('calculated', 0)}  "
             f"INFERRED {prov.get('inferred', 0)}  UNKNOWN {prov.get('unknown', 0)}")
    scene.text(box.x + pad, box.y + 1.15, facts, size=max(_fit(facts, cell_w, 0.55), 0.3),
               anchor="start", color=INK, layer="G-ANNO")
    if prov.get("inferred"):
        legend = "DASHED = INFERRED, NOT CONFIRMED BY THE SOURCE"
        scene.text(box.x + pad, box.y + 2.35, legend, size=max(_fit(legend, cell_w, 0.5), 0.3),
                   anchor="start", color=INFERRED_INK, layer="G-ANNO")

    cell = Rect(identity, box.y, issue - identity, box.h)
    _draw_scale_bar(scene, cell, units)
    label = f"SCALE  {scene.scale.label}"
    scene.text(cell.center[0], cell.y2 - 0.85, label, size=_fit(label, cell.w * 0.92, 0.52),
               color=INK, layer="G-ANNO")

    right_w = box.x2 - issue - 2 * pad
    scene.text(box.x2 - pad, box.y2 - 1.5, date.today().isoformat(),
               size=_fit(date.today().isoformat(), right_w, 0.6), anchor="end", color=LIGHT, layer="G-ANNO")
    source_scale = f"SOURCE {drawing.scale_label or 'SCALE UNKNOWN'} [{drawing.scale_provenance.value.upper()}]"
    scene.text(box.x2 - pad, box.y + 1.15, source_scale, size=_fit(source_scale, right_w, 0.5),
               anchor="end", color=LIGHT, layer="G-ANNO")
