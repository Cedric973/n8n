"""Rasterise a :class:`~floorplan.drawing.Scene` to a PNG.

A small scanline renderer plus a PNG encoder, both standard library only, so a
plan can be turned into an image without a graphics stack installed. Polygons
are filled by even-odd scanline spans written with slice assignment, which
keeps the inner loop in C rather than in Python; strokes become quads; text is
drawn with the single-stroke font in :mod:`floorplan.font`.

Supersampling is off by default: the renderer draws at high resolution instead,
which is cheaper in pure Python and reads the same once the image is scaled to
fit a screen. Pass ``supersample=2`` for smoother edges at roughly four times
the cost.
"""

from __future__ import annotations

import math
import struct
import zlib

from .drawing import Path, Scene, Text, fit_scale, hex_to_rgb
from .font import CAP, GLYPH_WIDTH, glyph
from .metrics import HELVETICA, HELVETICA_BOLD, text_width

MIN_STROKE_PX = 1.0


class Canvas:
    """An RGB pixel buffer with scanline fill."""

    def __init__(self, width: int, height: int, background: str = "#ffffff"):
        self.width = int(width)
        self.height = int(height)
        self.stride = self.width * 3
        self.pixels = bytearray(bytes(hex_to_rgb_bytes(background)) * (self.width * self.height))

    # -- primitives -------------------------------------------------------

    def span(self, y: int, x0: float, x1: float, color: bytes) -> None:
        """Fill one horizontal run. The hot path, so it stays a slice write."""
        if y < 0 or y >= self.height:
            return
        start = max(int(math.floor(x0 + 0.5)), 0)
        end = min(int(math.floor(x1 + 0.5)), self.width)
        if end <= start:
            if 0 <= start < self.width and x1 > x0:
                end = start + 1  # never drop a sub-pixel sliver entirely
            else:
                return
        offset = y * self.stride
        self.pixels[offset + start * 3: offset + end * 3] = color * (end - start)

    def fill_polygon(self, points: list[tuple[float, float]], color: bytes) -> None:
        if len(points) < 3:
            return
        ys = [p[1] for p in points]
        top = max(int(math.floor(min(ys))), 0)
        bottom = min(int(math.ceil(max(ys))) + 1, self.height)
        edges = list(zip(points, points[1:] + points[:1]))
        for y in range(top, bottom):
            cy = y + 0.5
            crossings = []
            for (x1, y1), (x2, y2) in edges:
                if (y1 <= cy < y2) or (y2 <= cy < y1):
                    crossings.append(x1 + (cy - y1) / (y2 - y1) * (x2 - x1))
            if not crossings:
                continue
            crossings.sort()
            for a, b in zip(crossings[0::2], crossings[1::2]):
                self.span(y, a, b, color)

    def stroke(self, points: list[tuple[float, float]], width: float, color: bytes,
               closed: bool = False) -> None:
        half = max(width, MIN_STROKE_PX) / 2.0
        run = points + points[:1] if closed and len(points) > 2 else points
        for (x1, y1), (x2, y2) in zip(run, run[1:]):
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy)
            if length < 1e-9:
                continue
            nx, ny = -dy / length * half, dx / length * half
            self.fill_polygon(
                [(x1 + nx, y1 + ny), (x2 + nx, y2 + ny), (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)],
                color,
            )
        if half > 0.85:  # square off the joins so corners do not open up
            for x, y in run:
                self.fill_polygon(
                    [(x - half, y - half), (x + half, y - half),
                     (x + half, y + half), (x - half, y + half)], color)

    # -- output -----------------------------------------------------------

    def downsample(self, factor: int) -> "Canvas":
        if factor <= 1:
            return self
        out = Canvas(self.width // factor, self.height // factor)
        source, target = self.pixels, out.pixels
        area = factor * factor
        for y in range(out.height):
            rows = [(y * factor + dy) * self.stride for dy in range(factor)]
            base = y * out.stride
            for x in range(out.width):
                left = x * factor * 3
                r = g = b = 0
                for row in rows:
                    for dx in range(factor):
                        i = row + left + dx * 3
                        r += source[i]
                        g += source[i + 1]
                        b += source[i + 2]
                i = base + x * 3
                target[i] = r // area
                target[i + 1] = g // area
                target[i + 2] = b // area
        return out

    def to_png(self) -> bytes:
        raw = bytearray()
        for y in range(self.height):
            raw.append(0)  # filter type: none
            raw += self.pixels[y * self.stride:(y + 1) * self.stride]
        return _png(self.width, self.height, bytes(raw))


def hex_to_rgb_bytes(color: str) -> bytes:
    return bytes(int(round(c * 255)) for c in hex_to_rgb(color))


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))


def _png(width: int, height: int, raw: bytes) -> bytes:
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit truecolour
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", header)
            + _chunk(b"IDAT", zlib.compress(raw, 6))
            + _chunk(b"IEND", b""))


# --------------------------------------------------------------------------
# scene rendering
# --------------------------------------------------------------------------

def render_png(scene: Scene, width: int = 1800, margin: float = 24.0,
               supersample: int = 1) -> bytes:
    """Draw ``scene`` and return PNG bytes."""
    supersample = max(1, min(int(supersample), 4))
    scale = fit_scale(scene.bounds, width, width * 4, margin)
    height = int(round(scene.bounds.h * scale + 2 * margin))
    canvas = Canvas(int(width) * supersample, height * supersample, scene.background)
    s = scale * supersample
    m = margin * supersample

    def px(x: float, y: float) -> tuple[float, float]:
        return ((x - scene.bounds.x) * s + m, (scene.bounds.y2 - y) * s + m)

    for item in scene.items:
        if isinstance(item, Path):
            points = [px(*p) for p in item.points]
            if item.fill:
                canvas.fill_polygon(points, hex_to_rgb_bytes(item.fill))
            if item.stroke:
                canvas.stroke(points, item.width * s, hex_to_rgb_bytes(item.stroke), item.closed)
        elif isinstance(item, Text):
            _draw_text(canvas, item, px, s)

    return canvas.downsample(supersample).to_png()


def _draw_text(canvas: Canvas, text: Text, px, scale: float) -> None:
    if not text.value:
        return
    size = text.size * scale
    if size < 3.0:
        return  # unreadable at this scale; leave it out rather than smear it
    table = HELVETICA_BOLD if text.bold else HELVETICA
    y_unit = text.size / CAP
    shift = {"start": 0.0, "middle": -0.5, "end": -1.0}.get(text.anchor, -0.5)
    angle = math.radians(text.rotate)
    cos, sin = math.cos(angle), math.sin(angle)
    color = hex_to_rgb_bytes(text.color)
    weight = max(size * (0.115 if text.bold else 0.075), 1.0)

    # Each glyph is advanced by its real Helvetica width and squeezed to match,
    # so a preview string covers exactly the span the SVG and PDF will.
    pen = text_width(text.value, text.size, text.bold) * shift
    for char in text.value:
        step = table.get(char, 500) / 1000.0 * text.size
        x_unit = step * 0.84 / GLYPH_WIDTH
        for stroke in glyph(char):
            points = []
            for gx, gy in stroke:
                fx = pen + step * 0.08 + gx * x_unit
                fy = gy * y_unit - text.size * 0.5
                points.append(px(text.x + fx * cos - fy * sin, text.y + fx * sin + fy * cos))
            canvas.stroke(points, weight, color)
        pen += step
