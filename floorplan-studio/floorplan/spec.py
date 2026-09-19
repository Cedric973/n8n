"""The design program: what rooms to place, and the rules they prefer to follow."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from .geometry import Polygon
from .units import DEFAULT_UNITS, normalise

PUBLIC, PRIVATE, SERVICE = "public", "private", "service"


@dataclass(frozen=True)
class RoomType:
    """Design defaults for one kind of room.

    ``target_sqft`` is a wish, not a constraint: the solver scales every room so
    the program exactly fills the footprint, keeping relative proportions.
    """

    key: str
    label: str
    zone: str
    target_sqft: float
    min_dim: float
    max_aspect: float = 2.2
    needs_exterior: bool = False
    wet: bool = False
    privacy: float = 0.0  # 0 = fully public, 1 = fully private
    fill: str = "#f4f4f2"


CATALOG: dict[str, RoomType] = {
    r.key: r
    for r in [
        RoomType("living", "Living", PUBLIC, 260, 11.5, 1.9, needs_exterior=True, fill="#eef2f7"),
        RoomType("family", "Family", PUBLIC, 230, 11.0, 1.9, needs_exterior=True, fill="#eef2f7"),
        RoomType("dining", "Dining", PUBLIC, 150, 9.5, 1.8, needs_exterior=True, fill="#eef2f7"),
        RoomType("kitchen", "Kitchen", PUBLIC, 165, 8.5, 2.4, needs_exterior=True, wet=True, fill="#eaf3ee"),
        RoomType("pantry", "Pantry", PUBLIC, 30, 3.5, 3.0, fill="#eaf3ee"),
        RoomType("foyer", "Foyer", PUBLIC, 60, 5.0, 2.6, needs_exterior=True, fill="#f7f4ee"),
        RoomType("office", "Office", PUBLIC, 120, 8.5, 1.9, needs_exterior=True, privacy=0.5, fill="#f2f0f7"),
        RoomType("powder", "Powder", PUBLIC, 26, 4.0, 2.4, wet=True, privacy=0.8, fill="#e8f1f6"),
        RoomType("primary_bedroom", "Primary Bedroom", PRIVATE, 240, 11.5, 1.8, needs_exterior=True, privacy=1.0, fill="#f6f1ee"),
        RoomType("bedroom", "Bedroom", PRIVATE, 135, 10.0, 1.8, needs_exterior=True, privacy=1.0, fill="#f6f1ee"),
        RoomType("primary_bath", "Primary Bath", PRIVATE, 85, 5.5, 2.6, wet=True, privacy=1.0, fill="#e8f1f6"),
        RoomType("bathroom", "Bath", PRIVATE, 50, 5.0, 2.6, wet=True, privacy=0.9, fill="#e8f1f6"),
        RoomType("closet", "Closet", PRIVATE, 32, 3.5, 3.4, privacy=1.0, fill="#f1efec"),
        RoomType("hall", "Hall", PRIVATE, 90, 3.0, 12.0, fill="#faf9f7"),
        RoomType("laundry", "Laundry", SERVICE, 45, 5.0, 2.6, wet=True, fill="#eef0ee"),
        RoomType("mudroom", "Mud", SERVICE, 50, 5.0, 2.6, needs_exterior=True, fill="#eef0ee"),
        RoomType("garage", "Garage", SERVICE, 420, 18.0, 1.6, needs_exterior=True, fill="#ecebe8"),
        RoomType("utility", "Utility", SERVICE, 40, 4.5, 2.8, fill="#eef0ee"),
    ]
}

ZONE_ORDER = {PUBLIC: 0, PRIVATE: 1, SERVICE: 2}

#: Pairs that should share a wall, with a weight. Keys are room-type keys.
PREFERRED_ADJACENCY: list[tuple[str, str, float]] = [
    ("kitchen", "dining", 3.0),
    ("kitchen", "pantry", 2.5),
    ("kitchen", "family", 2.0),
    ("dining", "living", 2.5),
    ("foyer", "living", 2.0),
    ("primary_bedroom", "primary_bath", 4.0),
    ("primary_bedroom", "closet", 2.0),
    ("laundry", "mudroom", 1.5),
    ("kitchen", "mudroom", 1.0),
    ("kitchen", "laundry", 1.0),
    ("garage", "mudroom", 2.5),
]

#: Pairs that should *not* share a wall, with a penalty weight.
AVOIDED_ADJACENCY: list[tuple[str, str, float]] = [
    ("bedroom", "living", 1.5),
    ("bedroom", "family", 1.5),
    ("bedroom", "kitchen", 2.0),
    ("bedroom", "garage", 2.5),
    ("primary_bedroom", "living", 1.5),
    ("primary_bedroom", "garage", 2.5),
    ("bathroom", "kitchen", 2.0),
    ("bathroom", "dining", 2.5),
    ("powder", "dining", 2.0),
    ("garage", "living", 1.5),
]


@dataclass
class RoomSpec:
    """One room instance in the program."""

    type_key: str
    name: str | None = None
    sqft: float | None = None  # explicit override of the catalog target

    @property
    def room_type(self) -> RoomType:
        try:
            return CATALOG[self.type_key]
        except KeyError:
            raise ValueError(f"unknown room type {self.type_key!r}") from None

    @property
    def label(self) -> str:
        return self.name or self.room_type.label

    @property
    def target_sqft(self) -> float:
        return self.sqft if self.sqft is not None else self.room_type.target_sqft


@dataclass
class PlanSpec:
    """A complete request: a footprint plus the rooms that must fit inside it."""

    footprint: Polygon
    rooms: list[RoomSpec]
    title: str = "Untitled Plan"
    exterior_wall: float = 0.83  # ~10 in, framed 2x6 wall with sheathing
    interior_wall: float = 0.42  # ~5 in
    hall_width: float = 3.5
    door_width: float = 2.75
    entry_door_width: float = 3.0
    max_aspect: float = 2.4
    seed: int = 0
    units: str = DEFAULT_UNITS  # presentation only; geometry is always in feet

    def __post_init__(self) -> None:
        self.units = normalise(self.units)
        if not self.rooms:
            raise ValueError("a plan needs at least one room")
        for room in self.rooms:
            room.room_type  # validates the type key eagerly
        if self.footprint.area <= 0:
            raise ValueError("footprint has no area")

    @property
    def total_target(self) -> float:
        return sum(r.target_sqft for r in self.rooms)

    def scaled_areas(self) -> list[float]:
        """Room areas scaled so the program exactly fills the footprint."""
        factor = self.footprint.area / self.total_target
        return [r.target_sqft * factor for r in self.rooms]

    def with_seed(self, seed: int) -> "PlanSpec":
        return replace(self, rooms=list(self.rooms), seed=seed)

    # -- program building -------------------------------------------------

    @classmethod
    def from_program(
        cls,
        footprint: Polygon,
        *,
        bedrooms: int = 3,
        bathrooms: int = 2,
        office: bool = False,
        garage: bool = False,
        formal_dining: bool = True,
        laundry: bool = True,
        mudroom: bool = False,
        pantry: bool = True,
        **kwargs: Any,
    ) -> "PlanSpec":
        """Build a conventional single-storey program from a room count."""
        if bedrooms < 1:
            raise ValueError("a house needs at least one bedroom")
        if bathrooms < 1:
            raise ValueError("a house needs at least one bathroom")

        rooms = [RoomSpec("foyer"), RoomSpec("living"), RoomSpec("kitchen")]
        if formal_dining:
            rooms.append(RoomSpec("dining"))
        if pantry:
            rooms.append(RoomSpec("pantry"))
        if office:
            rooms.append(RoomSpec("office"))

        rooms.append(RoomSpec("primary_bedroom"))
        rooms.append(RoomSpec("primary_bath"))
        rooms.append(RoomSpec("closet", name="W.I.C."))
        for i in range(bedrooms - 1):
            rooms.append(RoomSpec("bedroom", name=f"Bedroom {i + 2}"))

        # The primary bath already covers one; the rest are shared or powder rooms.
        extra_baths = bathrooms - 1
        full = min(extra_baths, max(bedrooms - 1, 0))
        for i in range(full):
            rooms.append(RoomSpec("bathroom", name=f"Bath {i + 2}"))
        for _ in range(extra_baths - full):
            rooms.append(RoomSpec("powder"))

        if bedrooms >= 2:
            rooms.append(RoomSpec("hall"))
        if laundry:
            rooms.append(RoomSpec("laundry"))
        if mudroom:
            rooms.append(RoomSpec("mudroom"))
        if garage:
            rooms.append(RoomSpec("garage"))

        return cls(footprint=footprint, rooms=rooms, **kwargs)

    # -- serialisation ----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "footprint": [list(p) for p in self.footprint.points],
            "rooms": [
                {"type": r.type_key, "name": r.name, "sqft": r.sqft} for r in self.rooms
            ],
            "exterior_wall": self.exterior_wall,
            "interior_wall": self.interior_wall,
            "hall_width": self.hall_width,
            "door_width": self.door_width,
            "max_aspect": self.max_aspect,
            "seed": self.seed,
            "units": self.units,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlanSpec":
        known = {
            "title", "exterior_wall", "interior_wall", "hall_width",
            "door_width", "entry_door_width", "max_aspect", "seed", "units",
        }
        kwargs = {k: data[k] for k in known if k in data and data[k] is not None}
        return cls(
            footprint=Polygon([tuple(p) for p in data["footprint"]]),
            rooms=[
                RoomSpec(r["type"], r.get("name"), r.get("sqft")) for r in data["rooms"]
            ],
            **kwargs,
        )


def adjacency_weight(a: str, b: str, table: list[tuple[str, str, float]]) -> float:
    for x, y, w in table:
        if (a == x and b == y) or (a == y and b == x):
            return w
    return 0.0
