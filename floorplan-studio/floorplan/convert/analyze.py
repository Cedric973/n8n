"""Work out what a drawing is: its units, its scale, and what each line means.

Three questions, answered in order and each answer tagged with how it was
reached:

1. **Units.** A DXF may declare them; a PDF or SVG is in paper units and needs
   a scale before anything is real-world.
2. **Scale.** Best is a printed scale on the sheet ("1:100"). Failing that, a
   dimension string is measured against the tick marks it sits between, which
   turns a paper length into a real one; several such readings that agree are
   a calculated scale. Failing both, the scale is unknown and stays unknown.
3. **Roles.** Layer names are believed. Geometry is only ever *inferred*: two
   long parallel lines a wall's width apart, a quarter-circle a door's radius.
"""

from __future__ import annotations

import math
import re
import statistics

from .geometry import angle, angle_diff, arc_like, length, overlap, project, separation
from .model import UNIT_TO_METRES, Drawing, Entity, Provenance, Role

GRADES = ["EXCELLENT", "GOOD", "ACCEPTABLE", "POOR", "UNUSABLE"]

LAYER_KEYWORDS: list[tuple[Role, tuple[str, ...]]] = [
    (Role.SHEET, ("TTLB", "TITLE", "CARTOUCHE", "BORDER", "G-ANNO", "SHEET", "FRAME")),
    (Role.DIMENSION, ("DIM", "COTE", "COTA", "BEMASS")),
    (Role.DOOR, ("DOOR", "PORTE", "PUERTA", "TUER", "TÜR", "A-DOOR")),
    (Role.WINDOW, ("WIND", "FEN", "GLAZ", "VENTANA", "FENSTER")),
    (Role.COLUMN, ("COLS", "COLUMN", "POTEAU", "PILAR", "STUETZ")),
    (Role.STAIR, ("STAIR", "STRS", "ESCAL", "TREPPE")),
    (Role.FURNITURE, ("FURN", "MOBIL", "MOEBEL")),
    (Role.EQUIPMENT, ("EQPM", "EQUIP", "APPL")),
    (Role.GRID, ("GRID", "AXIS", "AXE", "ACHSE")),
    (Role.WALL, ("WALL", "MUR", "WAND", "PARED", "PARTITION", "CLOISON")),
    (Role.TEXT, ("TEXT", "TXT", "LABEL", "NOTE", "ANNO")),
]

DISCIPLINE_HINTS = {
    "electrical": ("E-", "ELEC", "LIGHT", "POWER", "SOCKET", "PRISE", "LUM"),
    "hvac": ("M-", "HVAC", "DUCT", "GAINE", "CVC", "VENT"),
    "plumbing": ("P-", "PLUMB", "PIPE", "SANIT", "PLOMB", "EAU"),
    "structural": ("S-", "BEAM", "SLAB", "POUTRE", "DALLE", "STRUCT"),
    "fire": ("F-", "FIRE", "INCEND", "EXTINCT", "SPRINK"),
}

_METRIC_LEN = re.compile(r"(?<![\d.])(\d+(?:[.,]\d+)?)\s*(mm|cm|m)(?![²2a-z])")
_IMPERIAL_LEN = re.compile(r"(\d+)'\s*-?\s*(\d+(?:\.\d+)?)?\"?")
_SCALE_RATIO = re.compile(r"\b1\s*[:/]\s*(\d{2,4})\b")
_SCALE_IMPERIAL = re.compile(r"(\d+(?:/\d+)?)\s*(?:\"|″|in)\s*=\s*1\s*'?-?\s*0?\s*(?:\"|″|')?")

WALL_THICKNESS = (0.06, 0.60)   # metres
MIN_WALL_RUN = 0.9              # a filled band shorter than this is a symbol, not a wall
DOOR_RADIUS = (0.55, 1.30)
DOOR_SWEEP = (60.0, 120.0)


def analyze(drawing: Drawing) -> Drawing:
    _resolve_units(drawing)
    _resolve_scale(drawing)
    metres = drawing.in_metres()
    metres.notes = list(drawing.notes)
    _classify_by_layer(metres)
    _classify_text(metres)
    _infer_geometry(metres)
    _separate_sheet_furniture(metres)
    metres.metadata["disciplines"] = _disciplines(metres)
    metres.metadata["counts"] = metres.counts()
    metres.metadata["provenance"] = metres.provenance_counts()
    # The extent that matters is the drawing without the source's own sheet
    # furniture, and the building itself is what the walls span.
    content = [e for e in metres.entities if e.role != Role.SHEET] or metres.entities
    boxes = [b for b in (e.bounds() for e in content) if b]
    if boxes:
        x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
        x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
        metres.metadata["extent_m"] = (round(x1 - x0, 3), round(y1 - y0, 3))
    walls = [b for b in (e.bounds() for e in metres.by_role(Role.WALL)) if b]
    if walls:
        metres.metadata["building_extent_m"] = (
            round(max(b[2] for b in walls) - min(b[0] for b in walls), 3),
            round(max(b[3] for b in walls) - min(b[1] for b in walls), 3))
    metres.quality = _grade(metres)
    return metres


# -- units and scale ---------------------------------------------------------

def _resolve_units(d: Drawing) -> None:
    if d.units in UNIT_TO_METRES and d.units_provenance == Provenance.VERIFIED:
        d.to_metres = UNIT_TO_METRES[d.units]
        return
    if d.units in ("svg", "pt") and d.to_metres:
        return  # paper units with a known page mapping; scale decides the rest
    box = d.bounds()
    if not box:
        d.note("no geometry; units cannot be inferred")
        return
    extent = max(box[2] - box[0], box[3] - box[1])
    texts = " ".join(e.text or "" for e in d.texts())
    if _IMPERIAL_LEN.search(texts) and "m²" not in texts:
        guess = "ft"
    elif 1000 <= extent <= 500000:
        guess = "mm"
    elif 3 <= extent <= 300:
        guess = "m"
    elif 300 < extent <= 1000:
        guess = "ft"
    else:
        d.note(f"units unknown: drawing extent {extent:g} fits no common unit")
        d.units_provenance = Provenance.UNKNOWN
        return
    d.units, d.to_metres = guess, UNIT_TO_METRES[guess]
    d.units_provenance = Provenance.INFERRED
    d.note(f"units inferred as {guess} from a drawing extent of {extent:g} units")


def _resolve_scale(d: Drawing) -> None:
    """For paper-based sources, find the ratio that turns paper into building."""
    paper = d.units in ("svg", "pt")
    if not paper:
        d.scale_provenance = d.units_provenance
        if d.scale_label is None and d.units_provenance != Provenance.UNKNOWN:
            d.scale_label = "1:1 (model space)"
        return
    per_unit = d.to_metres or 0.0
    if not per_unit:
        d.scale_provenance = Provenance.UNKNOWN
        d.note("paper size unknown; cannot establish a real-world scale")
        return

    if "scale_ratio" not in d.metadata:
        for e in d.texts():
            m = _SCALE_RATIO.search(e.text or "")
            if m:
                d.metadata["scale_ratio"] = int(m.group(1))
                d.scale_label = f"1:{m.group(1)}"
                d.note(f"scale {d.scale_label} read from sheet text")
                break
            m = _SCALE_IMPERIAL.search(e.text or "")
            if m:
                frac = m.group(1)
                inches = (float(frac.split("/")[0]) / float(frac.split("/")[1])) if "/" in frac else float(frac)
                if inches > 0:
                    d.metadata["scale_ratio"] = 12.0 / inches
                    d.scale_label = f'{frac}" = 1\'-0"'
                    d.note(f"scale {d.scale_label} read from sheet text")
                    break

    calibrated = _calibrate(d, per_unit)
    printed = d.metadata.get("scale_ratio")
    if printed:
        d.to_metres = per_unit * printed
        d.scale_provenance = Provenance.VERIFIED
        if calibrated and abs(calibrated - printed) / printed > 0.05:
            d.note(f"WARNING: printed scale 1:{printed:g} disagrees with dimensions "
                   f"(measured 1:{calibrated:.0f}); the printed scale was used")
    elif calibrated:
        d.to_metres = per_unit * calibrated
        d.scale_label = f"1:{calibrated:.0f}"
        d.scale_provenance = Provenance.CALCULATED
        d.note(f"scale 1:{calibrated:.0f} calculated from dimension strings against their tick marks")
    else:
        d.scale_provenance = Provenance.UNKNOWN
        d.units = "paper"
        d.note("no printed scale and no readable dimensions: geometry is in paper metres, "
               "not building metres")


def _real_length(text: str) -> float | None:
    m = _METRIC_LEN.search(text)
    if m:
        value = float(m.group(1).replace(",", "."))
        return value * {"mm": 0.001, "cm": 0.01, "m": 1.0}[m.group(2)]
    m = _IMPERIAL_LEN.search(text)
    if m:
        return (float(m.group(1)) + (float(m.group(2)) if m.group(2) else 0.0) / 12.0) * 0.3048
    return None


def _calibrate(d: Drawing, per_unit: float) -> float | None:
    """Measure dimension strings against the tick marks they sit between."""
    ticks = []
    for e in d.entities:
        if e.kind == "line":
            a, b = e.points
            ticks.append((a, b, length(a, b)))
    ratios: list[float] = []
    for t in d.texts():
        real = _real_length(t.text or "")
        h = t.height or 0.0
        if real is None or h <= 0:
            continue
        cx, cy = t.points[0]
        ang = math.radians(t.rotation)
        ux, uy = math.cos(ang), math.sin(ang)
        nearest_neg = nearest_pos = None
        for a, b, tl in ticks:
            if not (0.3 * h <= tl <= 3.0 * h):
                continue
            mx, my = (a[0] + b[0]) / 2 - cx, (a[1] + b[1]) / 2 - cy
            across = -mx * uy + my * ux
            if abs(across) > 3.0 * h:
                continue
            along = mx * ux + my * uy
            if along < 0 and (nearest_neg is None or along > nearest_neg):
                nearest_neg = along
            if along > 0 and (nearest_pos is None or along < nearest_pos):
                nearest_pos = along
        if nearest_neg is None or nearest_pos is None:
            continue
        run = nearest_pos - nearest_neg
        if run <= 0 or abs(nearest_pos + nearest_neg) > 0.35 * run:
            continue
        ratios.append(real / (run * per_unit))
    if not ratios:
        return None
    ratios.sort()
    middle = ratios[len(ratios) // 4: max(len(ratios) * 3 // 4, len(ratios) // 4 + 1)] or ratios
    median = statistics.median(middle)
    spread = (max(middle) - min(middle)) / median if median else 1.0
    d.metadata["calibration_samples"] = len(ratios)
    d.metadata["calibration_spread"] = round(spread, 4)
    if len(ratios) == 1:
        d.note("scale calibrated from a single dimension; treat as low confidence")
    elif spread > 0.04:
        d.note(f"dimension readings disagree by {spread:.0%}; scale is low confidence")
    return median


# -- classification ------------------------------------------------------------

def _classify_by_layer(d: Drawing) -> None:
    for e in d.entities:
        name = e.layer.upper()
        for role, keys in LAYER_KEYWORDS:
            if any(k in name for k in keys):
                if e.kind == "text" and role not in (Role.DIMENSION, Role.SHEET):
                    role = Role.TEXT
                e.role = role
                e.provenance = Provenance.VERIFIED
                break


def _classify_text(d: Drawing) -> None:
    for e in d.texts():
        if e.role == Role.OTHER:
            e.role = Role.TEXT
        if e.role == Role.TEXT and _real_length(e.text or "") is not None and "x" not in (e.text or ""):
            e.role = Role.DIMENSION


def _infer_geometry(d: Drawing) -> None:
    lines = [e for e in d.entities if e.kind == "line" and e.role == Role.OTHER]
    walls = doors = columns = 0

    # Filled thin rectangles: wall bands as a print driver or this package draws them.
    for e in d.entities:
        if e.role != Role.OTHER or e.kind != "polyline" or not e.closed or len(e.points) != 4:
            continue
        if not _is_rectangle(e.points):
            continue
        sides = sorted((length(e.points[0], e.points[1]), length(e.points[1], e.points[2])))
        if e.filled and WALL_THICKNESS[0] <= sides[0] <= WALL_THICKNESS[1] and sides[1] >= MIN_WALL_RUN:
            e.role, e.provenance, e.thickness = Role.WALL, Provenance.INFERRED, sides[0]
            walls += 1
        elif e.filled and 0.15 <= sides[0] <= 0.9 and sides[1] / sides[0] < 2.0:
            e.role, e.provenance = Role.COLUMN, Provenance.INFERRED
            columns += 1

    # Arcs of a door's radius and sweep, drawn natively or as flattened polylines.
    for e in d.entities:
        if e.role != Role.OTHER:
            continue
        if e.kind == "arc" and e.radius and DOOR_RADIUS[0] <= e.radius <= DOOR_RADIUS[1]:
            sweep = abs((e.end_angle or 0) - (e.start_angle or 0)) % 360
            if DOOR_SWEEP[0] <= min(sweep, 360 - sweep) <= DOOR_SWEEP[1]:
                e.role, e.provenance = Role.DOOR, Provenance.INFERRED
                doors += 1
        elif e.kind == "polyline" and not e.closed:
            fit = arc_like(e.points)
            if fit and DOOR_RADIUS[0] <= fit[1] <= DOOR_RADIUS[1] and DOOR_SWEEP[0] <= fit[2] <= DOOR_SWEEP[1]:
                e.role, e.provenance = Role.DOOR, Provenance.INFERRED
                e.center, e.radius = fit[0], fit[1]
                doors += 1

    # Parallel pairs a wall's width apart, overlapping along most of their length.
    long_lines = [e for e in lines if e.length >= 0.5]
    paired: set[int] = set()
    for i, p in enumerate(long_lines):
        if id(p) in paired:
            continue
        a, b = p.points
        ang = angle(a, b)
        for q in long_lines[i + 1:]:
            if id(q) in paired:
                continue
            c, dd = q.points
            if angle_diff(ang, angle(c, dd)) > 2.0:
                continue
            sep = separation(a, b, c, dd)
            if not (WALL_THICKNESS[0] <= sep <= WALL_THICKNESS[1]):
                continue
            shared = overlap(a, b, c, dd)
            if shared < 0.6 * min(p.length, q.length):
                continue
            for e in (p, q):
                e.role, e.provenance, e.thickness = Role.WALL, Provenance.INFERRED, sep
                paired.add(id(e))
            walls += 2
            break

    walls -= _prune_stray_walls(d)
    for label, n in (("walls", walls), ("doors", doors), ("columns", columns)):
        if n:
            d.note(f"inferred {n} {label} from geometry (not confirmed by layer names)")


def _is_rectangle(pts, tolerance_deg: float = 2.0) -> bool:
    for i in range(4):
        a, b, c = pts[i - 1], pts[i], pts[(i + 1) % 4]
        if angle_diff(angle(a, b), angle(b, c)) < 90 - tolerance_deg:
            return False
    return True


def _prune_stray_walls(d: Drawing) -> int:
    """Keep the one connected body of walls; stray 'walls' elsewhere are not walls.

    A legend box, a scale bar or a thick border can pass the local tests for a
    wall. What they cannot do is touch the building. Walls are grouped by
    contact and only the largest group keeps the role; the rest are handed back
    for the sheet-furniture pass to judge by position.
    """
    walls = [e for e in d.entities if e.role == Role.WALL and e.provenance == Provenance.INFERRED]
    if len(walls) < 2:
        return 0
    boxes = [e.bounds() for e in walls]
    parent = list(range(len(walls)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def touch(a, b, gap=0.3):
        return not (a[0] > b[2] + gap or b[0] > a[2] + gap or a[1] > b[3] + gap or b[1] > a[3] + gap)

    for i in range(len(walls)):
        for j in range(i + 1, len(walls)):
            if touch(boxes[i], boxes[j]):
                parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in range(len(walls)):
        groups.setdefault(find(i), []).append(i)
    main = max(groups.values(), key=lambda g: sum(walls[k].length for k in g))
    stray = [k for g in groups.values() if g is not main for k in g]
    for k in stray:
        walls[k].role, walls[k].thickness = Role.OTHER, None
    if stray:
        d.note(f"{len(stray)} wall-like shapes not connected to the building were not treated as walls")
    return len(stray)


SHEET_MARGIN = 2.2   # metres beyond the walls; dimension chains live inside this


def _separate_sheet_furniture(d: Drawing) -> None:
    """Tell the building apart from the sheet it was printed on.

    An unlayered source carries its old title block, border, north arrow and
    scale bar as plain lines and text. Once the walls are known, anything well
    outside them is sheet furniture — the re-issued sheet supplies its own —
    and unclassified linework in the band just outside the walls is the
    dimensioning that sits there.
    """
    walls = d.by_role(Role.WALL)
    if not walls:
        return
    boxes = [b for b in (e.bounds() for e in walls) if b]
    wx0, wy0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    wx1, wy1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    ww, wh = wx1 - wx0, wy1 - wy0
    furniture = dims = 0
    for e in d.entities:
        if e.role in (Role.WALL, Role.DOOR, Role.WINDOW, Role.COLUMN, Role.STAIR, Role.SHEET):
            continue
        b = e.bounds()
        if not b:
            continue
        outside = (b[0] > wx1 + SHEET_MARGIN or b[2] < wx0 - SHEET_MARGIN
                   or b[1] > wy1 + SHEET_MARGIN or b[3] < wy0 - SHEET_MARGIN)
        frames = (b[2] - b[0]) > ww * 1.15 and (b[3] - b[1]) > wh * 1.15  # a border or page background
        inside = b[0] >= wx0 and b[2] <= wx1 and b[1] >= wy0 and b[3] <= wy1
        if outside or frames:
            e.role, e.provenance = Role.SHEET, Provenance.INFERRED
            furniture += 1
        elif e.role == Role.OTHER and e.kind != "text" and not inside:
            e.role, e.provenance = Role.DIMENSION, Provenance.INFERRED
            dims += 1
    if furniture:
        d.note(f"{furniture} entities of the source's own sheet furniture (border, title block, "
               "north arrow, scale bar) were set aside; the re-issued sheet supplies its own")
    if dims:
        d.note(f"inferred {dims} dimension linework entities from their position outside the walls")


def _disciplines(d: Drawing) -> list[str]:
    names = " ".join(d.layers()).upper()
    found = [disc for disc, keys in DISCIPLINE_HINTS.items() if any(k in names for k in keys)]
    return found or ["architecture"]


def _grade(d: Drawing) -> str:
    geometry = [e for e in d.entities if e.kind != "text"]
    if not geometry:
        return "UNUSABLE"
    penalty = 0
    if d.scale_provenance == Provenance.UNKNOWN:
        penalty += 2
    elif d.scale_provenance == Provenance.INFERRED:
        penalty += 1
    if not d.texts():
        penalty += 1
    if not d.by_role(Role.WALL):
        penalty += 1
    if len(geometry) < 20:
        penalty += 1
    extent = d.metadata.get("extent_m")
    if extent and (max(extent) > 500 or max(extent) < 2):
        penalty += 1
    inferred = d.provenance_counts().get("inferred", 0)
    if inferred > 0.3 * max(len(d.entities), 1):
        penalty += 1
    # UNUSABLE is reserved for a source with no geometry at all. A drawing
    # whose scale is unknown can still be re-issued, at paper size, with the
    # fact stated on the sheet and in the report.
    return GRADES[min(penalty, len(GRADES) - 2)]
