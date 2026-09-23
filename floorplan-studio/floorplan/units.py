"""Imperial and metric presentation.

The solver works in feet throughout — the room catalog, minimum dimensions and
wall thicknesses are all authored that way — so units are a boundary concern.
Input is converted to feet on the way in, and lengths and areas are formatted
back on the way out. Nothing in the geometry or the layout knows about this.

Metric output uses metres to two decimals rather than millimetres. Millimetres
are the ISO convention for construction drawings, but this is a schematic tool
and ``5.03 m`` reads better than ``5030`` for someone sizing a house.
"""

from __future__ import annotations

IMPERIAL = "imperial"
METRIC = "metric"
UNIT_SYSTEMS = (IMPERIAL, METRIC)

#: Metric is the default: most of the world builds in metres, and a drawing
#: dimensioned in feet and inches is unreadable to a reader who does not.
#: Imperial remains available everywhere it was, by asking for it.
DEFAULT_UNITS = METRIC

#: Sensible starting extents per system, so a default request is buildable.
DEFAULT_EXTENT = {METRIC: (15.0, 10.0), IMPERIAL: (48.0, 32.0)}

FEET_PER_METRE = 3.280839895013123
SQFT_PER_SQM = 10.763910416709722


def normalise(units: str | None) -> str:
    """Accept the usual spellings; anything unknown is an error, not a guess."""
    if units is None:
        return DEFAULT_UNITS
    value = str(units).strip().lower()
    aliases = {
        "imperial": IMPERIAL, "us": IMPERIAL, "ft": IMPERIAL, "feet": IMPERIAL,
        "metric": METRIC, "si": METRIC, "m": METRIC, "metre": METRIC,
        "meters": METRIC, "metres": METRIC, "meter": METRIC,
    }
    if value not in aliases:
        raise ValueError(f"unknown unit system {units!r}; use 'imperial' or 'metric'")
    return aliases[value]


# -- conversion ------------------------------------------------------------

def to_feet(value: float, units: str) -> float:
    return value * FEET_PER_METRE if units == METRIC else value


def from_feet(feet: float, units: str) -> float:
    return feet / FEET_PER_METRE if units == METRIC else feet


def to_sqft(value: float, units: str) -> float:
    return value * SQFT_PER_SQM if units == METRIC else value


def from_sqft(sqft: float, units: str) -> float:
    return sqft / SQFT_PER_SQM if units == METRIC else sqft


# -- formatting ------------------------------------------------------------

def format_feet(value: float) -> str:
    """12.5 -> ``12'-6"``, rounded to the nearest inch."""
    total_inches = round(value * 12.0)
    feet, inches = divmod(int(total_inches), 12)
    return f"{feet}'-{inches}\""


def format_length(feet: float, units: str = DEFAULT_UNITS) -> str:
    if units == METRIC:
        return f"{from_feet(feet, METRIC):.2f} m"
    return format_feet(feet)


def format_dimensions(width_ft: float, height_ft: float, units: str = DEFAULT_UNITS) -> str:
    """A room's two sides, with the unit named once in metric."""
    if units == METRIC:
        return (f"{from_feet(width_ft, METRIC):.2f} x "
                f"{from_feet(height_ft, METRIC):.2f} m")
    return f"{format_feet(width_ft)} x {format_feet(height_ft)}"


def format_area(sqft: float, units: str = DEFAULT_UNITS) -> str:
    if units == METRIC:
        return f"{from_sqft(sqft, METRIC):.1f} m²"
    return f"{round(sqft)} SF"


def scale_bar_options(units: str = DEFAULT_UNITS) -> list[tuple[float, str]]:
    """Candidate bar lengths, longest first, as (feet, label)."""
    if units == METRIC:
        return [(to_feet(n, METRIC), f"{n:g} m") for n in (3, 2, 1)]
    return [(float(n), f"{n:g} FT") for n in (10, 5, 2)]


def length_label(units: str = DEFAULT_UNITS) -> str:
    return "m" if units == METRIC else "ft"
