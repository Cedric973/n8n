"""Serialise a :class:`~floorplan.drawing.Scene` to PDF.

A minimal PDF 1.4 writer: one page, Helvetica and Helvetica-Bold, and a single
content stream of filled and stroked paths plus text. Written by hand so the
package keeps its promise of needing nothing outside the standard library.

PDF user space has its origin at the bottom left with y pointing up, which is
the same convention the scene uses, so only a scale and an offset are needed.
"""

from __future__ import annotations

from .drawing import Path, Scene, Text, hex_to_rgb
from .metrics import HELVETICA, HELVETICA_BOLD, text_width

MIN_STROKE_PT = 0.25


def render_pdf(scene: Scene) -> bytes:
    """Render onto the scene's sheet, at the scene's scale.

    A point is 1/72 inch, and the scale is carried as points per foot, so
    printing this file at 100% gives a drawing a scale rule can measure.
    """
    width, height = scene.sheet.width, scene.sheet.height
    scale, off_x, off_y = scene.placement()

    def pt(x: float, y: float) -> tuple[float, float]:
        return (x * scale + off_x, y * scale + off_y)

    ops: list[str] = ["q"]
    r, g, b = hex_to_rgb(scene.background)
    ops.append(f"{r:.3f} {g:.3f} {b:.3f} rg 0 0 {width:.2f} {height:.2f} re f")
    for item in scene.items:
        if isinstance(item, Path):
            ops.extend(_path_ops(item, pt, scale))
        elif isinstance(item, Text):
            ops.extend(_text_ops(item, pt, scale))
    ops.append("Q")
    return _document("\n".join(ops).encode("latin-1", "replace"), width, height, scene.title)


def _path_ops(path: Path, pt, scale: float) -> list[str]:
    if not path.points:
        return []
    ops = ["q"]
    if path.dash:
        pattern = " ".join(f"{d * scale:.2f}" for d in path.dash)
        ops.append(f"[{pattern}] 0 d")
    if path.fill:
        r, g, b = hex_to_rgb(path.fill)
        ops.append(f"{r:.3f} {g:.3f} {b:.3f} rg")
    if path.stroke:
        r, g, b = hex_to_rgb(path.stroke)
        ops.append(f"{r:.3f} {g:.3f} {b:.3f} RG")
        ops.append(f"{max(path.width * scale, MIN_STROKE_PT):.2f} w 1 j 1 J")
    x, y = pt(*path.points[0])
    ops.append(f"{x:.2f} {y:.2f} m")
    for point in path.points[1:]:
        x, y = pt(*point)
        ops.append(f"{x:.2f} {y:.2f} l")
    if path.closed:
        ops.append("h")
    if path.fill and path.stroke:
        ops.append("B")
    elif path.fill:
        ops.append("f")
    elif path.stroke:
        ops.append("S")
    else:
        ops.append("n")
    ops.append("Q")
    return ops


def _text_ops(text: Text, pt, scale: float) -> list[str]:
    import math

    size = text.size * scale
    if size < 1.0 or not text.value:
        return []
    shift = {"start": 0.0, "middle": -0.5, "end": -1.0}.get(text.anchor, -0.5)
    dx = text_width(text.value, size, text.bold) * shift
    dy = -size * 0.35  # baseline offset for vertical centring
    angle = math.radians(text.rotate)
    cos, sin = math.cos(angle), math.sin(angle)
    x, y = pt(text.x, text.y)
    r, g, b = hex_to_rgb(text.color)
    font = "/F2" if text.bold else "/F1"
    tx = x + dx * cos - dy * sin
    ty = y + dx * sin + dy * cos
    return [
        "BT", f"{r:.3f} {g:.3f} {b:.3f} rg", f"{font} {size:.2f} Tf",
        f"{cos:.5f} {sin:.5f} {-sin:.5f} {cos:.5f} {tx:.2f} {ty:.2f} Tm",
        f"({_escape(text.value)}) Tj", "ET",
    ]


def _escape(value: str) -> str:
    out = value.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    return "".join(ch if ord(ch) < 256 else "?" for ch in out)


def _document(content: bytes, width: float, height: float, title: str) -> bytes:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width:.2f} {height:.2f}] "
            f"/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> /Contents 4 0 R >>"
        ).encode("ascii"),
        b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        b"<< /Title (" + _escape(title).encode("latin-1", "replace") + b") /Producer (floorplan-studio) >>",
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info {len(objects)} 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode("ascii")
    return bytes(out)
