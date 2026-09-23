"""Read an SVG file into a :class:`~floorplan.convert.model.Drawing`.

Standard library only. Handles the shape elements, paths with every command
in the SVG spec (curves are flattened, arcs converted from endpoint to centre
parameterisation), nested groups with ``translate``/``scale``/``rotate``/
``matrix`` transforms, and text. SVG is y-down; the drawing is y-up, so every
coordinate is flipped on the way out.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from ..model import Drawing, Entity, Provenance, Role

Matrix = tuple[float, float, float, float, float, float]  # a b c d e f
IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
CURVE_STEPS = 8
_NUM = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")
_UNIT = re.compile(r"^\s*([-+]?[\d.]+(?:e[-+]?\d+)?)\s*([a-z%]*)\s*$", re.I)
UNIT_PX = {"": 1.0, "px": 1.0, "pt": 96 / 72, "pc": 16.0, "mm": 96 / 25.4, "cm": 96 / 2.54, "in": 96.0}


def read_svg(path: str | Path) -> Drawing:
    root = ET.parse(str(path)).getroot()
    drawing = Drawing(source=str(path), format="svg")
    _units(root, drawing)
    _walk(root, IDENTITY, "0", drawing)
    # SVG is y-down. Flip so north is up like every other source.
    for e in drawing.entities:
        e.points = [(x, -y) for x, y in e.points]
        if e.center is not None:
            e.center = (e.center[0], -e.center[1])
        if e.kind == "arc" and e.start_angle is not None:
            e.start_angle, e.end_angle = -e.end_angle, -e.start_angle  # type: ignore[operator]
        e.rotation = -e.rotation
    return drawing


# -- units -------------------------------------------------------------------

def _units(root, drawing: Drawing) -> None:
    """Physical size from width/height and viewBox, when both are declared."""
    width, height = root.get("width"), root.get("height")
    viewbox = root.get("viewBox")
    if width and viewbox:
        m = _UNIT.match(width)
        parts = _NUM.findall(viewbox)
        if m and len(parts) == 4:
            value, unit = float(m.group(1)), m.group(2).lower()
            vb_w = float(parts[2])
            if unit in ("mm", "cm", "in", "pt") and vb_w > 0:
                per_user = {"mm": 0.001, "cm": 0.01, "in": 0.0254, "pt": 0.0254 / 72}[unit] * value / vb_w
                drawing.units = "svg"
                drawing.to_metres = per_user  # paper metres per user unit; real scale still unknown
                drawing.units_provenance = Provenance.VERIFIED
                drawing.metadata["paper_metres_per_user_unit"] = per_user
                drawing.note(f"page declared as {width} x {height}; user units map to paper size")
                return
    drawing.units = "px"
    drawing.units_provenance = Provenance.UNKNOWN
    drawing.note("no physical page size declared; coordinates are unitless pixels")


# -- traversal ---------------------------------------------------------------

def _tag(el) -> str:
    return el.tag.split("}", 1)[-1]


def _walk(el, ctm: Matrix, layer: str, drawing: Drawing) -> None:
    tag = _tag(el)
    if tag in ("defs", "metadata", "title", "desc", "style", "clipPath", "mask", "marker"):
        return
    ctm = _mul(ctm, _transform(el.get("transform")))
    if tag == "g":
        name = (el.get("{http://www.inkscape.org/namespaces/inkscape}label")
                or el.get("id") or el.get("class") or layer)
        for child in el:
            _walk(child, ctm, name, drawing)
        return
    if tag == "svg":
        for child in el:
            _walk(child, ctm, layer, drawing)
        return

    style = _style(el)
    base = dict(layer=layer, source_id=el.get("id", ""), lineweight=_weight(style, ctm),
                filled=_filled(style), color=_color(style))
    pts: list[tuple[float, float]] = []
    closed = False
    if tag == "line":
        pts = [_pt(ctm, _f(el, "x1"), _f(el, "y1")), _pt(ctm, _f(el, "x2"), _f(el, "y2"))]
    elif tag == "rect":
        x, y, w, h = _f(el, "x"), _f(el, "y"), _f(el, "width"), _f(el, "height")
        pts = [_pt(ctm, x, y), _pt(ctm, x + w, y), _pt(ctm, x + w, y + h), _pt(ctm, x, y + h)]
        closed = True
    elif tag in ("polyline", "polygon"):
        nums = [float(n) for n in _NUM.findall(el.get("points", ""))]
        pts = [_pt(ctm, nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]
        closed = tag == "polygon"
    elif tag in ("circle", "ellipse"):
        cx, cy = _f(el, "cx"), _f(el, "cy")
        rx = _f(el, "r") if tag == "circle" else _f(el, "rx")
        ry = rx if tag == "circle" else _f(el, "ry")
        if tag == "circle" and _uniform(ctm):
            drawing.entities.append(Entity("circle", center=_pt(ctm, cx, cy),
                                           radius=rx * math.hypot(ctm[0], ctm[1]), **base))
            return
        pts = [_pt(ctm, cx + rx * math.cos(t), cy + ry * math.sin(t))
               for t in (2 * math.pi * i / 32 for i in range(32))]
        closed = True
    elif tag == "path":
        for sub, sub_closed in _path(el.get("d", "")):
            drawing.entities.append(Entity("polyline", [_pt(ctm, *p) for p in sub],
                                           closed=sub_closed, **base))
        return
    elif tag == "text":
        _text(el, ctm, base, drawing)
        return
    else:
        return
    if len(pts) >= 2:
        drawing.entities.append(Entity("line" if len(pts) == 2 else "polyline", pts, closed=closed, **base))


def _text(el, ctm: Matrix, base: dict, drawing: Drawing) -> None:
    value = "".join(el.itertext()).strip()
    if not value:
        return
    x, y = _f(el, "x"), _f(el, "y")
    style = _style(el)
    size = _f(el, "font-size") or _len(style.get("font-size", "16"))
    angle = math.degrees(math.atan2(ctm[1], ctm[0]))
    anchor = el.get("text-anchor") or style.get("text-anchor", "start")
    base = dict(base, filled=False)
    drawing.entities.append(Entity("text", [_pt(ctm, x, y)], text=value,
                                   height=size * math.hypot(ctm[0], ctm[1]) * 0.72,
                                   rotation=angle, role=Role.TEXT, **base))
    drawing.entities[-1].meta["anchor"] = anchor


# -- attributes ----------------------------------------------------------------

def _f(el, name: str) -> float:
    value = el.get(name)
    return _len(value) if value else 0.0


def _len(value: str) -> float:
    m = _UNIT.match(value or "")
    if not m:
        return 0.0
    return float(m.group(1)) * UNIT_PX.get(m.group(2).lower(), 1.0)


def _style(el) -> dict[str, str]:
    out = {}
    for part in (el.get("style") or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip()] = v.strip()
    for key in ("fill", "stroke", "stroke-width", "font-size", "text-anchor"):
        if el.get(key) is not None:
            out.setdefault(key, el.get(key))
    return out


def _filled(style: dict) -> bool:
    fill = style.get("fill", "black").strip().lower()
    stroke = style.get("stroke", "none").strip().lower()
    return fill not in ("none", "transparent") and stroke in ("none", "")


def _color(style: dict) -> str | None:
    for key in ("stroke", "fill"):
        v = style.get(key, "").strip().lower()
        if v.startswith("#") and len(v) in (4, 7):
            return v
    return None


def _weight(style: dict, ctm: Matrix) -> float | None:
    if "stroke-width" not in style:
        return None
    return _len(style["stroke-width"]) * math.hypot(ctm[0], ctm[1]) * 25.4 / 96  # px -> mm


# -- transforms ---------------------------------------------------------------

def _mul(a: Matrix, b: Matrix) -> Matrix:
    return (a[0] * b[0] + a[2] * b[1], a[1] * b[0] + a[3] * b[1],
            a[0] * b[2] + a[2] * b[3], a[1] * b[2] + a[3] * b[3],
            a[0] * b[4] + a[2] * b[5] + a[4], a[1] * b[4] + a[3] * b[5] + a[5])


def _pt(m: Matrix, x: float, y: float) -> tuple[float, float]:
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


def _uniform(m: Matrix) -> bool:
    return abs(math.hypot(m[0], m[1]) - math.hypot(m[2], m[3])) < 1e-6 and abs(m[0] * m[2] + m[1] * m[3]) < 1e-6


def _transform(spec: str | None) -> Matrix:
    m = IDENTITY
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", spec or ""):
        v = [float(n) for n in _NUM.findall(args)]
        if name == "translate":
            t = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0.0)
        elif name == "scale":
            t = (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0)
        elif name == "rotate":
            a = math.radians(v[0]); c, s = math.cos(a), math.sin(a)
            t = (c, s, -s, c, 0, 0)
            if len(v) == 3:
                t = _mul(_mul((1, 0, 0, 1, v[1], v[2]), t), (1, 0, 0, 1, -v[1], -v[2]))
        elif name == "matrix" and len(v) == 6:
            t = tuple(v)  # type: ignore[assignment]
        elif name == "skewX":
            t = (1, 0, math.tan(math.radians(v[0])), 1, 0, 0)
        elif name == "skewY":
            t = (1, math.tan(math.radians(v[0])), 0, 1, 0, 0)
        else:
            continue
        m = _mul(m, t)
    return m


# -- path data ----------------------------------------------------------------

def _path(d: str) -> list[tuple[list[tuple[float, float]], bool]]:
    """Subpaths as point lists; curves flattened, arcs converted."""
    tokens = re.findall(r"[MmZzLlHhVvCcSsQqTtAa]|" + _NUM.pattern, d)
    subs: list[tuple[list, bool]] = []
    cur: list[tuple[float, float]] = []
    cmd = ""
    i = 0
    x = y = sx = sy = 0.0
    last_c = last_q = None

    def nums(n):
        nonlocal i
        vals = [float(t) for t in tokens[i:i + n]]
        i += n
        return vals

    while i < len(tokens):
        tok = tokens[i]
        if tok.isalpha():
            cmd = tok; i += 1
            if cmd in "Zz":
                if cur:
                    subs.append((cur, True)); cur = []
                x, y = sx, sy
                continue
        rel = cmd.islower()
        c = cmd.upper()
        if c == "M":
            px, py = nums(2)
            if rel: px += x; py += y
            if cur:
                subs.append((cur, False))
            cur = [(px, py)]; x, y = sx, sy = px, py
            cmd = "l" if rel else "L"
        elif c == "L":
            px, py = nums(2)
            if rel: px += x; py += y
            cur.append((px, py)); x, y = px, py
        elif c == "H":
            (px,) = nums(1); px = px + x if rel else px
            cur.append((px, y)); x = px
        elif c == "V":
            (py,) = nums(1); py = py + y if rel else py
            cur.append((x, py)); y = py
        elif c in ("C", "S"):
            if c == "C":
                x1, y1, x2, y2, px, py = nums(6)
            else:
                x2, y2, px, py = nums(4)
                x1, y1 = (2 * x - last_c[0], 2 * y - last_c[1]) if last_c else (x, y)
                if rel and last_c: x1, y1 = x1 - x, y1 - y
            if rel:
                x1 += x; y1 += y; x2 += x; y2 += y; px += x; py += y
            cur += _cubic((x, y), (x1, y1), (x2, y2), (px, py))
            last_c = (x2, y2); x, y = px, py
        elif c in ("Q", "T"):
            if c == "Q":
                x1, y1, px, py = nums(4)
            else:
                px, py = nums(2)
                x1, y1 = (2 * x - last_q[0], 2 * y - last_q[1]) if last_q else (x, y)
                if rel and last_q: x1, y1 = x1 - x, y1 - y
            if rel:
                x1 += x; y1 += y; px += x; py += y
            cur += _quad((x, y), (x1, y1), (px, py))
            last_q = (x1, y1); x, y = px, py
        elif c == "A":
            rx, ry, phi, large, sweep, px, py = nums(7)
            if rel: px += x; py += y
            cur += _arc((x, y), rx, ry, phi, bool(large), bool(sweep), (px, py))
            x, y = px, py
        else:
            i += 1
        if c not in ("C", "S"): last_c = None
        if c not in ("Q", "T"): last_q = None
    if cur:
        subs.append((cur, False))
    return subs


def _cubic(p0, p1, p2, p3):
    out = []
    for k in range(1, CURVE_STEPS + 1):
        t = k / CURVE_STEPS; u = 1 - t
        out.append((u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                    u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1]))
    return out


def _quad(p0, p1, p2):
    out = []
    for k in range(1, CURVE_STEPS + 1):
        t = k / CURVE_STEPS; u = 1 - t
        out.append((u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                    u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]))
    return out


def _arc(p0, rx, ry, phi_deg, large, sweep, p1):
    """SVG endpoint arc -> centre parameterisation -> points (W3C appendix B.2.4)."""
    if rx == 0 or ry == 0 or p0 == p1:
        return [p1]
    phi = math.radians(phi_deg); c, s = math.cos(phi), math.sin(phi)
    dx, dy = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    x1p, y1p = c * dx + s * dy, -s * dx + c * dy
    rx, ry = abs(rx), abs(ry)
    lam = (x1p / rx) ** 2 + (y1p / ry) ** 2
    if lam > 1:
        rx *= math.sqrt(lam); ry *= math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = math.sqrt(max(num / den, 0.0)) * (-1 if large == sweep else 1)
    cxp, cyp = coef * rx * y1p / ry, -coef * ry * x1p / rx
    cx = c * cxp - s * cyp + (p0[0] + p1[0]) / 2
    cy = s * cxp + c * cyp + (p0[1] + p1[1]) / 2

    def ang(ux, uy, vx, vy):
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a
    t1 = ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dt = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dt > 0: dt -= 2 * math.pi
    if sweep and dt < 0: dt += 2 * math.pi
    steps = max(4, int(abs(dt) / (math.pi / 2) * CURVE_STEPS))
    out = []
    for k in range(1, steps + 1):
        t = t1 + dt * k / steps
        ex, ey = rx * math.cos(t), ry * math.sin(t)
        out.append((c * ex - s * ey + cx, s * ex + c * ey + cy))
    return out
