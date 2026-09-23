"""The layout solver.

For one seed:

1. Decompose the footprint into rectangles (an L-shape gives two, and so on).
2. Scale the room program so its areas exactly fill the footprint.
3. Pack rooms into those rectangles in zone order, so public / private /
   service rooms stay clustered.
4. Slice each rectangle into zone blocks, then each zone block into rooms, by
   recursive guillotine cuts. Cuts run across the long side of the rectangle
   and are rejected when they would starve a room of its minimum dimension.
   A private block with enough rooms first gets a corridor carved out of it,
   running toward whichever side faces the rest of the house.
5. Hand the result to :mod:`floorplan.openings` for doors and windows, and to
   :mod:`floorplan.scoring` for a verdict.

Rooms are sliced in a designed sequence rather than by size alone, because a
guillotine cut keeps neighbours in the sequence next to each other: listing the
kitchen after the dining room is what makes them share a wall.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .geometry import EPS, Polygon, Rect
from .openings import build_openings
from .plan import Plan, PlacedRoom
from .scoring import score_plan
from .spec import PRIVATE, PUBLIC, SERVICE, PlanSpec

MIN_CORRIDOR_ROOMS = 3

#: Placement order within a zone. Adjacent entries tend to end up adjacent.
SEQUENCE = [
    "foyer", "living", "family", "dining", "kitchen", "pantry", "office", "powder",
    "primary_bedroom", "primary_bath", "closet", "hall", "bedroom", "bathroom",
    "mudroom", "laundry", "utility", "garage",
]
SEQUENCE_RANK = {key: i for i, key in enumerate(SEQUENCE)}

ZONE_CYCLES = [
    [PUBLIC, PRIVATE, SERVICE],
    [PRIVATE, PUBLIC, SERVICE],
    [PUBLIC, SERVICE, PRIVATE],
]


#: Rooms that belong to whatever precedes them in the sequence and are never
#: cut away from it: a pantry serves its kitchen, a walk-in serves its bedroom.
ATTACHED = {"primary_bath", "closet", "pantry", "utility"}

#: A zone smaller than this share of its rectangle cannot hold its own block,
#: so its rooms are folded into the neighbouring zone instead.
MIN_ZONE_SHARE = 0.13


@dataclass
class _Item:
    """A room (or a whole zone) carrying the area it wants."""

    key: int | str
    area: float
    min_dim: float = 0.0
    attach: bool = False  # cannot be cut away from the preceding item


# --------------------------------------------------------------------------
# guillotine slicing
# --------------------------------------------------------------------------

def slice_layout(items: list[_Item], rect: Rect, rng: random.Random) -> dict[int | str, Rect]:
    """Fill ``rect`` with ``items``, in order, by recursive guillotine cuts."""
    live = [i for i in items if i.area > EPS]
    if not live or rect.area <= EPS:
        return {}
    total = sum(i.area for i in live)
    scale = rect.area / total
    scaled = [_Item(i.key, i.area * scale, i.min_dim) for i in live]
    out: dict[int | str, Rect] = {}
    _slice(scaled, rect, out, rng)
    return out


def _slice(items: list[_Item], rect: Rect, out: dict[int | str, Rect], rng: random.Random) -> None:
    if len(items) == 1:
        out[items[0].key] = rect
        return

    total = sum(i.area for i in items)
    cut = _balanced_prefix(items, total)
    head, tail = items[:cut], items[cut:]
    frac = sum(i.area for i in head) / total
    need_head = max(i.min_dim for i in head)
    need_tail = max(i.min_dim for i in tail)

    candidates = []
    for vertical in (rect.w >= rect.h, rect.w < rect.h):
        span = rect.w if vertical else rect.h
        # Give each side the depth its narrowest room needs, even at the cost
        # of some area error: a 2 ft laundry is not a laundry.
        depth = _clamp_split(span * frac, span, need_head, need_tail)
        if vertical:
            a = Rect(rect.x, rect.y, depth, rect.h)
            b = Rect(a.x2, rect.y, rect.w - depth, rect.h)
        else:
            a = Rect(rect.x, rect.y, rect.w, depth)
            b = Rect(rect.x, a.y2, rect.w, rect.h - depth)
        starved = max(0.0, need_head - a.min_dim) + max(0.0, need_tail - b.min_dim)
        stretched = max(0.0, a.aspect - 2.6) + max(0.0, b.aspect - 2.6)
        drift = abs(a.area / rect.area - frac) * 4.0
        candidates.append((starved * 12.0 + stretched + drift, vertical, a, b))

    candidates.sort(key=lambda c: c[0])
    if abs(candidates[0][0] - candidates[1][0]) < 1e-9 and rng.random() < 0.5:
        candidates.reverse()
    _, _, rect_head, rect_tail = candidates[0]
    _slice(head, rect_head, out, rng)
    _slice(tail, rect_tail, out, rng)


def _clamp_split(depth: float, span: float, need_head: float, need_tail: float) -> float:
    """Push a cut far enough from both edges for each side to be usable."""
    if need_head + need_tail > span:
        # Neither side can have what it wants; share out the shortfall instead
        # of letting the area split hand one of them a corridor-width slot.
        if need_head + need_tail <= 0:
            return depth
        return span * need_head / (need_head + need_tail)
    return min(max(depth, need_head), span - need_tail)


def _balanced_prefix(items: list[_Item], total: float) -> int:
    """Index splitting ``items`` into two runs of the most equal area.

    Attached rooms are never separated from what they serve, so cuts are only
    considered at indices that do not land inside such a pair.
    """
    allowed = [i for i in range(1, len(items)) if not items[i].attach]
    if not allowed:
        allowed = list(range(1, len(items)))
    prefix, running = [], 0.0
    for item in items[:-1]:
        running += item.area
        prefix.append(running)
    return min(allowed, key=lambda i: abs(prefix[i - 1] - total / 2.0))


# --------------------------------------------------------------------------
# packing rooms into the footprint
# --------------------------------------------------------------------------

def _order_rooms(spec: PlanSpec, areas: list[float], rng: random.Random) -> list[int]:
    """Room indices in placement order: zone-major, then the designed sequence."""
    cycle = ZONE_CYCLES[rng.randrange(len(ZONE_CYCLES))]
    zone_rank = {z: i for i, z in enumerate(cycle)}
    flip = rng.random() < 0.4

    def key(i: int) -> tuple[float, float, float]:
        room = spec.rooms[i]
        rank = SEQUENCE_RANK.get(room.type_key, len(SEQUENCE))
        return (zone_rank[room.room_type.zone], -rank if flip else rank, -areas[i])

    return sorted(range(len(spec.rooms)), key=key)


def _pack_into_rects(order: list[int], areas: list[float], rects: list[Rect]) -> list[list[int]]:
    """Fill each footprint rectangle in turn, following room order."""
    buckets: list[list[int]] = [[] for _ in rects]
    if len(rects) == 1:
        buckets[0] = list(order)
        return buckets

    capacity = [r.area for r in rects]
    slot = 0
    for idx in order:
        while slot < len(rects) - 1 and capacity[slot] < areas[idx] * 0.5:
            slot += 1
        buckets[slot].append(idx)
        capacity[slot] -= areas[idx]
    for i, bucket in enumerate(buckets):  # no rectangle may be left empty
        if bucket:
            continue
        donor = max(range(len(buckets)), key=lambda j: len(buckets[j]))
        if len(buckets[donor]) > 1:
            bucket.append(buckets[donor].pop())
    return buckets


def _zone_blocks(
    spec: PlanSpec, areas: list[float], bucket: list[int], rect: Rect, rng: random.Random
) -> list[tuple[str, Rect, list[int]]]:
    """Split one footprint rectangle into per-zone blocks, preserving order."""
    groups: dict[str, list[int]] = {}
    for idx in bucket:
        groups.setdefault(spec.rooms[idx].room_type.zone, []).append(idx)
    groups = _merge_small_zones(groups, areas, rect.area)
    if len(groups) == 1:
        zone = next(iter(groups))
        return [(zone, rect, groups[zone])]

    items = [
        _Item(
            zone,
            sum(areas[i] for i in members),
            max(spec.rooms[i].room_type.min_dim for i in members),
        )
        for zone, members in groups.items()
    ]
    placed = slice_layout(items, rect, rng)
    return [
        (str(zone), placed[zone], groups[str(zone)])
        for zone in placed
        if placed[zone].area > EPS
    ]


# --------------------------------------------------------------------------
# corridors
# --------------------------------------------------------------------------

def _merge_small_zones(
    groups: dict[str, list[int]], areas: list[float], total: float
) -> dict[str, list[int]]:
    """Fold a zone too small to deserve its own block into its neighbour."""
    if len(groups) < 2:
        return groups
    order = list(groups)

    def share(zone: str) -> float:
        return sum(areas[i] for i in groups[zone]) / total if total > 0 else 0.0

    keep = [z for z in order if share(z) >= MIN_ZONE_SHARE]
    if not keep:  # every zone is small, so the largest one hosts the rest
        keep = [max(order, key=share)]

    merged = {zone: list(groups[zone]) for zone in order if zone in keep}
    for position, zone in enumerate(order):
        if zone in keep:
            continue
        before = [z for z in order[:position] if z in keep]
        after = [z for z in order[position + 1:] if z in keep]
        host = before[-1] if before else after[0]
        merged[host].extend(groups[zone])
    return merged


def _room_item(spec: PlanSpec, areas: list[float], index: int) -> _Item:
    room = spec.rooms[index]
    return _Item(index, areas[index], room.room_type.min_dim, room.type_key in ATTACHED)


def _entry_side(block: Rect, others: list[Rect], footprint: Polygon) -> str:
    """Which side of ``block`` faces the rest of the house."""
    best, best_len = None, 0.0
    for other in others:
        for name, edge in block.edges().items():
            if edge.vertical and abs(edge.x1 - (other.x2 if name == "west" else other.x)) < 1e-4:
                overlap = min(block.y2, other.y2) - max(block.y, other.y)
            elif edge.horizontal and abs(
                edge.y1 - (other.y2 if name == "south" else other.y)
            ) < 1e-4:
                overlap = min(block.x2, other.x2) - max(block.x, other.x)
            else:
                continue
            if overlap > best_len:
                best, best_len = name, overlap
    if best:
        return best
    cx, cy = footprint.bounds.center
    bx, by = block.center
    if abs(cx - bx) >= abs(cy - by):
        return "east" if cx > bx else "west"
    return "north" if cy > by else "south"


def _layout_zone(
    spec: PlanSpec,
    areas: list[float],
    block: Rect,
    members: list[int],
    entry: str,
    rng: random.Random,
) -> dict[int, Rect]:
    """Place one zone's rooms, carving a corridor first when it earns one."""
    def items(indices: list[int]) -> list[_Item]:
        return [_room_item(spec, areas, i) for i in indices]

    hall = next((i for i in members if spec.rooms[i].type_key == "hall"), None)
    others = [i for i in members if i != hall]

    # The corridor runs across the block so that it reaches the entry side.
    horizontal = entry in ("west", "east")
    span = block.w if horizontal else block.h
    across = block.h if horizontal else block.w
    room_min = min((spec.rooms[i].room_type.min_dim for i in others), default=6.0)
    if (
        hall is None
        or len(others) < MIN_CORRIDOR_ROOMS
        or across < spec.hall_width + 2 * room_min
        or span < spec.hall_width * 2
    ):
        return {int(k): v for k, v in slice_layout(items(members), block, rng).items()}

    corridor_area = spec.hall_width * span
    budget = max(block.area - corridor_area, EPS)
    total = sum(areas[i] for i in others) or 1.0
    cut = _balanced_prefix(items(others), total)
    side_a, side_b = others[:cut], others[cut:]
    if rng.random() < 0.5:
        side_a, side_b = side_b, side_a
    depth_a = sum(areas[i] for i in side_a) / total * budget / span
    depth_a = min(max(depth_a, room_min), across - spec.hall_width - room_min)

    if horizontal:
        rect_a = Rect(block.x, block.y, block.w, depth_a)
        corridor = Rect(block.x, rect_a.y2, block.w, spec.hall_width)
        rect_b = Rect(block.x, corridor.y2, block.w, block.y2 - corridor.y2)
    else:
        rect_a = Rect(block.x, block.y, depth_a, block.h)
        corridor = Rect(rect_a.x2, block.y, spec.hall_width, block.h)
        rect_b = Rect(corridor.x2, block.y, block.x2 - corridor.x2, block.h)

    out: dict[int, Rect] = {hall: corridor}
    for group, target in ((side_a, rect_a), (side_b, rect_b)):
        if group and target.area > EPS:
            out.update({int(k): v for k, v in slice_layout(items(group), target, rng).items()})
    return out


# --------------------------------------------------------------------------
# top level
# --------------------------------------------------------------------------

def layout_once(spec: PlanSpec, seed: int) -> Plan:
    """Produce a single plan for one seed."""
    rng = random.Random(seed)
    areas = spec.scaled_areas()
    rects = spec.footprint.decompose()
    order = _order_rooms(spec, areas, rng)
    buckets = _pack_into_rects(order, areas, rects)

    blocks: list[tuple[str, Rect, list[int]]] = []
    for rect, bucket in zip(rects, buckets):
        if bucket:
            blocks.extend(_zone_blocks(spec, areas, bucket, rect, rng))

    placements: dict[int, Rect] = {}
    for zone, block, members in blocks:
        others = [b for _, b, _ in blocks if b is not block]
        public = [b for z, b, _ in blocks if z == PUBLIC and b is not block]
        entry = _entry_side(block, public or others, spec.footprint)
        placements.update(_layout_zone(spec, areas, block, members, entry, rng))

    rooms = [
        PlacedRoom(index=i, spec=room, rect=placements.get(i, Rect(0, 0, 0, 0)))
        for i, room in enumerate(spec.rooms)
    ]
    plan = Plan(spec=spec, rooms=rooms, seed=seed)
    plan.openings = build_openings(plan)
    plan.score, plan.penalties = score_plan(plan)
    return plan


def generate(spec: PlanSpec, variants: int = 3, attempts: int | None = None) -> list[Plan]:
    """Generate ``variants`` distinct plans, best first.

    ``attempts`` seeds are tried (ten per requested variant by default) and the
    best-scoring plans that are not near-duplicates of one another are kept.
    """
    if variants < 1:
        raise ValueError("variants must be at least 1")
    attempts = attempts if attempts is not None else max(variants * 10, 24)
    plans = [layout_once(spec, spec.seed + n) for n in range(attempts)]
    plans.sort(key=lambda p: -p.score)

    chosen: list[Plan] = []
    for plan in plans:
        if all(not _too_similar(plan, other) for other in chosen):
            chosen.append(plan)
        if len(chosen) == variants:
            break
    for plan in plans:  # top up when the program admits little variety
        if len(chosen) >= variants:
            break
        if plan not in chosen:
            chosen.append(plan)
    return chosen


def _too_similar(a: Plan, b: Plan, tol: float = 0.9) -> bool:
    """Two plans match when most of their rooms land in the same place."""
    if len(a.rooms) != len(b.rooms):
        return False
    total = sum(r.area for r in a.rooms) or 1.0
    shared = sum(ra.rect.overlap_area(rb.rect) for ra, rb in zip(a.rooms, b.rooms))
    return shared / total >= tol
