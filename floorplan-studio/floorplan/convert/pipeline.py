"""ANALYZE → CLEAN → RECONSTRUCT → VALIDATE → EXPORT, as one call."""

from __future__ import annotations

from pathlib import Path

from ..dxf import DXF_ENCODING, render_dxf
from ..pdf import render_pdf
from ..raster import render_png
from ..svg import render_svg
from ..units import DEFAULT_UNITS
from .analyze import analyze
from .clean import clean
from .model import Drawing
from .render import build_drawing_scene
from .report import build_report, report_json, report_markdown

FORMATS = ("pdf", "dxf", "svg", "png")
READABLE = ("dxf", "svg", "pdf")


class UnsupportedSource(ValueError):
    """The file is a format this converter cannot read."""


def read(path: str | Path, page: int = 1) -> Drawing:
    suffix = Path(path).suffix.lower().lstrip(".")
    if suffix == "dxf":
        from .readers.dxf import read_dxf
        return read_dxf(path)
    if suffix == "svg":
        from .readers.svg import read_svg
        return read_svg(path)
    if suffix == "pdf":
        from .readers.pdf import read_pdf
        return read_pdf(path, page=page)
    if suffix in ("dwg", "dwf", "rvt", "ifc"):
        raise UnsupportedSource(
            f".{suffix} is a proprietary or BIM format this converter cannot read directly; "
            "export it to DXF (any CAD package, or the free ODA File Converter for DWG) and convert that")
    if suffix in ("png", "jpg", "jpeg", "tif", "tiff", "bmp"):
        raise UnsupportedSource(
            f".{suffix} is a raster image; this converter reads vector sources only "
            "(DXF, SVG, vector PDF). Raster reconstruction is not implemented")
    raise UnsupportedSource(f"unrecognised file type .{suffix}")


def convert_file(path: str | Path, formats=("pdf", "dxf"), out_dir: str | Path = "converted",
                 sheet=None, scale=None, page: int = 1, units: str = DEFAULT_UNITS,
                 dpi: float = 150.0) -> dict:
    """Convert one source; returns the report, which lists every file written."""
    formats = [f.lower() for f in formats]
    bad = [f for f in formats if f not in FORMATS]
    if bad:
        raise ValueError(f"unsupported output format(s): {', '.join(bad)}; use {', '.join(FORMATS)}")

    drawing = analyze(clean(read(path, page=page)))
    if drawing.quality == "UNUSABLE":
        report = build_report(drawing, {}, reconstructed=False)
        report["warnings"].insert(0, "source is UNUSABLE: nothing was exported")
        return report

    scene = build_drawing_scene(drawing, sheet=sheet, scale=scale, units=units)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = out / (Path(path).stem + "-clean")
    written: dict[str, str] = {}
    if "pdf" in formats:
        stem.with_suffix(".pdf").write_bytes(render_pdf(scene)); written["pdf"] = str(stem.with_suffix(".pdf"))
    if "dxf" in formats:
        stem.with_suffix(".dxf").write_text(render_dxf(scene), encoding=DXF_ENCODING, errors="replace")
        written["dxf"] = str(stem.with_suffix(".dxf"))
    if "svg" in formats:
        stem.with_suffix(".svg").write_text(render_svg(scene), encoding="utf-8"); written["svg"] = str(stem.with_suffix(".svg"))
    if "png" in formats:
        stem.with_suffix(".png").write_bytes(render_png(scene, dpi=dpi)); written["png"] = str(stem.with_suffix(".png"))

    report = build_report(drawing, written)
    report["sheet"] = scene.sheet.name
    report["output_scale"] = scene.scale.label
    (out / (Path(path).stem + "-report.md")).write_text(report_markdown(report), encoding="utf-8")
    (out / (Path(path).stem + "-report.json")).write_text(report_json(report), encoding="utf-8")
    report["outputs"]["report_md"] = str(out / (Path(path).stem + "-report.md"))
    report["outputs"]["report_json"] = str(out / (Path(path).stem + "-report.json"))
    return report
