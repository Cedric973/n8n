"""The drawing model the converter works on.

The generator's :class:`~floorplan.plan.Plan` knows rooms as rectangles. An
imported drawing knows nothing of the sort: it is lines, arcs and text on
layers, from which walls and doors have to be recognised. So the converter has
its own model — a flat list of entities — and carries, on every one of them,
where the knowledge came from.

Provenance is the point of the whole exercise. A wall that was on a layer
called WALL in the source is *verified*; a wall guessed from two parallel lines
is *inferred*; a real-world length worked out from a printed scale is
*calculated*; and what could not be determined is *unknown* and stays that
way. Nothing is promoted silently.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator

Point = tuple[float, float]


class Provenance(str, Enum):
    VERIFIED = "verified"      # visible in, or directly extracted from, the source
    CALCULATED = "calculated"  # derived mathematically from reliable source data
    INFERRED = "inferred"      # a likely interpretation, not directly confirmed
    UNKNOWN = "unknown"        # could not be determined reliably

    @property
    def rank(self) -> int:
        return ["unknown", "inferred", "calculated", "verified"].index(self.value)


class Role(str, Enum):
    """What an entity is, once the analyzer has had a look at it."""

    WALL = "wall"
    DOOR = "door"
    WINDOW = "window"
    COLUMN = "column"
    STAIR = "stair"
    FURNITURE = "furniture"
    EQUIPMENT = "equipment"
    DIMENSION = "dimension"
    TEXT = "text"
    GRID = "grid"
    SHEET = "sheet"        # title block, border, north arrow
    OTHER = "other"


#: AIA layer for each role, on export.
AIA_LAYER = {
    Role.WALL: "A-WALL", Role.DOOR: "A-DOOR", Role.WINDOW: "A-WIND",
    Role.COLUMN: "A-COLS", Role.STAIR: "A-STRS", Role.FURNITURE: "A-FURN",
    Role.EQUIPMENT: "A-EQPM", Role.DIMENSION: "A-DIMS", Role.TEXT: "A-TEXT",
    Role.GRID: "A-GRID", Role.SHEET: "G-ANNO", Role.OTHER: "A-MISC",
}


@dataclass
class Entity:
    """One drawn thing. Coordinates are in the drawing's current units."""

    kind: str                       # line | polyline | arc | circle | text | dimension
    points: list[Point] = field(default_factory=list)
    closed: bool = False
    layer: str = "0"                # the source layer, verbatim
    text: str | None = None
    height: float | None = None     # text height, drawing units
    rotation: float = 0.0           # degrees, text
    center: Point | None = None     # arc / circle
    radius: float | None = None
    start_angle: float | None = None  # degrees, arc
    end_angle: float | None = None
    lineweight: float | None = None   # mm, when the source says
    role: Role = Role.OTHER
    provenance: Provenance = Provenance.VERIFIED
    source_id: str = ""
    thickness: float | None = None  # walls: the detected width
    filled: bool = False            # a solid shape rather than an outline
    color: str | None = None        # #rrggbb when the source says
    meta: dict = field(default_factory=dict)  # reader-specific extras (anchor, measurement)

    # -- geometry helpers -------------------------------------------------

    def segments(self) -> Iterator[tuple[Point, Point]]:
        pts = list(self.points)
        if self.closed and len(pts) > 2:
            pts.append(pts[0])
        yield from zip(pts, pts[1:])

    @property
    def length(self) -> float:
        if self.kind == "arc" and self.radius is not None:
            sweep = abs((self.end_angle or 0.0) - (self.start_angle or 0.0))
            return math.radians(sweep) * self.radius
        if self.kind == "circle" and self.radius is not None:
            return 2 * math.pi * self.radius
        return sum(math.dist(a, b) for a, b in self.segments())

    def bounds(self) -> tuple[float, float, float, float] | None:
        pts = list(self.points)
        if self.center is not None and self.radius is not None:
            cx, cy = self.center
            r = self.radius
            pts += [(cx - r, cy - r), (cx + r, cy + r)]
        if not pts:
            return None
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return (min(xs), min(ys), max(xs), max(ys))

    def transformed(self, factor: float, dx: float = 0.0, dy: float = 0.0) -> "Entity":
        """A copy scaled uniformly and shifted — used to move into metres."""
        out = Entity(**{k: v for k, v in self.__dict__.items()})
        out.meta = dict(self.meta)
        out.points = [(x * factor + dx, y * factor + dy) for x, y in self.points]
        if self.center is not None:
            out.center = (self.center[0] * factor + dx, self.center[1] * factor + dy)
        if self.radius is not None:
            out.radius = self.radius * factor
        if self.height is not None:
            out.height = self.height * factor
        if self.thickness is not None:
            out.thickness = self.thickness * factor
        return out


@dataclass
class Drawing:
    """A parsed source, with what is known about it and how well."""

    entities: list[Entity] = field(default_factory=list)
    source: str = ""
    format: str = ""                    # dxf | svg | pdf
    units: str | None = None            # m | mm | cm | ft | in | pt | None
    units_provenance: Provenance = Provenance.UNKNOWN
    to_metres: float | None = None      # multiply a coordinate by this to get metres
    scale_provenance: Provenance = Provenance.UNKNOWN
    scale_label: str | None = None      # "1:100", "1/4\" = 1'-0\"" as read
    sheets: int = 1
    quality: str = "UNKNOWN"            # EXCELLENT .. UNUSABLE
    notes: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    # -- queries ----------------------------------------------------------

    def bounds(self) -> tuple[float, float, float, float] | None:
        boxes = [b for b in (e.bounds() for e in self.entities) if b is not None]
        if not boxes:
            return None
        return (min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes))

    def by_role(self, role: Role) -> list[Entity]:
        return [e for e in self.entities if e.role == role]

    def texts(self) -> list[Entity]:
        return [e for e in self.entities if e.kind == "text" and e.text]

    def layers(self) -> list[str]:
        return sorted({e.layer for e in self.entities})

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in self.entities:
            out[e.role.value] = out.get(e.role.value, 0) + 1
        return out

    def provenance_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in self.entities:
            out[e.provenance.value] = out.get(e.provenance.value, 0) + 1
        return out

    def note(self, message: str) -> None:
        if message not in self.notes:
            self.notes.append(message)

    def in_metres(self) -> "Drawing":
        """A copy with every coordinate converted to metres, if the factor is known."""
        if self.to_metres is None or self.units == "m":
            return self
        out = Drawing(**{k: v for k, v in self.__dict__.items() if k != "entities"})
        out.entities = [e.transformed(self.to_metres) for e in self.entities]
        # Paper units stay labelled as paper: the numbers are metres of page,
        # not metres of building, and pretending otherwise is the one lie the
        # provenance model exists to prevent.
        out.units = "paper" if self.units == "paper" else "m"
        out.to_metres = 1.0
        return out


#: Metres per unit, for the units a source can declare.
UNIT_TO_METRES = {
    "m": 1.0, "mm": 0.001, "cm": 0.01, "dm": 0.1, "km": 1000.0,
    "ft": 0.3048, "in": 0.0254, "yd": 0.9144, "pt": 0.0254 / 72.0, "px": 0.0254 / 96.0,
}
