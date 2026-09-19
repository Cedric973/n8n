"""Tidy a drawing's geometry without changing what it says.

Exports from CAD and print drivers are full of things a reader never sees:
zero-length segments, the same line drawn twice, a straight wall split into
six collinear pieces, and lines a hair off horizontal. Each fix is recorded
in the drawing's notes with a count, so the report can say what was done.
"""

from __future__ import annotations

from .geometry import angle, angle_diff, length, project
from .model import Drawing, Entity

NOISE = 0.001         # metres; anything shorter is not linework
SNAP_DEGREES = 1.5    # within this of an axis, a line is meant to be on it
MERGE_GAP = 0.002     # metres; endpoints closer than this touch


def clean(drawing: Drawing) -> Drawing:
    before = len(drawing.entities)
    drawing.entities = [e for e in drawing.entities if not _is_noise(e)]
    dropped = before - len(drawing.entities)

    deduped = _dedupe(drawing.entities)
    duplicates = len(drawing.entities) - len(deduped)
    drawing.entities = deduped

    snapped = sum(_snap(e) for e in drawing.entities)

    merged_from = len(drawing.entities)
    drawing.entities = _merge_collinear(drawing.entities)
    merged = merged_from - len(drawing.entities)

    for label, count in (("dropped %d zero-length or sub-millimetre entities", dropped),
                         ("removed %d duplicate entities", duplicates),
                         ("snapped %d lines to the nearest axis", snapped),
                         ("merged %d collinear segments", merged)):
        if count:
            drawing.note(label % count)
    return drawing


def _is_noise(e: Entity) -> bool:
    if e.kind == "text":
        return not (e.text or "").strip()
    if e.kind in ("arc", "circle"):
        return (e.radius or 0.0) < NOISE
    return e.length < NOISE


def _key(e: Entity) -> tuple:
    if e.kind == "line":
        a, b = e.points
        pts = tuple(sorted(((round(a[0], 4), round(a[1], 4)), (round(b[0], 4), round(b[1], 4)))))
        return ("line", pts, e.layer)
    if e.kind == "text":
        return ("text", e.text, round(e.points[0][0], 3), round(e.points[0][1], 3), e.layer)
    if e.kind in ("arc", "circle"):
        return (e.kind, tuple(round(v, 4) for v in e.center or (0, 0)), round(e.radius or 0, 4),
                round(e.start_angle or 0, 2), round(e.end_angle or 0, 2), e.layer)
    return ("poly", tuple((round(x, 4), round(y, 4)) for x, y in e.points), e.closed, e.layer)


def _dedupe(entities: list[Entity]) -> list[Entity]:
    seen: set = set()
    out = []
    for e in entities:
        k = _key(e)
        if k in seen:
            continue
        seen.add(k)
        out.append(e)
    return out


def _snap(e: Entity) -> int:
    """Rotate a nearly-axial line about its midpoint onto the axis."""
    if e.kind != "line":
        return 0
    a, b = e.points
    ang = angle(a, b)
    if angle_diff(ang, 0.0) < SNAP_DEGREES and abs(a[1] - b[1]) > 0:
        y = (a[1] + b[1]) / 2.0
        e.points = [(a[0], y), (b[0], y)]
        return 1
    if angle_diff(ang, 90.0) < SNAP_DEGREES and abs(a[0] - b[0]) > 0:
        x = (a[0] + b[0]) / 2.0
        e.points = [(x, a[1]), (x, b[1])]
        return 1
    return 0


def _merge_collinear(entities: list[Entity]) -> list[Entity]:
    """Join lines that share an endpoint, a direction, a layer and a role."""
    lines = [e for e in entities if e.kind == "line"]
    others = [e for e in entities if e.kind != "line"]
    by_group: dict[tuple, list[Entity]] = {}
    for e in lines:
        by_group.setdefault((e.layer, e.role, e.filled), []).append(e)

    merged: list[Entity] = []
    for group in by_group.values():
        pool = list(group)
        changed = True
        while changed:
            changed = False
            for i in range(len(pool)):
                for j in range(i + 1, len(pool)):
                    joined = _join(pool[i], pool[j])
                    if joined is not None:
                        pool[i] = joined
                        pool.pop(j)
                        changed = True
                        break
                if changed:
                    break
        merged.extend(pool)
    return merged + others


def _join(p: Entity, q: Entity) -> Entity | None:
    a, b = p.points
    c, d = q.points
    if angle_diff(angle(a, b), angle(c, d)) > 0.2:
        return None
    # q's endpoints must lie on p's line, and the two must touch or overlap.
    _, off_c = project(c, a, b)
    _, off_d = project(d, a, b)
    if abs(off_c) > MERGE_GAP or abs(off_d) > MERGE_GAP:
        return None
    la = length(a, b)
    s_c, _ = project(c, a, b)
    s_d, _ = project(d, a, b)
    lo, hi = min(s_c, s_d), max(s_c, s_d)
    if hi < -MERGE_GAP or lo > la + MERGE_GAP:
        return None
    start, end = min(0.0, lo), max(la, hi)
    ux, uy = (b[0] - a[0]) / la, (b[1] - a[1]) / la
    out = Entity(**{k: v for k, v in p.__dict__.items()})
    out.points = [(a[0] + ux * start, a[1] + uy * start), (a[0] + ux * end, a[1] + uy * end)]
    return out
