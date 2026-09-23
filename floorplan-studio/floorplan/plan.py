"""Result types produced by the layout solver."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .geometry import EPS, Polygon, Rect, Segment
from .spec import PlanSpec, RoomSpec, RoomType


@dataclass
class PlacedRoom:
    index: int
    spec: RoomSpec
    rect: Rect

    @property
    def room_type(self) -> RoomType:
        return self.spec.room_type

    @property
    def type_key(self) -> str:
        return self.spec.type_key

    @property
    def zone(self) -> str:
        return self.room_type.zone

    @property
    def label(self) -> str:
        return self.spec.label

    @property
    def area(self) -> float:
        return self.rect.area

    def net_rect(self, spec: PlanSpec, footprint: Polygon) -> Rect:
        """The room rect pulled back to the inside face of its walls."""
        ext = spec.exterior_wall / 2.0
        inte = spec.interior_wall / 2.0
        on_ext = _edges_on_boundary(self.rect, footprint)
        west = ext if on_ext["west"] else inte
        east = ext if on_ext["east"] else inte
        south = ext if on_ext["south"] else inte
        north = ext if on_ext["north"] else inte
        return Rect(
            self.rect.x + west,
            self.rect.y + south,
            max(self.rect.w - west - east, 0.0),
            max(self.rect.h - south - north, 0.0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "type": self.type_key,
            "label": self.label,
            "zone": self.zone,
            "x": round(self.rect.x, 4),
            "y": round(self.rect.y, 4),
            "w": round(self.rect.w, 4),
            "h": round(self.rect.h, 4),
            "sqft": round(self.area, 1),
        }


@dataclass
class Opening:
    """A door, cased opening, or window sitting in a wall."""

    kind: str  # "door" | "opening" | "entry" | "garage" | "window"
    segment: Segment
    rooms: tuple[int, ...] = ()
    hinge: str = "left"

    @property
    def width(self) -> float:
        return self.segment.length

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "x1": round(self.segment.x1, 4),
            "y1": round(self.segment.y1, 4),
            "x2": round(self.segment.x2, 4),
            "y2": round(self.segment.y2, 4),
            "rooms": list(self.rooms),
            "hinge": self.hinge,
        }


@dataclass
class Plan:
    spec: PlanSpec
    rooms: list[PlacedRoom]
    openings: list[Opening] = field(default_factory=list)
    score: float = 0.0
    penalties: dict[str, float] = field(default_factory=dict)
    seed: int = 0

    @property
    def footprint(self) -> Polygon:
        return self.spec.footprint

    @property
    def total_sqft(self) -> float:
        return sum(r.area for r in self.rooms)

    @property
    def conditioned_sqft(self) -> float:
        """Living area, i.e. everything except the garage."""
        return sum(r.area for r in self.rooms if r.type_key != "garage")

    @property
    def bedroom_count(self) -> int:
        return sum(1 for r in self.rooms if r.type_key in ("bedroom", "primary_bedroom"))

    @property
    def bath_count(self) -> float:
        full = sum(1 for r in self.rooms if r.type_key in ("bathroom", "primary_bath"))
        half = sum(1 for r in self.rooms if r.type_key == "powder")
        return full + 0.5 * half

    def room(self, index: int) -> PlacedRoom:
        return self.rooms[index]

    def summary(self) -> dict[str, Any]:
        baths = self.bath_count
        return {
            "title": self.spec.title,
            "seed": self.seed,
            "score": round(self.score, 2),
            "total_sqft": round(self.total_sqft),
            "conditioned_sqft": round(self.conditioned_sqft),
            "bedrooms": self.bedroom_count,
            "bathrooms": int(baths) if baths == int(baths) else baths,
            "rooms": len(self.rooms),
            "penalties": {k: round(v, 2) for k, v in sorted(self.penalties.items())},
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary(),
            "spec": self.spec.to_dict(),
            "rooms": [r.to_dict() for r in self.rooms],
            "openings": [o.to_dict() for o in self.openings],
        }


def _edges_on_boundary(rect: Rect, footprint: Polygon, tol: float = 1e-4) -> dict[str, bool]:
    result = {"west": False, "east": False, "south": False, "north": False}
    for name, edge in rect.edges().items():
        for b in footprint.edges():
            if edge.vertical and b.vertical and abs(edge.x1 - b.x1) <= tol:
                lo, hi = max(min(edge.y1, edge.y2), min(b.y1, b.y2)), min(
                    max(edge.y1, edge.y2), max(b.y1, b.y2)
                )
                if hi - lo > tol:
                    result[name] = True
            elif edge.horizontal and b.horizontal and abs(edge.y1 - b.y1) <= tol:
                lo, hi = max(min(edge.x1, edge.x2), min(b.x1, b.x2)), min(
                    max(edge.x1, edge.x2), max(b.x1, b.x2)
                )
                if hi - lo > tol:
                    result[name] = True
    return result


def exterior_segments(rect: Rect, footprint: Polygon, tol: float = 1e-4) -> list[Segment]:
    """The parts of ``rect``'s perimeter that sit on the footprint boundary."""
    out: list[Segment] = []
    for edge in rect.edges().values():
        for b in footprint.edges():
            if edge.vertical and b.vertical and abs(edge.x1 - b.x1) <= tol:
                lo = max(min(edge.y1, edge.y2), min(b.y1, b.y2))
                hi = min(max(edge.y1, edge.y2), max(b.y1, b.y2))
                if hi - lo > tol:
                    out.append(Segment(edge.x1, lo, edge.x1, hi))
            elif edge.horizontal and b.horizontal and abs(edge.y1 - b.y1) <= tol:
                lo = max(min(edge.x1, edge.x2), min(b.x1, b.x2))
                hi = min(max(edge.x1, edge.x2), max(b.x1, b.x2))
                if hi - lo > tol:
                    out.append(Segment(lo, edge.y1, hi, edge.y1))
    return out
