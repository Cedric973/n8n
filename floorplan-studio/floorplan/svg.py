"""Serialise a :class:`~floorplan.drawing.Scene` to SVG."""

from __future__ import annotations

from xml.sax.saxutils import escape

from .drawing import Path, Scene, Text, fit_scale

MIN_STROKE_PX = 0.6


def render_svg(scene: Scene, width: float = 1180.0, margin: float = 16.0) -> str:
    scale = fit_scale(scene.bounds, width, width * 2, margin)
    height = scene.bounds.h * scale + 2 * margin

    def px(x: float, y: float) -> tuple[float, float]:
        return (
            (x - scene.bounds.x) * scale + margin,
            (scene.bounds.y2 - y) * scale + margin,
        )

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" '
        f'height="{height:.0f}" viewBox="0 0 {width:.2f} {height:.2f}" '
        f'font-family="Helvetica, Arial, sans-serif">',
        f'<title>{escape(scene.title)}</title>',
        f'<rect width="100%" height="100%" fill="{scene.background}"/>',
    ]
    for item in scene.items:
        if isinstance(item, Path):
            out.append(_path(item, px, scale))
        elif isinstance(item, Text):
            out.append(_text(item, px, scale))
    out.append("</svg>")
    return "\n".join(out)


def _path(path: Path, px, scale: float) -> str:
    points = " ".join(f"{x:.2f},{y:.2f}" for x, y in (px(*p) for p in path.points))
    tag = "polygon" if path.closed else "polyline"
    attrs = [f'points="{points}"', f'fill="{path.fill or "none"}"']
    if path.stroke:
        attrs.append(f'stroke="{path.stroke}"')
        attrs.append(f'stroke-width="{max(path.width * scale, MIN_STROKE_PX):.2f}"')
        attrs.append('stroke-linejoin="round"')
        attrs.append('stroke-linecap="round"')
        if path.dash:
            dash = " ".join(f"{d * scale:.2f}" for d in path.dash)
            attrs.append(f'stroke-dasharray="{dash}"')
    else:
        attrs.append('stroke="none"')
    return f"<{tag} {' '.join(attrs)}/>"


_ANCHOR = {"start": "start", "middle": "middle", "end": "end"}


def _text(text: Text, px, scale: float) -> str:
    x, y = px(text.x, text.y)
    attrs = [
        f'x="{x:.2f}"', f'y="{y:.2f}"',
        f'font-size="{max(text.size * scale, 4.0):.2f}"',
        f'fill="{text.color}"',
        f'text-anchor="{_ANCHOR.get(text.anchor, "middle")}"',
        'dominant-baseline="middle"',
    ]
    if text.bold:
        attrs.append('font-weight="600"')
    if text.rotate:
        attrs.append(f'transform="rotate({-text.rotate:.1f} {x:.2f} {y:.2f})"')
    return f"<text {' '.join(attrs)}>{escape(text.value)}</text>"
