"""Command line entry point: ``python -m floorplan.cli``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .api import RequestError, generate_from
from .levels import LEVEL_INFO, parse_levels
from .units import DEFAULT_EXTENT, DEFAULT_UNITS, format_area
from .dxf import DXF_ENCODING, render_dxf
from .pdf import render_pdf
from .preview import ascii_plan
from .raster import render_png
from .render import build_scene
from .svg import render_svg

FORMATS = ("svg", "pdf", "png", "dxf", "json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="floorplan",
        description="Generate residential floor plans from a footprint and a room program. "
                    "Use `floorplan convert <file>` to re-issue an existing DXF, SVG or PDF plan.",
    )
    shape = parser.add_argument_group("footprint")
    shape.add_argument("--shape", default="rectangle", choices=("rectangle", "l", "t", "u"))
    shape.add_argument("--width", type=float,
                       help="overall east-west size, in the chosen units (default 15 m)")
    shape.add_argument("--depth", type=float,
                       help="overall north-south size, in the chosen units (default 10 m)")
    shape.add_argument("--notch-w", type=float, help="notch width for l/u shapes")
    shape.add_argument("--notch-h", type=float, help="notch depth for l/u shapes")
    shape.add_argument("--spec", type=Path, help="JSON request file; overrides the flags above")

    program = parser.add_argument_group("program")
    program.add_argument("--bedrooms", type=int, default=3)
    program.add_argument("--bathrooms", type=int, default=2)
    program.add_argument("--office", action="store_true")
    program.add_argument("--garage", action="store_true")
    program.add_argument("--mudroom", action="store_true")
    program.add_argument("--no-dining", dest="formal_dining", action="store_false")
    program.add_argument("--no-pantry", dest="pantry", action="store_false")
    program.add_argument("--no-laundry", dest="laundry", action="store_false")

    out = parser.add_argument_group("output")
    out.add_argument("--units", default=DEFAULT_UNITS, choices=("imperial", "metric"),
                     help="units for --width/--depth and for every printed dimension")
    out.add_argument("--title", default="Untitled Plan")
    out.add_argument("--variants", type=int, default=3)
    out.add_argument("--seed", type=int, default=0)
    out.add_argument("--out", type=Path, default=Path("plans"))
    out.add_argument("--formats", default="svg,pdf,png,dxf",
                     help=f"comma separated, from {','.join(FORMATS)}")
    out.add_argument("--sheet", help="sheet size, e.g. 'ANSI C' or 'A3'; default fits the plan")
    out.add_argument("--scale", help="drawing scale, e.g. '1/4\" = 1'-0\"' or '1:100'")
    out.add_argument("--dpi", type=float, default=150.0, help="PNG resolution")
    out.add_argument("--level", default="all",
                     help="client, dimension, technical, a comma list, or all (default)")
    out.add_argument("--drawing-number", default="A-101")
    out.add_argument("--revision", default="A")
    out.add_argument("--preview", action="store_true", help="print an ASCII plan per variant")
    out.add_argument("--quiet", action="store_true")
    return parser


def payload_from(args: argparse.Namespace) -> dict:
    if args.spec:
        return json.loads(args.spec.read_text(encoding="utf-8"))
    default_w, default_d = DEFAULT_EXTENT[args.units]
    return {
        "shape": args.shape,
        "width": args.width if args.width is not None else default_w,
        "depth": args.depth if args.depth is not None else default_d,
        "notch_w": args.notch_w, "notch_h": args.notch_h,
        "bedrooms": args.bedrooms, "bathrooms": args.bathrooms,
        "office": args.office, "garage": args.garage, "mudroom": args.mudroom,
        "formal_dining": args.formal_dining, "pantry": args.pantry,
        "laundry": args.laundry, "title": args.title, "units": args.units,
        "sheet": args.sheet, "scale": args.scale,
        "variants": args.variants, "seed": args.seed,
    }


def build_convert_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="floorplan convert",
        description="Read an existing DXF, SVG or vector PDF plan and re-issue it cleanly.",
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("--to", default="pdf,dxf", help="comma separated: pdf,dxf,svg,png")
    parser.add_argument("--out", type=Path, default=Path("converted"))
    parser.add_argument("--page", type=int, default=1, help="PDF page to read")
    parser.add_argument("--pages", help="'all' or a list like 1,3,4: convert several pages")
    parser.add_argument("--units", default=DEFAULT_UNITS, choices=("imperial", "metric"),
                        help="presentation units for the re-issued sheet")
    parser.add_argument("--sheet", help="force a sheet size, e.g. 'A3' or 'ANSI C'")
    parser.add_argument("--scale", help="force a drawing scale, e.g. '1:100'")
    parser.add_argument("--dpi", type=float, default=150.0)
    parser.add_argument("--level", default="all",
                        help="client, dimension, technical, a comma list, or all (default)")
    parser.add_argument("--drawing-number", default="A-101")
    parser.add_argument("--revision", default="A")
    parser.add_argument("--quiet", action="store_true")
    return parser


def convert_main(argv: list[str]) -> int:
    from .convert.pipeline import UnsupportedSource, convert_file

    args = build_convert_parser().parse_args(argv)
    formats = [f.strip().lower() for f in args.to.split(",") if f.strip()]
    if not args.source.is_file():
        print(f"floorplan: no such file: {args.source}", file=sys.stderr)
        return 1
    try:
        levels = parse_levels(args.level)
        extra = dict(levels=levels, drawing_number=args.drawing_number, revision=args.revision)
        if args.pages:
            from .convert.pipeline import convert_pages
            pages = None if args.pages.strip().lower() == "all" else [int(p) for p in args.pages.split(",")]
            summary = convert_pages(args.source, pages=pages, formats=formats, out_dir=args.out,
                                    sheet=args.sheet, scale=args.scale, units=args.units, dpi=args.dpi,
                                    **extra)
            if not args.quiet:
                print(f"{args.source.name}: {len(summary['pages_converted'])} of "
                      f"{summary['pages_in_source']} page(s)")
                for row in summary["pages"]:
                    print(f"  p{row['page']:<3} {row['sheet_type']:<18} {str(row['quality']):<11} "
                          f"scale {row['scale'] or 'unknown'} [{row['scale_provenance']}]"
                          + (f"  ERROR {row['error']}" if row['error'] else ""))
                print(f"  summary     {summary['summary_json']}")
            return 0 if all(r.get("reconstruction_performed") == "YES" for r in summary["reports"]) else 2
        report = convert_file(args.source, formats=formats, out_dir=args.out, sheet=args.sheet,
                              scale=args.scale, page=args.page, units=args.units, dpi=args.dpi,
                              **extra)
    except (UnsupportedSource, ValueError, ImportError, OSError) as exc:
        print(f"floorplan: {exc}", file=sys.stderr)
        return 1
    if not args.quiet:
        print(f"{args.source.name}: quality {report['source_quality']}, "
              f"scale {report['detected_scale'] or 'unknown'} [{report['scale_provenance']}], "
              f"units {report['detected_units'] or 'unknown'} [{report['units_provenance']}]")
        counts = {**report['verified_elements']}
        print(f"  verified {sum(report['verified_elements'].values())}  "
              f"calculated {sum(report['calculated_elements'].values())}  "
              f"inferred {sum(report['inferred_elements'].values())}")
        for w in report["warnings"]:
            print(f"  ! {w}")
        for fmt, path in report["outputs"].items():
            print(f"  {fmt:11s} {path}")
    return 0 if report["reconstruction_performed"] == "YES" else 2


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "convert":
        return convert_main(argv[1:])
    args = build_parser().parse_args(argv)
    formats = [f.strip().lower() for f in args.formats.split(",") if f.strip()]
    unknown = [f for f in formats if f not in FORMATS]
    if unknown:
        print(f"floorplan: unknown format(s): {', '.join(unknown)}", file=sys.stderr)
        return 2
    payload = payload_from(args)
    try:
        levels = parse_levels(args.level)
        plans = generate_from(payload)
    except (RequestError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"floorplan: {exc}", file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    from .quality import check_scene
    for rank, plan in enumerate(plans, start=1):
        written = []
        scene = None
        issues = []
        for level in levels:
            try:
                scene = build_scene(plan, sheet=payload.get("sheet"), scale=payload.get("scale"),
                                    level=level, drawing_number=args.drawing_number,
                                    revision=args.revision)
            except ValueError as exc:
                print(f"floorplan: {exc}", file=sys.stderr)
                return 1
            stem = args.out / f"plan-{rank}-seed{plan.seed}-{LEVEL_INFO[level][0]}"
            if "svg" in formats:
                stem.with_suffix(".svg").write_text(render_svg(scene), encoding="utf-8")
            if "pdf" in formats:
                stem.with_suffix(".pdf").write_bytes(render_pdf(scene))
            if "png" in formats:
                stem.with_suffix(".png").write_bytes(render_png(scene, dpi=args.dpi))
            if "dxf" in formats:
                stem.with_suffix(".dxf").write_text(render_dxf(scene), encoding=DXF_ENCODING,
                                                    errors="replace")
            written.append(stem.name)
            issues += [(level, i) for i in check_scene(scene)]
        if "json" in formats:
            (args.out / f"plan-{rank}-seed{plan.seed}.json").write_text(
                json.dumps(plan.to_dict(), indent=2), encoding="utf-8")
        if not args.quiet:
            summary = plan.summary()
            print(
                f"plan-{rank}-seed{plan.seed}: score {summary['score']:.1f}  "
                f"{summary['bedrooms']} bed / {summary['bathrooms']} bath  "
                f"{format_area(plan.conditioned_sqft, plan.spec.units)}  "
                f"{scene.sheet.name} @ {scene.scale.label}  -> {', '.join(formats)} x "
                f"{', '.join(levels)}"
            )
            for level, issue in issues[:8]:
                print(f"  ! readability ({level}): {issue}")
            if len(issues) > 8:
                print(f"  ! readability: {len(issues) - 8} more")
        if args.preview:
            print(ascii_plan(plan))
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
