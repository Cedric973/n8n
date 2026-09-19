"""Serialise a :class:`~floorplan.drawing.Scene` to PDF.

A minimal PDF 1.4 writer: one page, Helvetica and Helvetica-Bold, and a single
content stream of filled and stroked paths plus text. Written by hand so the
package keeps its promise of needing nothing outside the standard library.

PDF user space has its origin at the bottom left with y pointing up, which is
the same convention the scene uses, so only a scale and an offset are needed.
"""

from __future__ import annotations

from .drawing import Path, Scene, Text, fit_scale, hex_to_rgb

# Character widths in 1/1000 em, from the Adobe Helvetica metrics. Enough of
# the set to place the text this package actually emits.
_BASE = {
    " ": 278, "!": 278, '"': 355, "'": 191, "(": 333, ")": 333, "*": 389, "+": 584,
    ",": 278, "-": 333, ".": 278, "/": 278, ":": 278, ";": 278, "=": 584, "?": 556,
    "·": 333, "×": 584, "_": 556,
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

LETTER_LANDSCAPE = (792.0, 612.0)
MARGIN = 20.0
MIN_STROKE_PT = 0.25


def text_width(value: str, size: float, bold: bool = False) -> float:
    table = HELVETICA_BOLD if bold else HELVETICA
    return sum(table.get(ch, 500) for ch in value) / 1000.0 * size


def render_pdf(scene: Scene, page: tuple[float, float] = LETTER_LANDSCAPE) -> bytes:
    width, height = page
    scale = fit_scale(scene.bounds, width, height, MARGIN)
    off_x = (width - scene.bounds.w * scale) / 2.0 - scene.bounds.x * scale
    off_y = (height - scene.bounds.h * scale) / 2.0 - scene.bounds.y * scale

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
