"""Tidy a drawing's geometry without changing what it says.

Exports from CAD and print drivers are full of things a reader never sees:
zero-length segments, the same line drawn twice, a straight wall split into
six collinear pieces, and lines a hair off horizontal. Each fix is recorded
in the drawing's notes with a count, so the report can say what was done.
"""

from __future__ import annotations

import math

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
    """Join lines that share a direction, an offset, a layer and a role.

    Lines are bucketed by direction and by their perpendicular offset from the
    origin, so only lines that could possibly be collinear are compared; each
    bucket is then swept once along its direction, merging runs that touch or
    overlap. Linear-ish, where the obvious pairwise loop is quadratic and
    stalls on a real drawing's fifteen thousand segments.
    """
    lines = [e for e in entities if e.kind == "line"]
    others = [e for e in entities if e.kind != "line"]
    buckets: dict[tuple, list[tuple[float, float, Entity]]] = {}
    for e in lines:
        a, b = e.points
        ang = angle(a, b)
        rad = math.radians(ang)
        ux, uy = math.cos(rad), math.sin(rad)
        offset = -a[0] * uy + a[1] * ux          # signed distance of the line from the origin
        s0, s1 = a[0] * ux + a[1] * uy, b[0] * ux + b[1] * uy
        key = (e.layer, e.role, e.filled, round(ang / 0.25), round(offset / MERGE_GAP))
        buckets.setdefault(key, []).append((min(s0, s1), max(s0, s1), e))

    merged: list[Entity] = []
    for key, runs in buckets.items():
        runs.sort(key=lambda r: r[0])
        cur_lo, cur_hi, cur = runs[0]
        for lo, hi, e in runs[1:]:
            if lo <= cur_hi + MERGE_GAP:
                cur_hi = max(cur_hi, hi)
            else:
                merged.append(_span(cur, cur_lo, cur_hi))
                cur_lo, cur_hi, cur = lo, hi, e
        merged.append(_span(cur, cur_lo, cur_hi))
    return merged + others


def _span(template: Entity, lo: float, hi: float) -> Entity:
    """``template``'s line, re-cut to run from ``lo`` to ``hi`` along its direction."""
    a, b = template.points
    rad = math.radians(angle(a, b))
    ux, uy = math.cos(rad), math.sin(rad)
    offset = -a[0] * uy + a[1] * ux
    px, py = -uy * offset, ux * offset            # foot of the perpendicular from the origin
    out = Entity(**{k: v for k, v in template.__dict__.items()})
    out.meta = dict(template.meta)
    out.points = [(px + ux * lo, py + uy * lo), (px + ux * hi, py + uy * hi)]
    return out
