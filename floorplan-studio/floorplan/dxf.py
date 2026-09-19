"""Serialise a :class:`~floorplan.drawing.Scene` to DXF (AutoCAD R12 ASCII).

Written at 1:1 into model space in feet, on named layers, so the plan can be
opened in CAD and dimensioned or detailed further. R12 is deliberate: it is the
most widely readable DXF revision and needs no handles or object dictionary.

Paths become LINE entities and text becomes TEXT. Fills are not exported —
a CAD user wants linework, and hatch patterns would only be in the way.
"""

from __future__ import annotations

from .drawing import Path, Scene, Text

#: Layer name -> AutoCAD colour index.
LAYER_COLORS = {
    "FLOOR": 8, "WALLS": 7, "OPENINGS": 8, "DOORS": 3,
    "WINDOWS": 4, "TEXT": 2, "DIMS": 1, "SHEET": 8, "PLAN": 7,
}
DEFAULT_COLOR = 7

#: Layers that carry only fills and would be noise as outlines in CAD.
SKIP_LAYERS = {"FLOOR", "OPENINGS"}


def render_dxf(scene: Scene) -> str:
    layers = [l for l in scene.layers() if l not in SKIP_LAYERS] or ["PLAN"]
    out: list[str] = []
    _section(out, "HEADER", _header())
    _section(out, "TABLES", _layer_table(layers))
    _section(out, "ENTITIES", _entities(scene))
    out += ["0", "EOF"]
    return "\n".join(out) + "\n"


def _pair(out: list[str], code: int, value) -> None:
    out.append(str(code))
    out.append(f"{value:.6f}" if isinstance(value, float) else str(value))


def _section(out: list[str], name: str, body: list[str]) -> None:
    out += ["0", "SECTION", "2", name]
    out += body
    out += ["0", "ENDSEC"]


def _header() -> list[str]:
    out: list[str] = []
    _pair(out, 9, "$ACADVER")
    _pair(out, 1, "AC1009")
    _pair(out, 9, "$INSUNITS")
    _pair(out, 70, 2)  # feet
    return out


def _layer_table(layers: list[str]) -> list[str]:
    out = ["0", "TABLE", "2", "LAYER"]
    _pair(out, 70, len(layers))
    for name in layers:
        out += ["0", "LAYER"]
        _pair(out, 2, name)
        _pair(out, 70, 0)
        _pair(out, 62, LAYER_COLORS.get(name, DEFAULT_COLOR))
        _pair(out, 6, "CONTINUOUS")
    out += ["0", "ENDTAB"]
    return out


def _entities(scene: Scene) -> list[str]:
    out: list[str] = []
    for item in scene.items:
        if item.layer in SKIP_LAYERS:
            continue
        if isinstance(item, Path):
            _path(out, item)
        elif isinstance(item, Text):
            _text(out, item)
    return out


def _path(out: list[str], path: Path) -> None:
    if path.stroke is None and path.fill is not None:
        return  # a pure fill has no linework to export
    points = list(path.points)
    if path.closed and len(points) > 2:
        points.append(points[0])
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        out += ["0", "LINE"]
        _pair(out, 8, path.layer)
        _pair(out, 10, float(x1))
        _pair(out, 20, float(y1))
        _pair(out, 30, 0.0)
        _pair(out, 11, float(x2))
        _pair(out, 21, float(y2))
        _pair(out, 31, 0.0)


_JUSTIFY = {"start": 0, "middle": 1, "end": 2}


def _text(out: list[str], text: Text) -> None:
    out += ["0", "TEXT"]
    _pair(out, 8, text.layer)
    _pair(out, 10, float(text.x))
    _pair(out, 20, float(text.y))
    _pair(out, 30, 0.0)
    _pair(out, 40, float(text.size))
    _pair(out, 1, text.value)
    _pair(out, 50, float(text.rotate))
    _pair(out, 72, _JUSTIFY.get(text.anchor, 1))
    _pair(out, 73, 2)  # vertically centred
    _pair(out, 11, float(text.x))  # alignment point, required when 72/73 are set
    _pair(out, 21, float(text.y))
    _pair(out, 31, 0.0)
