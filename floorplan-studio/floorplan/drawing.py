"""A backend-independent drawing scene.

Everything is expressed in world coordinates — feet, y pointing up — so the
SVG, PDF and DXF backends all serialise the same geometry and cannot drift
apart. Each backend applies its own transform: SVG and PDF fit the scene to a
page, DXF writes it at 1:1 into model space.

Sizes are in feet too, the way a CAD drawing states text height in drawing
units. A backend scales them along with the geometry and enforces its own
minimum stroke width so hairlines stay visible.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .geometry import Rect

Point = tuple[float, float]

HAIRLINE = 0.02  # feet


@dataclass
class Path:
    """A polyline or polygon. ``fill`` and ``stroke`` are ``#rrggbb`` or None."""

    points: list[Point]
    closed: bool = False
    fill: str | None = None
    stroke: str | None = None
    width: float = HAIRLINE
    dash: tuple[float, ...] | None = None
    layer: str = "PLAN"


@dataclass
class Text:
    x: float
    y: float
    value: str
    size: float = 0.7
    anchor: str = "middle"  # start | middle | end
    bold: bool = False
    color: str = "#1a1a1a"
    rotate: float = 0.0  # degrees, counter-clockwise
    layer: str = "TEXT"


@dataclass
class Scene:
    bounds: Rect
    items: list[Path | Text] = field(default_factory=list)
    background: str = "#ffffff"
    title: str = "Floor Plan"

    # -- primitives -------------------------------------------------------

    def add(self, item: Path | Text) -> None:
        self.items.append(item)

    def rect(self, r: Rect, **kwargs) -> None:
        self.add(Path(list(r.corners), closed=True, **kwargs))

    def line(self, x1: float, y1: float, x2: float, y2: float, **kwargs) -> None:
        self.add(Path([(x1, y1), (x2, y2)], **kwargs))

    def polyline(self, points: list[Point], **kwargs) -> None:
        self.add(Path(list(points), **kwargs))

    def text(self, x: float, y: float, value: str, **kwargs) -> None:
        self.add(Text(x, y, value, **kwargs))

    def arc(
        self, cx: float, cy: float, radius: float, start: float, end: float, segments: int = 24, **kwargs
    ) -> None:
        """An arc as a polyline; ``start`` and ``end`` are radians."""
        step = (end - start) / max(segments, 1)
        points = [
            (cx + radius * math.cos(start + step * i), cy + radius * math.sin(start + step * i))
            for i in range(segments + 1)
        ]
        self.polyline(points, **kwargs)

    # -- queries ----------------------------------------------------------

    @property
    def paths(self) -> list[Path]:
        return [i for i in self.items if isinstance(i, Path)]

    @property
    def texts(self) -> list[Text]:
        return [i for i in self.items if isinstance(i, Text)]

    def layers(self) -> list[str]:
        return sorted({i.layer for i in self.items})


def fit_scale(bounds: Rect, width: float, height: float, margin: float = 0.0) -> float:
    """Units per foot that fits ``bounds`` into a ``width`` x ``height`` page."""
    usable_w = max(width - 2 * margin, 1e-6)
    usable_h = max(height - 2 * margin, 1e-6)
    return min(usable_w / max(bounds.w, 1e-6), usable_h / max(bounds.h, 1e-6))


def hex_to_rgb(color: str) -> tuple[float, float, float]:
    value = color.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    return tuple(int(value[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]
