"""Turn a JSON request into a :class:`~floorplan.spec.PlanSpec` and back.

Shared by the CLI and the HTTP server so both accept exactly the same input.
"""

from __future__ import annotations

from typing import Any

from .geometry import Polygon
from .layout import generate, layout_once
from .plan import Plan
from .render import build_scene
from .spec import CATALOG, PlanSpec, RoomSpec
from .units import DEFAULT_EXTENT, normalise, to_feet, to_sqft

SHAPES = {
    "rectangle": lambda p: Polygon.rectangle(p["width"], p["depth"]),
    "l": lambda p: Polygon.l_shape(p["width"], p["depth"], p.get("notch_w", p["width"] / 3), p.get("notch_h", p["depth"] / 3)),
    "t": lambda p: Polygon.t_shape(p["width"], p["depth"], p.get("stem_w", p["width"] / 2.5), p.get("stem_h", p["depth"] / 3)),
    "u": lambda p: Polygon.u_shape(p["width"], p["depth"], p.get("notch_w", p["width"] / 3.5), p.get("notch_h", p["depth"] / 3)),
}

PROGRAM_KEYS = {
    "bedrooms": int, "bathrooms": int, "office": bool, "garage": bool,
    "formal_dining": bool, "laundry": bool, "mudroom": bool, "pantry": bool,
}

MAX_ROOMS = 40
MAX_VARIANTS = 6


class RequestError(ValueError):
    """The payload is not a usable plan request."""


def units_from(payload: dict[str, Any]) -> str:
    try:
        return normalise(payload.get("units"))
    except ValueError as exc:
        raise RequestError(str(exc)) from exc


def footprint_from(payload: dict[str, Any]) -> Polygon:
    """Build the footprint, converting the caller's units to feet."""
    units = units_from(payload)
    points = payload.get("footprint")
    if points:
        if len(points) < 4:
            raise RequestError("a footprint needs at least four corners")
        if len(points) > 64:
            raise RequestError("footprint has too many corners (limit 64)")
        try:
            return Polygon([(to_feet(float(x), units), to_feet(float(y), units))
                            for x, y in points])
        except (TypeError, ValueError) as exc:
            raise RequestError(f"invalid footprint: {exc}") from exc

    shape = str(payload.get("shape", "rectangle")).lower()
    if shape not in SHAPES:
        raise RequestError(f"unknown shape {shape!r}; use one of {sorted(SHAPES)}")
    default_w, default_d = DEFAULT_EXTENT[units]
    params = {
        "width": to_feet(float(payload.get("width") or default_w), units),
        "depth": to_feet(float(payload.get("depth") or default_d), units),
    }
    for key in ("notch_w", "notch_h", "stem_w", "stem_h"):
        if payload.get(key) is not None:
            params[key] = to_feet(float(payload[key]), units)
    if not (8 <= params["width"] <= 300 and 8 <= params["depth"] <= 300):
        raise RequestError(
            "width and depth must be between 8 and 300 feet (2.4 and 91 metres)")
    try:
        return SHAPES[shape](params)
    except ValueError as exc:
        raise RequestError(str(exc)) from exc


def spec_from(payload: dict[str, Any]) -> PlanSpec:
    """Build a spec from either an explicit room list or a room-count program."""
    footprint = footprint_from(payload)
    units = units_from(payload)
    title = str(payload.get("title") or "Untitled Plan")[:80]
    seed = int(payload.get("seed", 0))

    rooms = payload.get("rooms")
    if rooms:
        if len(rooms) > MAX_ROOMS:
            raise RequestError(f"too many rooms (limit {MAX_ROOMS})")
        specs = []
        for entry in rooms:
            key = entry.get("type") if isinstance(entry, dict) else entry
            if key not in CATALOG:
                raise RequestError(f"unknown room type {key!r}")
            name = entry.get("name") if isinstance(entry, dict) else None
            sqft = entry.get("sqft") if isinstance(entry, dict) else None
            specs.append(RoomSpec(key, name,
                                  to_sqft(float(sqft), units) if sqft else None))
        return PlanSpec(footprint=footprint, rooms=specs, title=title, seed=seed,
                        units=units)

    program = {}
    for key, cast in PROGRAM_KEYS.items():
        if payload.get(key) is not None:
            program[key] = cast(payload[key])
    if not 1 <= program.get("bedrooms", 3) <= 8:
        raise RequestError("bedrooms must be between 1 and 8")
    if not 1 <= program.get("bathrooms", 2) <= 8:
        raise RequestError("bathrooms must be between 1 and 8")
    try:
        return PlanSpec.from_program(footprint, title=title, seed=seed,
                                     units=units, **program)
    except ValueError as exc:
        raise RequestError(str(exc)) from exc


def sheet_options(payload: dict[str, Any]) -> dict[str, Any]:
    """Optional sheet and scale overrides, validated against the unit system."""
    options = {"sheet": payload.get("sheet") or None, "scale": payload.get("scale") or None}
    if payload.get("level"):
        options["level"] = str(payload["level"]).lower()
    return options


def scene_for(plan: Plan, payload: dict[str, Any]):
    """Build a scene, turning a bad sheet or scale into a request error."""
    from .render import build_scene

    try:
        return build_scene(plan, **sheet_options(payload))
    except ValueError as exc:
        raise RequestError(str(exc)) from exc


def generate_from(payload: dict[str, Any]) -> list[Plan]:
    spec = spec_from(payload)
    variants = max(1, min(int(payload.get("variants", 3)), MAX_VARIANTS))
    if spec.footprint.area / len(spec.rooms) < 25:
        raise RequestError(
            f"{len(spec.rooms)} rooms will not fit in {round(spec.footprint.area)} sq ft; "
            "enlarge the footprint or cut the program"
        )
    return generate(spec, variants=variants)


def replay(payload: dict[str, Any], seed: int) -> Plan:
    """Rebuild one plan exactly, for export after the browser picked a variant."""
    return layout_once(spec_from(payload), seed)


def catalog() -> list[dict[str, Any]]:
    return [
        {
            "key": rt.key, "label": rt.label, "zone": rt.zone,
            "target_sqft": rt.target_sqft, "min_dim": rt.min_dim,
        }
        for rt in CATALOG.values()
    ]
