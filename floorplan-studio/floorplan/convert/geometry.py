"""Small vector helpers shared by the analyzer and the cleaner."""

from __future__ import annotations

import math

Point = tuple[float, float]


def length(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def angle(a: Point, b: Point) -> float:
    """Direction of a->b in degrees, folded to [0, 180)."""
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180.0


def angle_diff(u: float, v: float) -> float:
    d = abs(u - v) % 180.0
    return min(d, 180.0 - d)


def unit(a: Point, b: Point) -> Point:
    d = length(a, b)
    return ((b[0] - a[0]) / d, (b[1] - a[1]) / d) if d > 0 else (1.0, 0.0)


def project(p: Point, a: Point, b: Point) -> tuple[float, float]:
    """(along, across): distance along a->b from a, and signed offset from the line."""
    ux, uy = unit(a, b)
    dx, dy = p[0] - a[0], p[1] - a[1]
    return (dx * ux + dy * uy, dx * -uy + dy * ux)


def overlap(a: Point, b: Point, c: Point, d: Point) -> float:
    """Length of c-d's projection that lies within a-b, along a-b."""
    la = length(a, b)
    s0, _ = project(c, a, b)
    s1, _ = project(d, a, b)
    lo, hi = max(min(s0, s1), 0.0), min(max(s0, s1), la)
    return max(hi - lo, 0.0)


def separation(a: Point, b: Point, c: Point, d: Point) -> float:
    """Mean perpendicular distance of c and d from line a-b."""
    _, o1 = project(c, a, b)
    _, o2 = project(d, a, b)
    return (abs(o1) + abs(o2)) / 2.0


def midpoint(a: Point, b: Point) -> Point:
    return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)


def circle_through(p1: Point, p2: Point, p3: Point) -> tuple[Point, float] | None:
    """Centre and radius of the circle through three points, or None if collinear."""
    ax, ay = p1; bx, by = p2; cx, cy = p3
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    return (ux, uy), math.hypot(ax - ux, ay - uy)


def arc_like(points: list[Point], tolerance: float = 0.04) -> tuple[Point, float, float] | None:
    """If a polyline hugs one circle, return (centre, radius, sweep degrees)."""
    if len(points) < 5:
        return None
    fit = circle_through(points[0], points[len(points) // 2], points[-1])
    if fit is None:
        return None
    (cx, cy), r = fit
    if r <= 0:
        return None
    for x, y in points:
        if abs(math.hypot(x - cx, y - cy) - r) > tolerance * r:
            return None
    a0 = math.atan2(points[0][1] - cy, points[0][0] - cx)
    a1 = math.atan2(points[-1][1] - cy, points[-1][0] - cx)
    sweep = abs(math.degrees(a1 - a0)) % 360.0
    return (cx, cy), r, min(sweep, 360.0 - sweep)
