"""Import existing drawings and re-issue them cleanly.

The generator half of this package makes plans from nothing. This half takes a
plan that already exists — as DXF, SVG or vector PDF — recognises what is in
it, cleans it, and re-issues it on a standard sheet in every format the
generator can write, with a report saying what was verified, what was
calculated, what was inferred and what remains unknown.
"""

from .model import Drawing, Entity, Provenance, Role

__all__ = ["Drawing", "Entity", "Provenance", "Role"]
