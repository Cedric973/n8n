"""Sheet sizes and architectural scales.

A drawing scaled to fill its page is not a drawing you can measure. Two plans
come out at two different scales, so they cannot be compared side by side, and
a scale rule laid on the print reads nothing meaningful. Real drawing sets pick
a standard scale and a standard sheet, and let a small plan sit small on the
page — which is information, not wasted paper.

Scale is carried as points per foot, because the drawing is built in feet and
PDF measures in points. At 1/4" = 1'-0" a foot is a quarter inch, so 18 points;
at 1:100 a foot is 1/100 of a foot of paper, so 864/100 points. Both fall out of
``864 / ratio``, since a foot is 864 points at full size.
"""

from __future__ import annotations

from dataclasses import dataclass

POINTS_PER_INCH = 72.0
POINTS_PER_FOOT = 864.0
MARGIN = 36.0  # half an inch of clear border


@dataclass(frozen=True)
class Sheet:
    name: str
    width: float   # points, landscape
    height: float  # points

    @property
    def drawable(self) -> tuple[float, float]:
        return (self.width - 2 * MARGIN, self.height - 2 * MARGIN)

    def inches(self) -> tuple[float, float]:
        return (self.width / POINTS_PER_INCH, self.height / POINTS_PER_INCH)

    def millimetres(self) -> tuple[float, float]:
        return (self.width / POINTS_PER_INCH * 25.4, self.height / POINTS_PER_INCH * 25.4)


@dataclass(frozen=True)
class Scale:
    label: str
    ratio: float  # 1:ratio

    @property
    def points_per_foot(self) -> float:
        return POINTS_PER_FOOT / self.ratio


#: Largest (most detailed) first.
IMPERIAL_SCALES = [
    Scale("1/4\" = 1'-0\"", 48),
    Scale("3/16\" = 1'-0\"", 64),
    Scale("1/8\" = 1'-0\"", 96),
    Scale("3/32\" = 1'-0\"", 128),
    Scale("1/16\" = 1'-0\"", 192),
]
METRIC_SCALES = [Scale(f"1:{n}", n) for n in (50, 75, 100, 150, 200)]

#: Smallest first, all landscape.
IMPERIAL_SHEETS = [
    Sheet("ANSI A", 792, 612),
    Sheet("ANSI B", 1224, 792),
    Sheet("ANSI C", 1584, 1224),
    Sheet("ANSI D", 2448, 1584),
]
METRIC_SHEETS = [
    Sheet("A4", 842, 595),
    Sheet("A3", 1191, 842),
    Sheet("A2", 1684, 1191),
    Sheet("A1", 2384, 1684),
]


def scales_for(units: str) -> list[Scale]:
    return METRIC_SCALES if units == "metric" else IMPERIAL_SCALES


def sheets_for(units: str) -> list[Sheet]:
    return METRIC_SHEETS if units == "metric" else IMPERIAL_SHEETS


def fits(sheet: Sheet, scale: Scale, width_ft: float, height_ft: float) -> bool:
    usable_w, usable_h = sheet.drawable
    return (width_ft * scale.points_per_foot <= usable_w
            and height_ft * scale.points_per_foot <= usable_h)


def find_sheet(name: str, units: str) -> Sheet:
    for sheet in sheets_for(units):
        if sheet.name.lower() == str(name).strip().lower():
            return sheet
    known = ", ".join(s.name for s in sheets_for(units))
    raise ValueError(f"unknown sheet {name!r}; use one of {known}")


def find_scale(name: str, units: str) -> Scale:
    for scale in scales_for(units):
        if scale.label.lower() == str(name).strip().lower():
            return scale
    known = ", ".join(s.label for s in scales_for(units))
    raise ValueError(f"unknown scale {name!r}; use one of {known}")


def choose(width_ft: float, height_ft: float, units: str = "metric",
           sheet: str | Sheet | None = None,
           scale: str | Scale | None = None) -> tuple[Sheet, Scale]:
    """Pick the largest standard scale that fits, and the smallest sheet holding it.

    Working outward from the largest scale keeps as much detail as the paper
    allows; taking the smallest sheet at that scale avoids printing a bungalow
    on a D-size sheet. When nothing standard fits, the drawing is fitted to the
    largest sheet and reported as not to scale rather than silently mislabelled.
    """
    sheets = sheets_for(units)
    wanted_sheet = sheet if isinstance(sheet, Sheet) else (find_sheet(sheet, units) if sheet else None)
    wanted_scale = scale if isinstance(scale, Scale) else (find_scale(scale, units) if scale else None)

    if wanted_sheet and wanted_scale:
        return wanted_sheet, wanted_scale
    if wanted_scale:
        for candidate in sheets:
            if fits(candidate, wanted_scale, width_ft, height_ft):
                return candidate, wanted_scale
        # Honouring the request would run the drawing off the largest sheet.
        # Say so, and name the scale that would work, rather than clip it.
        workable = next(
            (c.label for c in scales_for(units) if fits(sheets[-1], c, width_ft, height_ft)),
            None,
        )
        hint = f"; {workable} fits on {sheets[-1].name}" if workable else ""
        raise ValueError(
            f"{wanted_scale.label} does not fit this plan on any sheet up to "
            f"{sheets[-1].name}{hint}"
        )
    if wanted_sheet:
        for candidate in scales_for(units):
            if fits(wanted_sheet, candidate, width_ft, height_ft):
                return wanted_sheet, candidate
        return wanted_sheet, _fitted(wanted_sheet, width_ft, height_ft)

    for candidate_scale in scales_for(units):
        for candidate_sheet in sheets:
            if fits(candidate_sheet, candidate_scale, width_ft, height_ft):
                return candidate_sheet, candidate_scale
    largest = sheets[-1]
    return largest, _fitted(largest, width_ft, height_ft)


def _fitted(sheet: Sheet, width_ft: float, height_ft: float) -> Scale:
    """A non-standard scale that fills the sheet, labelled honestly."""
    usable_w, usable_h = sheet.drawable
    ratio = max(width_ft * POINTS_PER_FOOT / max(usable_w, 1e-9),
                height_ft * POINTS_PER_FOOT / max(usable_h, 1e-9))
    return Scale("NOT TO SCALE", max(ratio, 1e-9))
