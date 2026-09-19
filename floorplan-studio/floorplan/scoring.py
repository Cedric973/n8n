"""How good is a plan? Lower penalties, higher score."""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

from .plan import exterior_segments
from .spec import AVOIDED_ADJACENCY, PREFERRED_ADJACENCY, adjacency_weight

if TYPE_CHECKING:  # pragma: no cover
    from .plan import Plan

WEIGHTS = {
    "area": 22.0,
    "aspect": 3.0,
    "min_dim": 9.0,
    "exterior": 7.0,
    "unreachable": 22.0,
    "adjacency": 2.4,
    "plumbing": 1.6,
}


def score_plan(plan: "Plan") -> tuple[float, dict[str, float]]:
    spec = plan.spec
    targets = spec.scaled_areas()
    penalties: dict[str, float] = {}

    area_err = 0.0
    aspect_pen = 0.0
    dim_pen = 0.0
    ext_pen = 0.0
    for room, target in zip(plan.rooms, targets):
        rect = room.rect
        if rect.area <= 0:
            area_err += 1.0
            dim_pen += 1.0
            continue
        area_err += abs(rect.area - target) / max(target, 1.0)
        aspect_pen += max(0.0, rect.aspect - room.room_type.max_aspect)
        dim_pen += max(0.0, room.room_type.min_dim - rect.min_dim)
        if room.room_type.needs_exterior and not exterior_segments(rect, plan.footprint):
            ext_pen += 1.0

    n = max(len(plan.rooms), 1)
    # Area error is averaged (every room drifts a little), but a starved or
    # misshapen room is a defect in its own right and is counted in full.
    penalties["area"] = WEIGHTS["area"] * area_err / n
    penalties["aspect"] = WEIGHTS["aspect"] * aspect_pen
    penalties["min_dim"] = WEIGHTS["min_dim"] * dim_pen
    penalties["exterior"] = WEIGHTS["exterior"] * ext_pen

    unreachable = len(plan.rooms) - len(_reachable(plan))
    penalties["unreachable"] = WEIGHTS["unreachable"] * unreachable

    adj_score, wet_score = _relationship_scores(plan)
    penalties["adjacency"] = -WEIGHTS["adjacency"] * adj_score
    penalties["plumbing"] = -WEIGHTS["plumbing"] * wet_score

    return 100.0 - sum(penalties.values()), penalties


def _reachable(plan: "Plan") -> set[int]:
    """Rooms you can walk to from the front door."""
    graph: dict[int, set[int]] = {r.index: set() for r in plan.rooms}
    entry: set[int] = set()
    for op in plan.openings:
        if op.kind in ("door", "opening") and len(op.rooms) == 2:
            a, b = op.rooms
            graph[a].add(b)
            graph[b].add(a)
        elif op.kind == "entry" and op.rooms:
            entry.add(op.rooms[0])
    if not entry:
        return set()
    seen = set(entry)
    queue = deque(entry)
    while queue:
        node = queue.popleft()
        for nxt in graph[node]:
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def _relationship_scores(plan: "Plan") -> tuple[float, float]:
    from .geometry import shared_wall

    adj = 0.0
    wet = 0.0
    rooms = plan.rooms
    for i in range(len(rooms)):
        for j in range(i + 1, len(rooms)):
            a, b = rooms[i], rooms[j]
            if a.rect.area <= 0 or b.rect.area <= 0:
                continue
            seg = shared_wall(a.rect, b.rect)
            if seg is None or seg.length < 2.0:
                continue
            adj += adjacency_weight(a.type_key, b.type_key, PREFERRED_ADJACENCY)
            adj -= adjacency_weight(a.type_key, b.type_key, AVOIDED_ADJACENCY)
            if a.room_type.wet and b.room_type.wet:
                wet += 1.0
    return adj, wet
