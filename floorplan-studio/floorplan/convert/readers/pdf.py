"""Read the vector content of a PDF page into a :class:`~floorplan.convert.model.Drawing`.

Uses ``pdfminer.six`` for its layout analysis: paths come back as line, rect
and curve objects in points, and characters are assembled into positioned
text lines. This is for PDFs that were *drawn* — exported from CAD, or from
this package. A scanned PDF holds an image and no paths, and is reported as
such rather than pretended into geometry.

PDF user space is y-up in points, which is already the drawing convention,
so no flip is needed.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..model import Drawing, Entity, Provenance, Role

_CID = re.compile(r"\(cid:\d+\)")
_SCALE_RATIO = re.compile(r"\b1\s*[:/]\s*(\d{2,4})\b")
_SCALE_IMPERIAL = re.compile(r"(\d+(?:/\d+)?)\s*(?:\"|″|in)\s*=\s*1\s*'?-?\s*0?\s*(?:\"|″|')?")


def _pdfminer():
    try:
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import (LAParams, LTChar, LTCurve, LTFigure, LTImage, LTLine,
                                     LTRect, LTTextContainer, LTTextLine)
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ImportError(
            "reading PDF needs the optional dependency pdfminer.six: pip install pdfminer.six"
        ) from exc
    return extract_pages, LAParams, LTChar, LTCurve, LTFigure, LTImage, LTLine, LTRect, LTTextContainer, LTTextLine


def read_pdf(path: str | Path, page: int = 1) -> Drawing:
    (extract_pages, LAParams, LTChar, LTCurve, LTFigure, LTImage,
     LTLine, LTRect, LTTextContainer, LTTextLine) = _pdfminer()
    drawing = Drawing(source=str(path), format="pdf", units="pt",
                      units_provenance=Provenance.VERIFIED)
    drawing.to_metres = 0.0254 / 72.0  # paper metres per point; real scale still unknown
    params = LAParams(detect_vertical=True, line_margin=0.2, char_margin=1.5)
    pages = list(extract_pages(str(path), laparams=params))
    drawing.sheets = len(pages)
    if not pages:
        drawing.note("PDF has no pages")
        return drawing
    if page < 1 or page > len(pages):
        raise ValueError(f"page {page} out of range 1..{len(pages)}")
    layout = pages[page - 1]
    drawing.metadata["page"] = page
    drawing.metadata["page_size_pt"] = (round(layout.width, 2), round(layout.height, 2))

    images = 0
    counter = [0]
    unreadable = [0]

    def sid() -> str:
        counter[0] += 1
        return f"p{page}-{counter[0]}"

    def walk(obj):
        nonlocal images
        if isinstance(obj, LTTextLine):
            text = obj.get_text().strip()
            if text:
                vertical = type(obj).__name__.endswith("Vertical")
                chars = [c for c in obj if isinstance(c, LTChar)]
                if vertical:
                    # pdfminer's char.size is the glyph *advance* once text is
                    # not upright, so a rotated "1" would come back a quarter
                    # of its height. The line's width is the font height.
                    size = obj.width
                    origin = (obj.x1, obj.y0)  # baseline start of text reading upward
                else:
                    size = chars[0].size if chars else obj.height
                    origin = (obj.x0, obj.y0)
                entity = Entity(
                    "text", [origin], text=text, height=size,
                    rotation=90.0 if vertical else 0.0, role=Role.TEXT, source_id=sid())
                if _CID.search(text):
                    # A font with no ToUnicode map: the glyphs exist on the page
                    # but their meaning cannot be recovered. Keep the position,
                    # mark it unknown, and never draw the placeholder string.
                    entity.text = _CID.sub("\ufffd", text).strip() or "\ufffd"
                    entity.provenance = Provenance.UNKNOWN
                    entity.meta["unreadable"] = True
                    unreadable[0] += 1
                drawing.entities.append(entity)
            return
        if isinstance(obj, LTTextContainer):
            for child in obj:
                walk(child)
            return
        if isinstance(obj, LTImage):
            images += 1
            return
        if isinstance(obj, LTRect):
            pts = [(obj.x0, obj.y0), (obj.x1, obj.y0), (obj.x1, obj.y1), (obj.x0, obj.y1)]
            drawing.entities.append(Entity(
                "polyline", pts, closed=True, filled=_is_filled(obj),
                lineweight=_weight(obj), color=_color(obj), source_id=sid()))
            return
        if isinstance(obj, LTLine):
            drawing.entities.append(Entity(
                "line", [(obj.pts[0][0], obj.pts[0][1]), (obj.pts[1][0], obj.pts[1][1])],
                lineweight=_weight(obj), color=_color(obj), source_id=sid()))
            return
        if isinstance(obj, LTCurve):
            pts = _flatten(obj)
            if len(pts) >= 2:
                closed = len(pts) > 2 and _close(pts[0], pts[-1])
                if closed:
                    pts = pts[:-1]
                drawing.entities.append(Entity(
                    "line" if len(pts) == 2 else "polyline", pts, closed=closed,
                    filled=_is_filled(obj), lineweight=_weight(obj), color=_color(obj),
                    source_id=sid()))
            return
        if isinstance(obj, LTFigure) or hasattr(obj, "__iter__"):
            for child in obj:
                walk(child)

    walk(layout)
    if images:
        drawing.note(f"{images} raster image(s) on the page were not vectorised")
    if unreadable[0]:
        total = sum(1 for e in drawing.entities if e.kind == "text")
        drawing.metadata["unreadable_text"] = unreadable[0]
        drawing.note(f"{unreadable[0]} of {total} text lines use a font with no Unicode mapping "
                     "and cannot be read; they are reported as UNKNOWN and not redrawn")
    paths = [e for e in drawing.entities if e.kind != "text"]
    if not paths:
        drawing.note("page contains no vector geometry" + (" — likely a scan" if images else ""))
        drawing.quality = "UNUSABLE"
    _find_scale_text(drawing)
    return drawing


def _find_scale_text(drawing: Drawing) -> None:
    """A printed scale in the sheet's own text is the best evidence there is."""
    for e in drawing.texts():
        t = e.text or ""
        m = _SCALE_RATIO.search(t)
        if m:
            drawing.scale_label = f"1:{m.group(1)}"
            drawing.metadata["scale_ratio"] = int(m.group(1))
            drawing.scale_provenance = Provenance.VERIFIED
            drawing.note(f"scale {drawing.scale_label} read from sheet text")
            return
        m = _SCALE_IMPERIAL.search(t)
        if m:
            frac = m.group(1)
            inches = float(frac.split("/")[0]) / float(frac.split("/")[1]) if "/" in frac else float(frac)
            if inches > 0:
                drawing.scale_label = f'{frac}" = 1\'-0"'
                drawing.metadata["scale_ratio"] = 12.0 / inches
                drawing.scale_provenance = Provenance.VERIFIED
                drawing.note(f"scale {drawing.scale_label} read from sheet text")
                return


def _flatten(curve) -> list[tuple[float, float]]:
    original = getattr(curve, "original_path", None)
    if not original:
        return [(x, y) for x, y in curve.pts]
    out: list[tuple[float, float]] = []
    cur = (0.0, 0.0)
    for op, *args in original:
        if op == "m":
            cur = tuple(args[0]); out.append(cur)
        elif op == "l":
            cur = tuple(args[0]); out.append(cur)
        elif op == "c":
            p1, p2, p3 = (tuple(a) for a in args)
            for k in range(1, 9):
                t = k / 8; u = 1 - t
                out.append((u**3 * cur[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                            u**3 * cur[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1]))
            cur = p3
        elif op == "h" and out:
            out.append(out[0])
    return out


def _close(a, b, tol: float = 1e-3) -> bool:
    return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol


def _is_filled(obj) -> bool:
    return bool(getattr(obj, "fill", False)) and not bool(getattr(obj, "stroke", False))


def _weight(obj) -> float | None:
    lw = getattr(obj, "linewidth", None)
    return lw * 25.4 / 72 if lw else None  # pt -> mm


def _color(obj) -> str | None:
    c = getattr(obj, "stroking_color", None) or getattr(obj, "non_stroking_color", None)
    if isinstance(c, (list, tuple)) and len(c) == 3:
        return "#%02x%02x%02x" % tuple(int(round(max(0, min(1, v)) * 255)) for v in c)
    if isinstance(c, (int, float)):
        g = int(round(max(0, min(1, c)) * 255))
        return "#%02x%02x%02x" % (g, g, g)
    return None
