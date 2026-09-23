"""Read a DXF file into a :class:`~floorplan.convert.model.Drawing`.

Uses ``ezdxf``, which understands every DXF revision, block references with
their transforms, and the curve types (splines, ellipses, bulged polylines)
that a hand-rolled parser would get wrong. The module imports lazily so the
rest of the package stays free of the dependency.
"""

from __future__ import annotations

import math
from pathlib import Path

from ..model import Drawing, Entity, Provenance, Role

#: $INSUNITS codes that name a unit we can convert.
INSUNITS = {1: "in", 2: "ft", 4: "mm", 5: "cm", 6: "m", 8: "in", 9: "in", 10: "yd",
            13: "mm", 14: "dm", 15: "mm", 16: "mm", 17: "km", 18: "km"}


def _ezdxf():
    try:
        import ezdxf  # noqa: WPS433
        from ezdxf import path as ezpath
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ImportError(
            "reading DXF needs the optional dependency ezdxf: pip install ezdxf"
        ) from exc
    return ezdxf, ezpath


def read_dxf(path: str | Path) -> Drawing:
    ezdxf, ezpath = _ezdxf()
    doc = ezdxf.readfile(str(path))
    drawing = Drawing(source=str(path), format="dxf")
    drawing.metadata["dxf_version"] = doc.dxfversion

    code = int(doc.header.get("$INSUNITS", 0) or 0)
    if code in INSUNITS:
        drawing.units = INSUNITS[code]
        drawing.units_provenance = Provenance.VERIFIED
        drawing.note(f"units {drawing.units} declared by $INSUNITS")
    else:
        drawing.note("no usable $INSUNITS header; units must be inferred")

    layer_weights = {}
    for layer in doc.layers:
        lw = layer.dxf.get("lineweight", -3)
        layer_weights[layer.dxf.name] = lw / 100.0 if lw and lw > 0 else None

    skipped: dict[str, int] = {}
    for entity in doc.modelspace():
        _collect(entity, drawing, layer_weights, ezpath, skipped)
    for name, count in sorted(skipped.items()):
        drawing.note(f"skipped {count} {name} entities (not converted)")

    paper = [lay for lay in doc.layouts if not lay.is_modelspace and len(lay) > 0]
    drawing.sheets = 1 + len(paper)
    if paper:
        drawing.note(f"{len(paper)} paper-space layout(s) present; model space was read")
    return drawing


def _collect(entity, drawing: Drawing, layer_weights: dict, ezpath, skipped: dict) -> None:
    kind = entity.dxftype()
    layer = entity.dxf.get("layer", "0")
    base = dict(layer=layer, source_id=str(entity.dxf.handle),
                lineweight=_weight(entity, layer_weights))

    if kind == "INSERT":
        for child in entity.virtual_entities():
            _collect(child, drawing, layer_weights, ezpath, skipped)
        return
    if kind == "LINE":
        s, e = entity.dxf.start, entity.dxf.end
        drawing.entities.append(Entity("line", [(s.x, s.y), (e.x, e.y)], **base))
    elif kind in ("LWPOLYLINE", "POLYLINE"):
        closed = bool(entity.closed if kind == "LWPOLYLINE" else entity.is_closed)
        drawing.entities.append(Entity("polyline", _flatten(entity, ezpath), closed=closed, **base))
    elif kind in ("SPLINE", "ELLIPSE"):
        drawing.entities.append(Entity("polyline", _flatten(entity, ezpath), **base))
    elif kind == "ARC":
        c = entity.dxf.center
        drawing.entities.append(Entity(
            "arc", center=(c.x, c.y), radius=float(entity.dxf.radius),
            start_angle=float(entity.dxf.start_angle), end_angle=float(entity.dxf.end_angle), **base))
    elif kind == "CIRCLE":
        c = entity.dxf.center
        drawing.entities.append(Entity("circle", center=(c.x, c.y), radius=float(entity.dxf.radius), **base))
    elif kind in ("TEXT", "ATTRIB"):
        p = entity.dxf.insert
        drawing.entities.append(Entity(
            "text", [(p.x, p.y)], text=entity.dxf.text, height=float(entity.dxf.height),
            rotation=float(entity.dxf.get("rotation", 0.0)), role=Role.TEXT, **base))
    elif kind == "MTEXT":
        p = entity.dxf.insert
        drawing.entities.append(Entity(
            "text", [(p.x, p.y)], text=entity.plain_text(), height=float(entity.dxf.char_height),
            rotation=float(entity.dxf.get("rotation", 0.0)), role=Role.TEXT, **base))
    elif kind == "DIMENSION":
        _dimension(entity, drawing, base, layer_weights, ezpath, skipped)
    elif kind in ("SOLID", "TRACE", "3DFACE"):
        pts = [(v.x, v.y) for v in (entity.dxf.vtx0, entity.dxf.vtx1, entity.dxf.vtx3, entity.dxf.vtx2)]
        drawing.entities.append(Entity("polyline", pts, closed=True, filled=True, **base))
    elif kind == "POINT":
        pass
    else:
        skipped[kind] = skipped.get(kind, 0) + 1


def _dimension(entity, drawing, base, layer_weights, ezpath, skipped) -> None:
    text = entity.dxf.get("text", "") or ""
    measurement = None
    try:
        measurement = float(entity.get_measurement())
    except Exception:  # noqa: BLE001 - ezdxf raises assorted errors on odd dims
        pass
    if text in ("", "<>") and measurement is not None:
        text = f"{measurement:g}"
    p1 = entity.dxf.get("defpoint")
    p2 = entity.dxf.get("defpoint2") or entity.dxf.get("defpoint3")
    pts = [(p.x, p.y) for p in (p1, p2) if p is not None]
    drawing.entities.append(Entity(
        "dimension", pts, text=text or None, role=Role.DIMENSION,
        provenance=Provenance.VERIFIED if measurement is not None else Provenance.INFERRED,
        **base))
    drawing.entities[-1].meta["measurement"] = measurement
    try:
        for child in entity.virtual_entities():
            before = len(drawing.entities)
            _collect(child, drawing, layer_weights, ezpath, skipped)
            for e in drawing.entities[before:]:
                e.role = Role.DIMENSION
    except Exception:  # noqa: BLE001
        drawing.note("a dimension had no renderable geometry block")


def _flatten(entity, ezpath) -> list[tuple[float, float]]:
    if entity.dxftype() == "LWPOLYLINE" and not any(abs(b) > 1e-9 for b in (p[4] for p in entity.get_points())):
        return [(x, y) for x, y, *_ in entity.get_points()]
    path = ezpath.make_path(entity)
    box = ezpath.bbox([path]) if hasattr(ezpath, "bbox") else None
    extent = max(box.size.x, box.size.y) if box is not None and box.has_data else 1.0
    return [(v.x, v.y) for v in path.flattening(max(extent * 2e-3, 1e-6))]


def _weight(entity, layer_weights: dict) -> float | None:
    lw = entity.dxf.get("lineweight", -1)
    if lw is not None and lw > 0:
        return lw / 100.0
    return layer_weights.get(entity.dxf.get("layer", "0"))
