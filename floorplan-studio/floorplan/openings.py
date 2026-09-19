"""Door and window placement.

Doors come from a spanning tree over the room-adjacency graph, rooted at the
entry. Rooms that should only ever be entered from one place (baths, closets,
the garage) are forced to be leaves of that tree, so you never have to walk
through a bathroom to reach a bedroom.
"""

from __future__ import annotations

import heapq
from typing import TYPE_CHECKING

from .geometry import Rect, Segment, shared_wall
from .plan import Opening, PlacedRoom, exterior_segments
from .spec import AVOIDED_ADJACENCY, PREFERRED_ADJACENCY, adjacency_weight

if TYPE_CHECKING:  # pragma: no cover
    from .plan import Plan

#: Rooms you enter from exactly one other room.
TERMINAL = {"bathroom", "primary_bath", "powder", "closet", "pantry", "utility", "garage"}

#: Rooms that get a cased opening rather than a door leaf.
OPEN_PAIRS = {
    frozenset(("kitchen", "dining")),
    frozenset(("living", "dining")),
    frozenset(("kitchen", "family")),
    frozenset(("foyer", "living")),
    frozenset(("hall", "foyer")),
}

MIN_WINDOW_WALL = 5.0
MAX_WINDOW = 6.0
GARAGE_DOOR = 16.0
JAMB = 0.6  # clearance kept at each end of a wall so doors miss the corners


def adjacency_graph(rooms: list[PlacedRoom], min_wall: float) -> dict[tuple[int, int], Segment]:
    graph: dict[tuple[int, int], Segment] = {}
    for a in range(len(rooms)):
        for b in range(a + 1, len(rooms)):
            if rooms[a].rect.area <= 0 or rooms[b].rect.area <= 0:
                continue
            seg = shared_wall(rooms[a].rect, rooms[b].rect)
            if seg is not None and seg.length >= min_wall:
                graph[(a, b)] = seg
    return graph


def _edge_cost(a: PlacedRoom, b: PlacedRoom, seg: Segment) -> float:
    cost = 1.0
    if "hall" in (a.type_key, b.type_key):
        cost = 0.2
    elif "foyer" in (a.type_key, b.type_key):
        cost = 0.5
    if adjacency_weight(a.type_key, b.type_key, PREFERRED_ADJACENCY):
        cost *= 0.4
    if adjacency_weight(a.type_key, b.type_key, AVOIDED_ADJACENCY):
        cost *= 3.0
    return cost - min(seg.length, 20.0) * 0.005


def _entry_room(plan: "Plan") -> int:
    """The most public room with an exterior wall wide enough for a front door."""
    rooms = plan.rooms
    needed = plan.spec.entry_door_width + 2 * JAMB
    reachable = {
        r.index
        for r in rooms
        if r.rect.area > 0
        and any(s.length >= needed for s in exterior_segments(r.rect, plan.footprint))
    }
    for key in ("foyer", "mudroom", "living", "family", "kitchen", "dining"):
        for room in rooms:
            if room.type_key == key and room.index in reachable:
                return room.index
    if reachable:
        return max(reachable, key=lambda i: rooms[i].rect.area)
    return max(range(len(rooms)), key=lambda i: rooms[i].rect.area)


def circulation_tree(
    rooms: list[PlacedRoom], graph: dict[tuple[int, int], Segment], root: int
) -> list[tuple[int, int]]:
    """Prim's algorithm, never expanding outward *through* a terminal room."""
    visited = {root}
    heap: list[tuple[float, int, int]] = []

    def push_from(node: int) -> None:
        if rooms[node].type_key in TERMINAL and node != root:
            return
        for (a, b), seg in graph.items():
            for src, dst in ((a, b), (b, a)):
                if src == node and dst not in visited:
                    heapq.heappush(heap, (_edge_cost(rooms[src], rooms[dst], seg), src, dst))

    push_from(root)
    tree: list[tuple[int, int]] = []
    while heap:
        _, src, dst = heapq.heappop(heap)
        if dst in visited:
            continue
        visited.add(dst)
        tree.append((src, dst))
        push_from(dst)
    return tree


def _door_segment(seg: Segment, width: float) -> Segment:
    """Centre a leaf of ``width`` in the wall, keeping clear of the corners."""
    usable = max(seg.length - 2 * JAMB, min(seg.length, width))
    return seg.sub(0.5, min(width, usable))


def _kind_for(a: PlacedRoom, b: PlacedRoom) -> str:
    return "opening" if frozenset((a.type_key, b.type_key)) in OPEN_PAIRS else "door"


def build_openings(plan: "Plan") -> list[Opening]:
    spec = plan.spec
    rooms = plan.rooms
    graph = adjacency_graph(rooms, spec.door_width)
    root = _entry_room(plan)
    tree = circulation_tree(rooms, graph, root)

    openings: list[Opening] = []
    used: set[frozenset[int]] = set()
    for src, dst in tree:
        seg = graph.get((min(src, dst), max(src, dst)))
        if seg is None:
            continue
        a, b = rooms[src], rooms[dst]
        swing_first = (a.index, b.index) if a.area >= b.area else (b.index, a.index)
        openings.append(
            Opening(
                kind=_kind_for(a, b),
                segment=_door_segment(seg, spec.door_width),
                rooms=swing_first,
                hinge="left" if (src + dst) % 2 == 0 else "right",
            )
        )
        used.add(frozenset((src, dst)))

    # Cased openings between public rooms that want to flow together.
    for (a, b), seg in graph.items():
        if frozenset((a, b)) in used:
            continue
        ra, rb = rooms[a], rooms[b]
        if frozenset((ra.type_key, rb.type_key)) not in OPEN_PAIRS:
            continue
        openings.append(
            Opening(
                kind="opening",
                segment=_door_segment(seg, min(spec.door_width * 2, seg.length - 2 * JAMB)),
                rooms=(ra.index, rb.index),
            )
        )
        used.add(frozenset((a, b)))

    openings.extend(_exterior_openings(plan, root))
    openings.extend(_windows(plan, openings))
    return openings


def _front_first(segments: list[Segment], footprint_bounds: Rect) -> list[Segment]:
    """Prefer the south façade, then the longest wall."""
    def rank(seg: Segment) -> tuple[int, float]:
        on_front = seg.horizontal and abs(seg.y1 - footprint_bounds.y) < 1e-4
        return (0 if on_front else 1, -seg.length)

    return sorted(segments, key=rank)


def _exterior_openings(plan: "Plan", root: int) -> list[Opening]:
    bounds = plan.footprint.bounds
    out: list[Opening] = []
    entry = plan.rooms[root]
    segs = _front_first(exterior_segments(entry.rect, plan.footprint), bounds)
    segs = [s for s in segs if s.length >= plan.spec.entry_door_width + 2 * JAMB]
    if segs:
        out.append(
            Opening("entry", _door_segment(segs[0], plan.spec.entry_door_width), (entry.index,))
        )
    for room in plan.rooms:
        if room.type_key != "garage" or room.rect.area <= 0:
            continue
        gsegs = _front_first(exterior_segments(room.rect, plan.footprint), bounds)
        gsegs = [s for s in gsegs if s.length >= 10.0]
        if gsegs:
            width = min(GARAGE_DOOR, gsegs[0].length - 2 * JAMB)
            out.append(Opening("garage", _door_segment(gsegs[0], width), (room.index,)))
    return out


def _windows(plan: "Plan", existing: list[Opening]) -> list[Opening]:
    doors = [o for o in existing if o.kind in ("entry", "garage")]
    out: list[Opening] = []
    for room in plan.rooms:
        rt = room.room_type
        if room.rect.area <= 0 or rt.key in ("closet", "pantry", "hall", "utility"):
            continue
        for seg in exterior_segments(room.rect, plan.footprint):
            if seg.length < MIN_WINDOW_WALL:
                continue
            if any(_collinear_overlap(seg, d.segment) for d in doors):
                continue
            width = min(0.45 * seg.length, MAX_WINDOW)
            out.append(Opening("window", seg.sub(0.5, width), (room.index,)))
    return out


def _collinear_overlap(a: Segment, b: Segment, tol: float = 1e-4) -> bool:
    if a.vertical and b.vertical and abs(a.x1 - b.x1) < tol:
        return min(a.y2, b.y2) - max(a.y1, b.y1) > tol
    if a.horizontal and b.horizontal and abs(a.y1 - b.y1) < tol:
        return min(a.x2, b.x2) - max(a.x1, b.x1) > tol
    return False
