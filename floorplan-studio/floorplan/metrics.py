"""Helvetica character metrics.

Shared by the PDF backend, which needs them to place text, and by the
renderer, which needs them to know whether a label fits in its room before
drawing it. Values are from the Adobe Helvetica metrics, in 1/1000 em.
"""

from __future__ import annotations

# Character widths in 1/1000 em, from the Adobe Helvetica metrics. Enough of
# the set to place the text this package actually emits.
_BASE = {
    " ": 278, "!": 278, '"': 355, "'": 191, "(": 333, ")": 333, "*": 389, "+": 584,
    ",": 278, "-": 333, ".": 278, "/": 278, ":": 278, ";": 278, "=": 584, "?": 556,
    "·": 333, "×": 584, "_": 556, "\u00b2": 365, "[": 278, "]": 278, "<": 584, ">": 584,
}
_BASE.update({str(d): 556 for d in range(10)})
HELVETICA = dict(_BASE)
HELVETICA.update(dict(zip(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    [667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833,
     722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611],
)))
HELVETICA.update(dict(zip(
    "abcdefghijklmnopqrstuvwxyz",
    [556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833,
     556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500],
)))
HELVETICA_BOLD = dict(_BASE)
HELVETICA_BOLD.update({"'": 238, '"': 474})
HELVETICA_BOLD.update(dict(zip(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    [722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833,
     722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611],
)))
HELVETICA_BOLD.update(dict(zip(
    "abcdefghijklmnopqrstuvwxyz",
    [556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889,
     611, 611, 611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500],
)))


def text_width(value: str, size: float, bold: bool = False) -> float:
    """Rendered width of ``value`` at ``size``, in the same units as ``size``."""
    table = HELVETICA_BOLD if bold else HELVETICA
    return sum(table.get(ch, 500) for ch in value) / 1000.0 * size
