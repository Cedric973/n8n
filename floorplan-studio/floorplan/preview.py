"""A terminal preview of a plan.

Rough by nature — one character per grid cell — but enough to see at a glance
whether rooms, corridors and doors landed where they should.
"""

from __future__ import annotations

from .plan import Plan

DOOR_MARKS = {"door": "+", "opening": ":", "entry": "@", "garage": "=", "window": "-"}


def ascii_plan(plan: Plan, width: int = 96) -> str:
    bounds = plan.footprint.bounds
    scale = width / bounds.w
    height = max(int(round(bounds.h * scale * 0.5)), 4)  # characters are ~2:1

    def cell(x: float, y: float) -> tuple[int, int]:
        return (
            min(int((x - bounds.x) * scale), width - 1),
            min(int((bounds.y2 - y) / bounds.h * height), height - 1),
        )

    grid = [[" "] * width for _ in range(height)]
    letters = {}
    for room in sorted(plan.rooms, key=lambda r: -r.area):
        if room.rect.area <= 0:
            continue
        mark = _mark(room.label, letters)
        x0, y1 = cell(room.rect.x, room.rect.y2)
        x1, y0 = cell(room.rect.x2, room.rect.y)
        for row in range(y1, y0 + 1):
            for col in range(x0, x1 + 1):
                edge = row in (y1, y0) or col in (x0, x1)
                grid[row][col] = "." if edge else mark
    for opening in plan.openings:
        col, row = cell(*opening.segment.midpoint)
        grid[row][col] = DOOR_MARKS.get(opening.kind, "?")

    legend = "  ".join(f"{m} {name}" for name, m in sorted(letters.items(), key=lambda kv: kv[1]))
    body = "\n".join("".join(row) for row in grid)
    marks = "  ".join(f"{v} {k}" for k, v in DOOR_MARKS.items())
    return f"{body}\n\nrooms:  {legend}\nkeys:   {marks}"


def _mark(label: str, letters: dict[str, str]) -> str:
    if label in letters:
        return letters[label]
    taken = set(letters.values())
    for char in label.upper() + "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if char.isalpha() and char not in taken:
            letters[label] = char
            return char
    letters[label] = "*"
    return "*"
