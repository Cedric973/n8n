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

MIN_CALIBRATION_SAMPLES = 3
MAX_CALIBRATION_SPREAD = 0.08   # readings must agree this closely to be a scale
_PURE_LENGTH = re.compile(r"^\s*(?:\d{3,5}|\d+(?:[.,]\d+)?\s*(?:mm|cm|m)|\d+'\s*-?\s*\d*\"?)\s*$")


def _is_pure_length(text: str) -> bool:
    return bool(_PURE_LENGTH.match(text))


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
    if metres.units == "paper":
        metres.note("walls and doors were not inferred: without a scale, a wall's width "
                    "and a door's radius cannot be recognised")
    else:
        _infer_geometry(metres)
        _separate_sheet_furniture(metres)
    metres.metadata["disciplines"] = _disciplines(metres)
    metres.metadata["sheet_type"] = _sheet_type(metres)
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

    nts = any(re.search(r"\bN\.?T\.?S\.?\b", e.text or "", re.I) for e in d.texts())
    if nts:
        d.metadata["not_to_scale"] = True
        d.note("WARNING: the sheet is marked N.T.S. (not to scale); no measured scale can be "
               "better than inferred")

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
        from .calibrate import calibrate_by_areas
        areas = calibrate_by_areas(d, per_unit)
        enough = areas and areas["agreeing"] >= max(4, (areas["samples"] + 1) // 2)
        if enough and areas["spread"] <= 0.25:
            ratio = areas["ratio"]
            d.to_metres = per_unit * ratio
            d.scale_label = f"1:{ratio:.0f}"
            d.scale_provenance = Provenance.INFERRED
            d.metadata["area_calibration"] = areas
            d.note(f"scale 1:{ratio:.0f} inferred from {areas['agreeing']} of {areas['samples']} "
                   f"room-area labels that agree to {areas['spread']:.0%}; furniture inside rooms "
                   "biases this small, so treat as approximate")
        else:
            d.scale_provenance = Provenance.UNKNOWN
            d.units = "paper"
            if areas:
                d.metadata["area_calibration"] = areas
                d.note(f"room-area labels gave a scale near 1:{areas['ratio']:.0f} but only "
                       f"{areas['agreeing']} of {areas['samples']} rooms agree; not used")
            d.note("no printed scale and no readable dimensions: geometry is in paper metres, "
                   "not building metres")
    if nts and d.scale_provenance in (Provenance.VERIFIED, Provenance.CALCULATED):
        d.scale_provenance = Provenance.INFERRED


def _real_length(text: str) -> float | None:
    from .calibrate import bare_millimetres
    bare = bare_millimetres(text)
    if bare is not None:
        return bare
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
        if not _is_pure_length(t.text or ""):
            continue
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
    # Readings that do not agree are not a scale; they are noise that happened
    # to look like dimensions. Only a tight cluster of several is believed.
    if len(ratios) < MIN_CALIBRATION_SAMPLES or spread > MAX_CALIBRATION_SPREAD:
        d.note(f"{len(ratios)} dimension reading(s) spread {spread:.0%}: not enough agreement "
               "to establish a scale from them")
        return None
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


HATCH_CELL = 0.05        # metres; a hatched region is sampled on this grid
HATCH_MAX_STROKE = 0.8   # metres; hatch strokes are short, geometry is not


def _walls_from_hatching(d: Drawing) -> int:
    """Recover walls that a PDF export drew as solid or 45° hatching.

    CAD plot drivers flatten a SOLID or ANSI31 hatch into hundreds of hairline
    strokes a tenth of a millimetre apart. No single stroke is a wall, and no
    pair of them is a parallel wall face, so the geometric rules see nothing.
    Seen as a whole they are dense: sampled on a coarse grid, cells crossed by
    two or more strokes are solid, connected solid cells are a region, and a
    region with a wall's thickness is a wall. The region is handed back as
    rectangles — strips merged where their runs agree — so it exports to CAD
    as linework rather than as the thousand strokes it came from.
    """
    strokes = [e for e in d.entities if e.kind == "line" and e.role == Role.OTHER
               and not e.filled and (e.lineweight or 0.0) <= 0.05 and 0 < e.length <= HATCH_MAX_STROKE]
    if len(strokes) < 50:
        return 0
    box = d.bounds()
    if not box:
        return 0
    x0, y0 = box[0], box[1]
    w = int((box[2] - x0) / HATCH_CELL) + 2
    h = int((box[3] - y0) / HATCH_CELL) + 2
    if w * h > 4_000_000:
        return 0
    hits = bytearray(w * h)
    for e in strokes:
        (ax, ay), (bx, by) = e.points
        n = max(int(e.length / (HATCH_CELL / 2)), 1)
        touched: set[int] = set()   # one stroke counts once per cell, however it wobbles
        for i in range(n + 1):
            t = i / n
            cx = int((ax + (bx - ax) * t - x0) / HATCH_CELL)
            cy = int((ay + (by - ay) * t - y0) / HATCH_CELL)
            if 0 <= cx < w and 0 <= cy < h:
                touched.add(cy * w + cx)
        for idx in touched:
            if hits[idx] < 255:
                hits[idx] += 1
    solid = _close_mask(bytearray(1 if v >= 2 else 0 for v in hits), hits, w, h)

    # Connected components of solid cells.
    label = [0] * (w * h)
    regions: list[list[int]] = []
    for start in range(w * h):
        if not solid[start] or label[start]:
            continue
        regions.append([])
        stack = [start]
        label[start] = len(regions)
        while stack:
            i = stack.pop()
            regions[-1].append(i)
            cx, cy = i % w, i // w
            for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                if 0 <= nx < w and 0 <= ny < h:
                    j = ny * w + nx
                    if solid[j] and not label[j]:
                        label[j] = len(regions)
                        stack.append(j)

    accepted: set[int] = set()
    made = 0
    for number, cells in enumerate(regions, start=1):
        area = len(cells) * HATCH_CELL ** 2
        boundary = 0
        for i in cells:
            cx, cy = i % w, i // w
            for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                if not (0 <= nx < w and 0 <= ny < h) or not solid[ny * w + nx]:
                    boundary += 1
        perimeter = boundary * HATCH_CELL
        thickness = 2.0 * area / perimeter if perimeter else 0.0
        if not (WALL_THICKNESS[0] <= thickness <= WALL_THICKNESS[1]) or area < MIN_WALL_RUN * thickness:
            continue
        accepted.add(number)
        for rect in _cells_to_rects(cells, w, x0, y0):
            d.entities.append(Entity("polyline", rect, closed=True, filled=True, layer="hatch",
                                     role=Role.WALL, provenance=Provenance.INFERRED,
                                     thickness=thickness, meta={"hatch": True}))
            made += 1
    if not accepted:
        return 0
    consumed = 0
    for e in strokes:
        (ax, ay), (bx, by) = e.points
        cx, cy = int(((ax + bx) / 2 - x0) / HATCH_CELL), int(((ay + by) / 2 - y0) / HATCH_CELL)
        if 0 <= cx < w and 0 <= cy < h and label[cy * w + cx] in accepted:
            e.role, e.provenance = Role.WALL, Provenance.INFERRED
            e.meta["hatch_stroke"] = True
            consumed += 1
    d.note(f"reconstructed {len(accepted)} wall region(s) as {made} rectangles from "
           f"{consumed} hatch strokes the export had flattened them into")
    return made


def _close_mask(solid: bytearray, hits: bytearray, w: int, h: int) -> bytearray:
    """Fill the pinholes a sparse hatch leaves in a wall band.

    Where the strokes are far apart a cell inside the wall is crossed only
    once, or not at all, and the band comes out speckled. A cell most of whose
    neighbours are solid is inside the band: fill it when one stroke touched
    it and two neighbours agree, or when no stroke did and three agree. Two
    passes close the two-cell gaps that the first pass narrows.
    """
    for _ in range(2):
        grown = bytearray(solid)
        for i in range(w * h):
            if solid[i]:
                continue
            cx, cy = i % w, i // w
            around = 0
            if cx + 1 < w and solid[i + 1]: around += 1
            if cx > 0 and solid[i - 1]: around += 1
            if cy + 1 < h and solid[i + w]: around += 1
            if cy > 0 and solid[i - w]: around += 1
            if around >= 3 or (around >= 2 and hits[i] >= 1):
                grown[i] = 1
        if grown == solid:
            break
        solid = grown
    return solid


def _cells_to_rects(cells: list[int], w: int, x0: float, y0: float) -> list[list[tuple[float, float]]]:
    """Row runs of cells, merged upward where consecutive rows share a run."""
    rows: dict[int, list[int]] = {}
    for i in cells:
        rows.setdefault(i // w, []).append(i % w)
    runs: dict[int, list[tuple[int, int]]] = {}
    for cy, xs in rows.items():
        xs.sort()
        out = []
        start = prev = xs[0]
        for x in xs[1:]:
            if x != prev + 1:
                out.append((start, prev)); start = x
            prev = x
        out.append((start, prev))
        runs[cy] = out
    rects: list[list[tuple[float, float]]] = []
    open_runs: dict[tuple[int, int], int] = {}   # (x0, x1) -> row it started on
    for cy in range(min(rows), max(rows) + 2):
        current = set(runs.get(cy, []))
        for key, start_row in list(open_runs.items()):
            if key not in current:
                rects.append(_rect(key, start_row, cy - 1, x0, y0))
                del open_runs[key]
        for key in current:
            open_runs.setdefault(key, cy)
    return rects


def _rect(key, r0, r1, x0, y0):
    c = HATCH_CELL
    ax, bx = x0 + key[0] * c, x0 + (key[1] + 1) * c
    ay, by = y0 + r0 * c, y0 + (r1 + 1) * c
    return [(ax, ay), (bx, ay), (bx, by), (ax, by)]


def _infer_geometry(d: Drawing) -> None:
    _walls_from_hatching(d)
    lines = [e for e in d.entities if e.kind == "line" and e.role == Role.OTHER]
    walls = doors = columns = 0

    # Filled thin rectangles: wall bands as a print driver or this package draws them.
    for e in d.entities:
        if e.role != Role.OTHER or e.kind != "polyline" or not e.closed or not e.filled:
            continue
        if len(e.points) == 4 and _is_rectangle(e.points):
            sides = sorted((length(e.points[0], e.points[1]), length(e.points[1], e.points[2])))
            if WALL_THICKNESS[0] <= sides[0] <= WALL_THICKNESS[1] and sides[1] >= MIN_WALL_RUN:
                e.role, e.provenance, e.thickness = Role.WALL, Provenance.INFERRED, sides[0]
                walls += 1
            elif 0.15 <= sides[0] <= 0.9 and sides[1] / sides[0] < 2.0:
                e.role, e.provenance = Role.COLUMN, Provenance.INFERRED
                columns += 1
            continue
        # Any other filled outline: a long thin one is a wall run. For a strip,
        # thickness is about twice the area over the perimeter.
        area, perimeter = _polygon_area(e.points), e.length
        if perimeter <= 0 or area <= 0:
            continue
        thickness = 2.0 * area / perimeter
        run = perimeter / 2.0 - thickness
        if WALL_THICKNESS[0] <= thickness <= WALL_THICKNESS[1] and run >= MIN_WALL_RUN:
            e.role, e.provenance, e.thickness = Role.WALL, Provenance.INFERRED, thickness
            walls += 1

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

    doors += _join_split_door_arcs(d)
    _door_leaves(d)

    # Glazing lines sit a few centimetres apart inside a wall — exactly what
    # the parallel-pair wall rule below would also match. Windows go first.
    windows = _infer_windows(d)
    windows += _infer_windows_from_gaps(d)

    # Parallel pairs a wall's width apart, overlapping along most of their
    # length. Lines are bucketed by direction and sorted by offset, so each one
    # is compared only with neighbours a wall's width away, not with everything.
    long_lines = [e for e in lines if e.length >= 0.5 and e.role == Role.OTHER]
    by_dir: dict[int, list[tuple[float, Entity]]] = {}
    for e in long_lines:
        a, b = e.points
        ang = angle(a, b)
        rad = math.radians(ang)
        offset = -a[0] * math.sin(rad) + a[1] * math.cos(rad)
        by_dir.setdefault(int(ang // 2), []).append((offset, e))
    paired: set[int] = set()
    for key, group in by_dir.items():
        # Neighbouring bins too, so a wall straddling a bin edge is not missed.
        group = sorted(group + by_dir.get(key + 1, []) if key + 1 in by_dir else group, key=lambda r: r[0])
        for i, (off_p, p) in enumerate(group):
            if id(p) in paired:
                continue
            a, b = p.points
            for off_q, q in group[i + 1:]:
                if off_q - off_p > WALL_THICKNESS[1] + 0.01:
                    break
                if id(q) in paired or angle_diff(angle(a, b), angle(*q.points)) > 2.0:
                    continue
                c, dd = q.points
                sep = separation(a, b, c, dd)
                if not (WALL_THICKNESS[0] <= sep <= WALL_THICKNESS[1]):
                    continue
                if overlap(a, b, c, dd) < 0.6 * min(p.length, q.length):
                    continue
                for e in (p, q):
                    e.role, e.provenance, e.thickness = Role.WALL, Provenance.INFERRED, sep
                    paired.add(id(e))
                walls += 2
                break

    _prune_stray_walls(d)
    for label, n in (("walls", walls), ("doors", doors), ("columns", columns), ("windows", windows)):
        if n:
            d.note(f"inferred {n} {label} from geometry (not confirmed by layer names)")


DOOR_PIECE_SWEEP = 20.0       # degrees; a shorter arc piece is a fillet, not part of a swing
HALF_SWEEP = (38.0, 59.0)     # degrees; a 45° swing drawn on its own, hinge on the wall


def _join_split_door_arcs(d: Drawing) -> int:
    """A door swing that the export split into two or three arc pieces.

    Each piece on its own is too short a sweep to be a door. Pieces on the
    same circle — same centre to a few centimetres, same radius — are one
    swing; when their sweeps add up to a door's, all of them are the door.
    """
    pieces: list[tuple[Entity, tuple[float, float], float, float]] = []
    for e in d.entities:
        if e.role != Role.OTHER or e.kind != "polyline" or e.closed:
            continue
        fit = arc_like(e.points)
        if not fit or not (DOOR_RADIUS[0] <= fit[1] <= DOOR_RADIUS[1]) or fit[2] < DOOR_PIECE_SWEEP:
            continue
        pieces.append((e, fit[0], fit[1], fit[2]))
    # Pieces of one swing share a centre to a few centimetres and a radius to
    # a few percent; a three-point fit on a short piece is that loose.
    parent = list(range(len(pieces)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(pieces)):
        for j in range(i + 1, len(pieces)):
            (ci, ri), (cj, rj) = pieces[i][1:3], pieces[j][1:3]
            if length(ci, cj) <= 0.12 and abs(ri - rj) <= 0.12 * max(ri, rj):
                parent[find(i)] = find(j)
    groups: dict[int, list] = {}
    for i in range(len(pieces)):
        groups.setdefault(find(i), []).append(pieces[i])
    walls = [b for b in (e.bounds() for e in d.by_role(Role.WALL)) if b]

    def on_wall(p, slack=0.25) -> bool:
        return any(b[0] - slack <= p[0] <= b[2] + slack and b[1] - slack <= p[1] <= b[3] + slack
                   for b in walls)

    made = 0
    for group in groups.values():
        total = sum(sw for _, _, _, sw in group)
        if len(group) < 2:
            # A lone 45° piece is a half swing — the convention some offices
            # draw — when its hinge sits on a wall.
            if not (HALF_SWEEP[0] <= total <= HALF_SWEEP[1]) or not on_wall(group[0][1]):
                continue
        elif not (DOOR_SWEEP[0] <= total <= DOOR_SWEEP[1] + 15.0):
            continue
        centre = (sum(c[0] for _, c, _, _ in group) / len(group),
                  sum(c[1] for _, c, _, _ in group) / len(group))
        radius = sum(r for _, _, r, _ in group) / len(group)
        for i, (e, _, _, _) in enumerate(group):
            e.role, e.provenance = Role.DOOR, Provenance.INFERRED
            e.center, e.radius = centre, radius
            e.meta["door_piece"] = True
            if i:
                e.meta["door_secondary"] = True   # the leaf is drawn from the first piece only
        made += 1
    return made


def _door_leaves(d: Drawing) -> None:
    """Give every door its leaf: the line from the hinge to the swing's free end.

    The swing arc runs from the leaf's tip to the latch jamb. The jamb end
    touches a wall; the tip end stands out in the room. So the leaf goes from
    the arc's centre to whichever end of the arc is farther from any wall.
    """
    walls = [b for b in (e.bounds() for e in d.by_role(Role.WALL)) if b]
    if not walls:
        return

    def wall_distance(p) -> float:
        best = float("inf")
        for b in walls:
            dx = max(b[0] - p[0], 0.0, p[0] - b[2])
            dy = max(b[1] - p[1], 0.0, p[1] - b[3])
            best = min(best, math.hypot(dx, dy))
        return best

    groups: dict[tuple[int, int, int], list[Entity]] = {}
    for e in d.entities:
        if e.role != Role.DOOR or e.center is None or e.radius is None or e.meta.get("leaf"):
            continue
        key = (int(round(e.center[0] / 0.04)), int(round(e.center[1] / 0.04)), int(round(e.radius / 0.03)))
        groups.setdefault(key, []).append(e)
    for members in groups.values():
        ends = []
        for e in members:
            if e.kind == "arc" and e.start_angle is not None and e.end_angle is not None:
                for a in (e.start_angle, e.end_angle):
                    ends.append((e.center[0] + e.radius * math.cos(math.radians(a)),
                                 e.center[1] + e.radius * math.sin(math.radians(a))))
            elif e.points:
                ends.extend((e.points[0], e.points[-1]))
        if not ends:
            continue
        tip = max(ends, key=wall_distance)
        if wall_distance(tip) < 0.15:
            continue   # both ends on walls: not a swing we understand
        first = members[0]
        first.meta["leaf"] = [list(first.center), list(tip)]


def _infer_windows_from_gaps(d: Drawing) -> int:
    """A gap in a wall run bridged by a thin line along the wall: a window.

    Many drawings do not draw glazing as a pair. They stop the wall, and
    close the opening with one line where the glass is. That line is not a
    wall (it is far too thin), not a door (nothing swings) and not a
    dimension (it sits in the wall itself). Between two collinear runs of the
    same wall, spanning most of the gap, it is a window.
    """
    rects = []
    for e in d.by_role(Role.WALL):
        if e.kind != "polyline" or not e.closed or not e.filled or len(e.points) != 4:
            continue
        b = e.bounds()
        w, h = b[2] - b[0], b[3] - b[1]
        if w >= 0.3 and h <= WALL_THICKNESS[1] and w > h:
            rects.append(("h", b))
        elif h >= 0.3 and w <= WALL_THICKNESS[1] and h > w:
            rects.append(("v", b))
    lines = [e for e in d.entities if e.kind == "line" and e.role == Role.OTHER
             and not e.meta.get("hatch_stroke") and 0.35 <= e.length <= 5.0]
    found = 0
    for axis in ("h", "v"):
        # A band is a set of rectangles that overlap across the wall: the
        # rows a hatch reconstruction cut one wall into are one band.
        across = sorted(((b[1], b[3]) if axis == "h" else (b[0], b[2]), b)
                        for kind, b in rects if kind == axis)
        bands: list[tuple[float, float, list]] = []
        for (lo, hi), b in across:
            if bands and lo < bands[-1][1] + 1e-6 and hi - bands[-1][0] <= WALL_THICKNESS[1] + 0.05:
                bands[-1] = (bands[-1][0], max(bands[-1][1], hi), bands[-1][2] + [b])
            else:
                bands.append((lo, hi, [b]))
        for band_lo, band_hi, members in bands:
            along = sorted(((b[0], b[2]) if axis == "h" else (b[1], b[3])) for b in members)
            runs: list[list[float]] = []
            for a, b in along:
                if runs and a <= runs[-1][1] + 0.05:
                    runs[-1][1] = max(runs[-1][1], b)
                else:
                    runs.append([a, b])
            slack_lo, slack_hi = band_lo - 0.06, band_hi + 0.06
            for (a0, a1), (b0, b1) in zip(runs, runs[1:]):
                gap = b0 - a1
                if not (0.35 <= gap <= 4.0):
                    continue
                bridging = []
                for e in lines:
                    (x0, y0), (x1, y1) = e.points
                    if axis == "h":
                        if not (slack_lo <= y0 <= slack_hi and slack_lo <= y1 <= slack_hi):
                            continue
                        span = min(max(x0, x1), b0) - max(min(x0, x1), a1)
                    else:
                        if not (slack_lo <= x0 <= slack_hi and slack_lo <= x1 <= slack_hi):
                            continue
                        span = min(max(y0, y1), b0) - max(min(y0, y1), a1)
                    if span >= 0.6 * gap:
                        bridging.append(e)
                if not bridging:
                    continue
                mid = (band_lo + band_hi) / 2.0
                thickness = max(band_hi - band_lo, WALL_THICKNESS[0])
                pts = [(a1, mid), (b0, mid)] if axis == "h" else [(mid, a1), (mid, b0)]
                d.entities.append(Entity("polyline", pts, layer="window", role=Role.WINDOW,
                                         provenance=Provenance.INFERRED, thickness=thickness,
                                         meta={"symbol": "window"}))
                for e in bridging:
                    e.role, e.provenance = Role.WINDOW, Provenance.INFERRED
                    e.meta["glazing"] = True
                found += 1
    return found


WINDOW_LINES = (0.03, 0.45)   # metres between the glazing lines of one window


def _infer_windows(d: Drawing) -> int:
    """Two or three thin parallel lines, close together, lying in a wall: a window.

    Doors were found by their swing. Windows have no swing; what they have is
    glazing drawn as a pair (or triple) of lines a few centimetres apart, of
    the same length, sitting in the line of a wall — where nothing else is
    drawn that way.
    """
    walls = [b for b in (e.bounds() for e in d.by_role(Role.WALL)) if b]
    if not walls:
        return 0
    cand = [e for e in d.entities if e.kind == "line" and e.role == Role.OTHER
            and 0.45 <= e.length <= 4.0 and not e.meta.get("hatch_stroke")]
    by_dir: dict[int, list[tuple[float, Entity]]] = {}
    for e in cand:
        a, b = e.points
        rad = math.radians(angle(a, b))
        by_dir.setdefault(int(angle(a, b) // 2), []).append((-a[0] * math.sin(rad) + a[1] * math.cos(rad), e))

    def in_wall(e: Entity, slack: float = 0.12) -> bool:
        b = e.bounds()
        return any(b[0] >= wb[0] - slack and b[2] <= wb[2] + slack and b[1] >= wb[1] - slack
                   and b[3] <= wb[3] + slack for wb in walls)

    found = 0
    used: set[int] = set()
    for group in by_dir.values():
        group.sort(key=lambda r: r[0])
        for i, (off_p, p) in enumerate(group):
            if id(p) in used:
                continue
            mates = []
            for off_q, q in group[i + 1:]:
                if off_q - off_p > WINDOW_LINES[1]:
                    break
                if id(q) in used or off_q - off_p < WINDOW_LINES[0]:
                    continue
                if abs(q.length - p.length) > 0.25 * p.length:
                    continue
                if overlap(*p.points, *q.points) < 0.75 * min(p.length, q.length):
                    continue
                mates.append(q)
            if not mates:
                continue
            members = [p] + mates[:2]
            if not all(in_wall(m) for m in members):
                continue
            for m in members:
                m.role, m.provenance = Role.WINDOW, Provenance.INFERRED
                used.add(id(m))
            found += 1
    return found


def _polygon_area(pts) -> float:
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))) / 2.0


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
    # An opening sits in the line of its wall and joins the runs either side
    # of it, so windows and doors connect groups; they are never pruned.
    joints = [e for e in d.entities if e.role in (Role.WINDOW, Role.DOOR)]
    n_walls = len(walls)
    walls = walls + joints
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
        if boxes[i] is None:
            continue
        for j in range(i + 1, len(walls)):
            if boxes[j] is not None and touch(boxes[i], boxes[j]):
                parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in range(n_walls):
        groups.setdefault(find(i), []).append(i)
    # The building is the group with room labels inside it. A sheet border is
    # longer than any house; it just has no rooms. Length only breaks ties.
    labels = [e.points[0] for e in d.texts() if e.role == Role.TEXT and not e.meta.get("unreadable")]

    def enclosed(group) -> int:
        bx = [boxes[k] for k in group]
        x0, y0 = min(b[0] for b in bx), min(b[1] for b in bx)
        x1, y1 = max(b[2] for b in bx), max(b[3] for b in bx)
        return sum(1 for x, y in labels if x0 <= x <= x1 and y0 <= y <= y1)

    main = max(groups.values(), key=lambda g: (enclosed(g), len(g), sum(walls[k].length for k in g)))
    stray = [k for g in groups.values() if g is not main for k in g]
    for k in stray:
        walls[k].role, walls[k].thickness = Role.OTHER, None
    if stray:
        d.note(f"{len(stray)} wall-like shapes not connected to the building were not treated as walls")
    return len(stray)


SHEET_MARGIN = 2.2   # metres beyond the walls; dimension chains live inside this
_ROOM_WORDS = ("room", "office", "kitchen", "hall", "wc", "bath", "bed", "living", "dining",
               "space", "corridor", "lobby", "store", "salle", "chambre", "cuisine", "bureau",
               "couloir", "entr", "meeting", "lounge", "pantry", "laundry", "garage", "closet")


def _looks_like_room_name(text: str) -> bool:
    lower = text.lower()
    return any(w in lower for w in _ROOM_WORDS) or bool(re.search(r"\d+(?:[.,]\d+)?\s*m[²2]", lower))


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
    # Room names sit inside the building; let them widen it when the wall
    # search only caught part of it, but only names near the walls, not the
    # title block's.
    wx0, wy0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    wx1, wy1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    # Only short labels close to the walls count: a title block's "3 BED 2 BATH
    # 179.9 m²" mentions rooms too, and must not drag the box down to it.
    reach = 2 * SHEET_MARGIN
    for e in d.texts():
        text = e.text or ""
        if (e.role != Role.TEXT or e.meta.get("unreadable") or len(text) > 24
                or len(text.split()) > 3 or not _looks_like_room_name(text)):
            continue
        x, y = e.points[0]
        if wx0 - reach <= x <= wx1 + reach and wy0 - reach <= y <= wy1 + reach:
            wx0, wy0, wx1, wy1 = min(wx0, x), min(wy0, y), max(wx1, x), max(wy1, y)
    ww, wh = wx1 - wx0, wy1 - wy0
    furniture = dims = 0
    for e in d.entities:
        if e.role in (Role.WALL, Role.DOOR, Role.WINDOW, Role.STAIR, Role.SHEET):
            continue
        if e.provenance == Provenance.VERIFIED and e.role != Role.OTHER and e.kind != "text":
            continue  # a layer said what this is; position does not overrule it
        b = e.bounds()
        if not b:
            continue
        # Dimensioning lives in a band around the walls; anything that is not
        # wholly within that band belongs to the sheet, whether it sits clear
        # of the building or merely starts beside it and runs off to the title
        # block.
        within_band = (b[0] >= wx0 - SHEET_MARGIN and b[2] <= wx1 + SHEET_MARGIN
                       and b[1] >= wy0 - SHEET_MARGIN and b[3] <= wy1 + SHEET_MARGIN)
        frames = (b[2] - b[0]) > ww * 1.15 and (b[3] - b[1]) > wh * 1.15  # a border or page background
        inside = b[0] >= wx0 and b[2] <= wx1 and b[1] >= wy0 and b[3] <= wy1
        # A line just outside the walls that runs longer than half the building
        # is a title-block rule or a border, not a dimension.
        long_rule = (e.kind == "line" and not inside
                     and max(b[2] - b[0], b[3] - b[1]) > 0.5 * max(ww, wh))
        if not within_band or frames or long_rule:
            e.role, e.provenance = Role.SHEET, Provenance.INFERRED
            furniture += 1
        elif e.role == Role.COLUMN and not inside:
            e.role = Role.OTHER   # a column stands in the building or it is a symbol
        elif e.role == Role.OTHER and e.kind != "text" and not inside:
            e.role, e.provenance = Role.DIMENSION, Provenance.INFERRED
            dims += 1
    if furniture:
        d.note(f"{furniture} entities of the source's own sheet furniture (border, title block, "
               "north arrow, scale bar) were set aside; the re-issued sheet supplies its own")
    if dims:
        d.note(f"inferred {dims} dimension linework entities from their position outside the walls")


def _sheet_type(d: Drawing) -> str:
    """plan | elevation/section | schedule | detail — inferred from the sheet's own words."""
    words = " ".join((e.text or "") for e in d.texts() if not e.meta.get("unreadable")).lower()
    if re.search(r"elevation|section|coupe|façade|facade|elevación", words):
        return "elevation/section"
    if re.search(r"\d+(?:[.,]\d+)?\s*m[²2]", words) or d.by_role(Role.WALL) and d.by_role(Role.DOOR):
        return "plan"
    if re.search(r"schedule|nomenclature|profile|hinge|handle|frame", words):
        return "schedule"
    if len(d.texts()) < 15 and len(d.entities) > 5000:
        return "detail"
    return "unknown"


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
