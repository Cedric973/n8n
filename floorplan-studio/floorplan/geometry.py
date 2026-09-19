"""Axis-aligned geometry primitives for rectilinear floor plans.

All coordinates are in feet, with y pointing up (CAD convention). Everything in
this module is exact-ish: comparisons go through :data:`EPS` so that footprints
authored on a 1-inch grid behave predictably.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Iterator, Sequence

EPS = 1e-6

Point = tuple[float, float]


def _almost(a: float, b: float, tol: float = EPS) -> bool:
    return abs(a - b) <= tol


@dataclass(frozen=True)
class Segment:
    """An axis-aligned segment. ``vertical`` segments have ``x1 == x2``."""

    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def vertical(self) -> bool:
        return _almost(self.x1, self.x2)

    @property
    def horizontal(self) -> bool:
        return _almost(self.y1, self.y2)

    @property
    def length(self) -> float:
        return math.hypot(self.x2 - self.x1, self.y2 - self.y1)

    @property
    def midpoint(self) -> Point:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)

    def point_at(self, t: float) -> Point:
        """Point at parameter ``t`` in [0, 1] along the segment."""
        return (self.x1 + (self.x2 - self.x1) * t, self.y1 + (self.y2 - self.y1) * t)

    def sub(self, center_t: float, length: float) -> "Segment":
        """A sub-segment of ``length`` centred at parameter ``center_t``."""
        total = self.length
        if total <= EPS:
            return self
        half = min(length, total) / 2.0 / total
        lo = min(max(center_t - half, 0.0), 1.0 - 2 * half)
        hi = lo + 2 * half
        (ax, ay), (bx, by) = self.point_at(lo), self.point_at(hi)
        return Segment(ax, ay, bx, by)


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def x2(self) -> float:
        return self.x + self.w

    @property
    def y2(self) -> float:
        return self.y + self.h

    @property
    def area(self) -> float:
        return self.w * self.h

    @property
    def center(self) -> Point:
        return (self.x + self.w / 2.0, self.y + self.h / 2.0)

    @property
    def min_dim(self) -> float:
        return min(self.w, self.h)

    @property
    def max_dim(self) -> float:
        return max(self.w, self.h)

    @property
    def aspect(self) -> float:
        """Long side over short side; 1.0 for a square."""
        if self.min_dim <= EPS:
            return math.inf
        return self.max_dim / self.min_dim

    @property
    def corners(self) -> tuple[Point, Point, Point, Point]:
        return ((self.x, self.y), (self.x2, self.y), (self.x2, self.y2), (self.x, self.y2))

    def inset(self, d: float) -> "Rect":
        return Rect(self.x + d, self.y + d, max(self.w - 2 * d, 0.0), max(self.h - 2 * d, 0.0))

    def contains_point(self, p: Point, tol: float = EPS) -> bool:
        return (
            self.x - tol <= p[0] <= self.x2 + tol and self.y - tol <= p[1] <= self.y2 + tol
        )

    def overlap_area(self, other: "Rect") -> float:
        dx = min(self.x2, other.x2) - max(self.x, other.x)
        dy = min(self.y2, other.y2) - max(self.y, other.y)
        return max(dx, 0.0) * max(dy, 0.0)

    def edges(self) -> dict[str, Segment]:
        return {
            "south": Segment(self.x, self.y, self.x2, self.y),
            "north": Segment(self.x, self.y2, self.x2, self.y2),
            "west": Segment(self.x, self.y, self.x, self.y2),
            "east": Segment(self.x2, self.y, self.x2, self.y2),
        }


def shared_wall(a: Rect, b: Rect, tol: float = 1e-4) -> Segment | None:
    """The segment where two rects touch, or ``None`` if they do not.

    Rects that merely meet at a corner return ``None`` (zero-length contact).
    """
    # Vertical contact: a's east on b's west, or vice versa.
    for lo, hi in ((a, b), (b, a)):
        if _almost(lo.x2, hi.x, tol):
            y0, y1 = max(lo.y, hi.y), min(lo.y2, hi.y2)
            if y1 - y0 > tol:
                return Segment(lo.x2, y0, lo.x2, y1)
        if _almost(lo.y2, hi.y, tol):
            x0, x1 = max(lo.x, hi.x), min(lo.x2, hi.x2)
            if x1 - x0 > tol:
                return Segment(x0, lo.y2, x1, lo.y2)
    return None


class Polygon:
    """A simple rectilinear polygon, stored as a closed ring of vertices."""

    def __init__(self, points: Sequence[Point]):
        pts = _dedupe(points)
        if len(pts) < 4:
            raise ValueError("a footprint needs at least 4 distinct corners")
        pts = _drop_collinear(pts)
        for (ax, ay), (bx, by) in _ring_edges(pts):
            if not (_almost(ax, bx) or _almost(ay, by)):
                raise ValueError(
                    f"footprint edges must be axis-aligned; ({ax}, {ay})-({bx}, {by}) is not"
                )
        if _signed_area(pts) < 0:
            pts = list(reversed(pts))
        self.points: list[Point] = pts

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Polygon({self.points!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Polygon) and self.points == other.points

    @classmethod
    def rectangle(cls, w: float, h: float, x: float = 0.0, y: float = 0.0) -> "Polygon":
        return cls([(x, y), (x + w, y), (x + w, y + h), (x, y + h)])

    @classmethod
    def l_shape(cls, w: float, h: float, notch_w: float, notch_h: float) -> "Polygon":
        """Rectangle ``w`` x ``h`` with the north-east corner notched out."""
        if not (0 < notch_w < w and 0 < notch_h < h):
            raise ValueError("notch must be smaller than the overall footprint")
        return cls(
            [
                (0, 0),
                (w, 0),
                (w, h - notch_h),
                (w - notch_w, h - notch_h),
                (w - notch_w, h),
                (0, h),
            ]
        )

    @classmethod
    def t_shape(cls, w: float, h: float, stem_w: float, stem_h: float) -> "Polygon":
        """A base bar of ``w`` x (h - stem_h) with a centred stem on top."""
        if not (0 < stem_w < w and 0 < stem_h < h):
            raise ValueError("stem must be smaller than the overall footprint")
        base_h = h - stem_h
        x0 = (w - stem_w) / 2.0
        return cls(
            [
                (0, 0),
                (w, 0),
                (w, base_h),
                (x0 + stem_w, base_h),
                (x0 + stem_w, h),
                (x0, h),
                (x0, base_h),
                (0, base_h),
            ]
        )

    @classmethod
    def u_shape(cls, w: float, h: float, notch_w: float, notch_h: float) -> "Polygon":
        """Rectangle with a centred notch cut into the north edge."""
        if not (0 < notch_w < w and 0 < notch_h < h):
            raise ValueError("notch must be smaller than the overall footprint")
        x0 = (w - notch_w) / 2.0
        return cls(
            [
                (0, 0),
                (w, 0),
                (w, h),
                (x0 + notch_w, h),
                (x0 + notch_w, h - notch_h),
                (x0, h - notch_h),
                (x0, h),
                (0, h),
            ]
        )

    @property
    def area(self) -> float:
        return abs(_signed_area(self.points))

    @property
    def bounds(self) -> Rect:
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    def edges(self) -> Iterator[Segment]:
        for (ax, ay), (bx, by) in _ring_edges(self.points):
            yield Segment(ax, ay, bx, by)

    def contains_point(self, p: Point) -> bool:
        """Even-odd ray cast. Points exactly on the boundary count as inside."""
        x, y = p
        for e in self.edges():
            if e.horizontal and _almost(e.y1, y) and min(e.x1, e.x2) - EPS <= x <= max(e.x1, e.x2) + EPS:
                return True
            if e.vertical and _almost(e.x1, x) and min(e.y1, e.y2) - EPS <= y <= max(e.y1, e.y2) + EPS:
                return True
        inside = False
        for (ax, ay), (bx, by) in _ring_edges(self.points):
            if (ay > y) != (by > y):
                cross = ax + (y - ay) / (by - ay) * (bx - ax)
                if cross > x:
                    inside = not inside
        return inside

    def decompose(self) -> list[Rect]:
        """Split into a minimal-ish set of disjoint rectangles covering the polygon.

        Uses a vertical sweep: cut at every vertex x, read off the interior
        y-intervals of each strip, then merge horizontally adjacent strips that
        share the same interval.
        """
        xs = sorted({p[0] for p in self.points})
        horizontals = [e for e in self.edges() if e.horizontal]
        strips: list[list[Rect]] = []
        for x0, x1 in zip(xs, xs[1:]):
            if x1 - x0 <= EPS:
                continue
            mid = (x0 + x1) / 2.0
            crossings = sorted(
                e.y1 for e in horizontals if min(e.x1, e.x2) < mid < max(e.x1, e.x2)
            )
            strip = [
                Rect(x0, lo, x1 - x0, hi - lo)
                for lo, hi in zip(crossings[0::2], crossings[1::2])
                if hi - lo > EPS
            ]
            strips.append(strip)
        return _merge_strips(strips)


def _merge_strips(strips: list[list[Rect]]) -> list[Rect]:
    """Merge rects across adjacent strips when their y-intervals match exactly."""
    merged: list[Rect] = []
    pending: list[Rect] = []
    for strip in strips:
        still_open: list[Rect] = []
        for rect in strip:
            match = next(
                (
                    p
                    for p in pending
                    if _almost(p.y, rect.y) and _almost(p.h, rect.h) and _almost(p.x2, rect.x)
                ),
                None,
            )
            if match is not None:
                pending.remove(match)
                still_open.append(Rect(match.x, match.y, match.w + rect.w, match.h))
            else:
                still_open.append(rect)
        merged.extend(pending)
        pending = still_open
    merged.extend(pending)
    return sorted(merged, key=lambda r: (-r.area, r.x, r.y))


def _ring_edges(pts: Sequence[Point]) -> Iterator[tuple[Point, Point]]:
    for i, a in enumerate(pts):
        yield a, pts[(i + 1) % len(pts)]


def _signed_area(pts: Sequence[Point]) -> float:
    return sum(ax * by - bx * ay for (ax, ay), (bx, by) in _ring_edges(pts)) / 2.0


def _dedupe(points: Iterable[Point]) -> list[Point]:
    out: list[Point] = []
    for p in points:
        q = (float(p[0]), float(p[1]))
        if not out or not (_almost(out[-1][0], q[0]) and _almost(out[-1][1], q[1])):
            out.append(q)
    while len(out) > 1 and _almost(out[0][0], out[-1][0]) and _almost(out[0][1], out[-1][1]):
        out.pop()
    return out


def _drop_collinear(pts: list[Point]) -> list[Point]:
    out = list(pts)
    changed = True
    while changed and len(out) > 4:
        changed = False
        for i in range(len(out)):
            a, b, c = out[i - 2], out[i - 1], out[i % len(out)]
            if (_almost(a[0], b[0]) and _almost(b[0], c[0])) or (
                _almost(a[1], b[1]) and _almost(b[1], c[1])
            ):
                out.pop(i - 1)
                changed = True
                break
    return out


#: Re-exported for convenience; the formatting itself lives in :mod:`floorplan.units`.
from .units import format_feet  # noqa: E402,F401  (kept at the bottom to avoid a cycle)
