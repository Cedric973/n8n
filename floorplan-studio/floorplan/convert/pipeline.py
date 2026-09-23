"""ANALYZE → CLEAN → RECONSTRUCT → VALIDATE → EXPORT, as one call."""

from __future__ import annotations

from pathlib import Path

from ..dxf import DXF_ENCODING, render_dxf
from ..pdf import render_pdf
from ..raster import render_png
from ..svg import render_svg
from ..levels import LEVELS, LEVEL_INFO
from ..quality import check_scene, summary
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


def page_count(path: str | Path) -> int:
    if Path(path).suffix.lower() != ".pdf":
        return 1
    from pdfminer.pdfpage import PDFPage
    with open(path, "rb") as handle:
        return sum(1 for _ in PDFPage.get_pages(handle))


def convert_file(path: str | Path, formats=("pdf", "dxf"), out_dir: str | Path = "converted",
                 sheet=None, scale=None, page: int = 1, units: str = DEFAULT_UNITS,
                 dpi: float = 150.0, multipage: bool = False, levels=None,
                 drawing_number: str | None = None, revision: str = "A") -> dict:
    """Convert one source page; returns the report, which lists every file written.

    Each requested level (client, dimension, technical) is written in each
    requested format, keyed ``"<level>_<format>"`` in the report's outputs.
    """
    levels = list(levels or LEVELS)
    formats = [f.lower() for f in formats]
    bad = [f for f in formats if f not in FORMATS]
    if bad:
        raise ValueError(f"unsupported output format(s): {', '.join(bad)}; use {', '.join(FORMATS)}")

    drawing = analyze(clean(read(path, page=page)))
    if drawing.quality == "UNUSABLE":
        report = build_report(drawing, {}, reconstructed=False)
        report["warnings"].insert(0, "source is UNUSABLE: nothing was exported")
        report["page"] = page
        return report

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    suffix = f"-p{page}" if multipage else ""
    written: dict[str, str] = {}
    scene = None
    readability: dict[str, dict] = {}
    for level in levels:
        scene = build_drawing_scene(drawing, sheet=sheet, scale=scale, units=units, level=level,
                                    drawing_number=drawing_number, revision=revision)
        readability[level] = summary(check_scene(scene))
        stem = out / f"{Path(path).stem}{suffix}-{LEVEL_INFO[level][0]}"
        for fmt in formats:
            target = stem.with_suffix("." + fmt)
            if fmt == "pdf":
                target.write_bytes(render_pdf(scene))
            elif fmt == "dxf":
                target.write_text(render_dxf(scene), encoding=DXF_ENCODING, errors="replace")
            elif fmt == "svg":
                target.write_text(render_svg(scene), encoding="utf-8")
            elif fmt == "png":
                target.write_bytes(render_png(scene, dpi=dpi))
            written[f"{level}_{fmt}"] = str(target)

    report = build_report(drawing, written)
    report["page"] = page
    report["levels"] = levels
    report["sheet_type"] = drawing.metadata.get("sheet_type", "unknown")
    report["sheet"] = scene.sheet.name
    report["output_scale"] = scene.scale.label
    report["readability"] = readability
    worst = max(readability.values(), key=lambda r: r["issues"], default=None)
    if worst and worst["issues"]:
        report["warnings"].append(
            "readability: " + ", ".join(f"{level} plan {r['issues']} issue(s)"
                                        for level, r in readability.items() if r["issues"]))
    md = out / (Path(path).stem + suffix + "-report.md")
    js = out / (Path(path).stem + suffix + "-report.json")
    md.write_text(report_markdown(report), encoding="utf-8")
    js.write_text(report_json(report), encoding="utf-8")
    report["outputs"]["report_md"] = str(md)
    report["outputs"]["report_json"] = str(js)
    return report


def convert_pages(path: str | Path, pages: list[int] | None = None, **kwargs) -> dict:
    """Convert several pages of one file; returns per-page reports and a set summary."""
    total = page_count(path)
    wanted = pages or list(range(1, total + 1))
    bad = [p for p in wanted if p < 1 or p > total]
    if bad:
        raise ValueError(f"page(s) {bad} out of range 1..{total}")
    reports = []
    for p in wanted:
        try:
            reports.append(convert_file(path, page=p, multipage=True, **kwargs))
        except Exception as exc:  # noqa: BLE001 - one bad page must not sink the set
            reports.append({"page": p, "error": str(exc), "source_quality": "UNUSABLE",
                            "outputs": {}, "warnings": [f"page {p} failed: {exc}"]})
    summary = {
        "source_file": str(path), "pages_in_source": total, "pages_converted": wanted,
        "pages": [{"page": r.get("page"), "sheet_type": r.get("sheet_type", "unknown"),
                   "quality": r.get("source_quality"), "scale": r.get("detected_scale"),
                   "scale_provenance": r.get("scale_provenance"),
                   "warnings": len(r.get("warnings", [])), "error": r.get("error")}
                  for r in reports],
        "reports": reports,
    }
    out = Path(kwargs.get("out_dir", "converted"))
    out.mkdir(parents=True, exist_ok=True)
    js = out / (Path(path).stem + "-set-summary.json")
    js.write_text(report_json(summary), encoding="utf-8")
    summary["summary_json"] = str(js)
    return summary
