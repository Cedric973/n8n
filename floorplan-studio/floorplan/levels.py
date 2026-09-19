"""The three levels a plan is issued at.

The same model is drawn three times, each for a different reader:

- **client** — the presentation plan. Walls, windows, doors, room names and
  areas, the overall dimensions, north and scale. Nothing else. A reader
  must tell a wall from a window from a door in under a second, at any zoom.
- **dimension** — every dimension chain on every face, and each room's
  width x depth under its name.
- **technical** — the record. Everything, including what the converter
  inferred rather than read, drawn dashed, with the provenance counts in the
  title block. This is where uncertainty lives; the client plan is not
  where to hide it, and not where to show it either.

Less on the main plan, a stronger hierarchy, and an immediate distinction
between wall, window and door.
"""

from __future__ import annotations

CLIENT = "client"
DIMENSION = "dimension"
TECHNICAL = "technical"
LEVELS = (CLIENT, DIMENSION, TECHNICAL)

#: File suffix and sheet caption per level.
LEVEL_INFO = {
    CLIENT: ("01-client", "FLOOR PLAN"),
    DIMENSION: ("02-dimension", "DIMENSION PLAN"),
    TECHNICAL: ("03-technical", "TECHNICAL PLAN"),
}


def parse_levels(value: str | None) -> list[str]:
    """'all' or a comma list; the default is every level."""
    if not value or value.strip().lower() == "all":
        return list(LEVELS)
    out = []
    for part in value.split(","):
        name = part.strip().lower()
        if name not in LEVELS:
            raise ValueError(f"unknown level {part!r}; use {', '.join(LEVELS)} or all")
        if name not in out:
            out.append(name)
    return out
