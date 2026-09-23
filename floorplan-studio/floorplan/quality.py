"""Readability checks on a finished scene.

A drawing can pass every geometric test and still be unreadable: two labels
on top of each other, a dimension figure printed at a millimetre, a room
name sitting on a wall. These are the defects the eye catches at 100 %,
50 % and 25 % zoom, so they are checked here on the scene itself — the same
primitives every backend draws — rather than on a rendered image.

The checks are deliberately few and mechanical:

* **overlap** — two texts whose boxes share more than a sliver of area.
* **small** — text that prints below :data:`MIN_PAPER_MM` at the sheet's scale
  (the 25 % test: a figure that small is gone at a quarter zoom).
* **over-wall** — a text box lying mostly on a wall fill.

Each finding carries a position in scene coordinates so the caller can point
at it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .drawing import Path, Scene, Text
from .metrics import text_width
from .render import WALL, WALL_INTERIOR
from .units import FEET_PER_METRE

MIN_PAPER_MM = 1.8       # anything smaller vanishes at 25 % zoom
OVERLAP_SHARE = 0.15     # of the smaller box; touching descenders are not a clash
WALL_SHARE = 0.30        # of the text box on wall fill before it counts

Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class Issue:
    kind: str        # overlap | small | over-wall
    message: str
    x: float
    y: float

    def __str__(self) -> str:
        return f"{self.kind}: {self.message} at ({self.x:.1f}, {self.y:.1f})"


def text_box(t: Text) -> Box:
    """Axis-aligned box of a text in scene units, allowing for anchor and rotation."""
    w, h = text_width(t.value, t.size, t.bold), t.size
    if t.anchor == "start":
        cx = t.x + w / 2.0
    elif t.anchor == "end":
        cx = t.x - w / 2.0
    else:
        cx = t.x
    cy = t.y
    rad = math.radians(t.rotate)
    c, s = abs(math.cos(rad)), abs(math.sin(rad))
    # Rotate about the anchor: the centre moves with it, then the box does.
    dx, dy = cx - t.x, cy - t.y
    rx = t.x + dx * math.cos(rad) - dy * math.sin(rad)
    ry = t.y + dx * math.sin(rad) + dy * math.cos(rad)
    hw, hh = (w * c + h * s) / 2.0, (w * s + h * c) / 2.0
    return (rx - hw, ry - hh, rx + hw, ry + hh)


def _area(b: Box) -> float:
    return max(b[2] - b[0], 0.0) * max(b[3] - b[1], 0.0)


def _intersection(a: Box, b: Box) -> float:
    return _area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def _bbox(p: Path) -> Box:
    xs = [x for x, _ in p.points]
    ys = [y for _, y in p.points]
    return (min(xs), min(ys), max(xs), max(ys))


def check_scene(scene: Scene) -> list[Issue]:
    """Every readability defect found on ``scene``, worst first."""
    issues: list[Issue] = []
    texts = [t for t in scene.texts if t.value.strip()]
    boxes = [text_box(t) for t in texts]

    # Small print. Needs the sheet's scale; a scene without one is not a sheet.
    if scene.scale is not None:
        for t in texts:
            paper_mm = t.size / FEET_PER_METRE / scene.scale.ratio * 1000.0
            if paper_mm < MIN_PAPER_MM:
                issues.append(Issue("small", f"{t.value!r} prints at {paper_mm:.1f} mm", t.x, t.y))

    # Overlaps: a sweep over boxes sorted by their left edge, so each is
    # compared only with the ones that start before it ends.
    order = sorted(range(len(texts)), key=lambda i: boxes[i][0])
    for k, i in enumerate(order):
        bi = boxes[i]
        for j in order[k + 1:]:
            bj = boxes[j]
            if bj[0] >= bi[2]:
                break
            shared = _intersection(bi, bj)
            if shared > OVERLAP_SHARE * min(_area(bi), _area(bj)):
                issues.append(Issue("overlap", f"{texts[i].value!r} and {texts[j].value!r}",
                                    (bi[0] + bi[2]) / 2.0, (bi[1] + bi[3]) / 2.0))

    # Text on a wall: only the drawing's walls, not title-block rules.
    walls = [_bbox(p) for p in scene.paths
             if p.fill in (WALL, WALL_INTERIOR) and p.layer == "A-WALL"]
    for t, b in zip(texts, boxes):
        if t.layer not in ("A-TEXT",):
            continue
        area = _area(b)
        if area <= 0:
            continue
        on_wall = 0.0
        for wb in walls:
            on_wall += _intersection(b, wb)
            if on_wall > WALL_SHARE * area:
                issues.append(Issue("over-wall", f"{t.value!r} sits on a wall", t.x, t.y))
                break

    rank = {"overlap": 0, "over-wall": 1, "small": 2}
    issues.sort(key=lambda i: rank[i.kind])
    return issues


def summary(issues: list[Issue]) -> dict:
    """Counts by kind plus the messages, for a report or a CLI line."""
    counts = {"overlap": 0, "small": 0, "over-wall": 0}
    for i in issues:
        counts[i.kind] += 1
    return {"issues": len(issues), **counts, "messages": [str(i) for i in issues[:20]]}
