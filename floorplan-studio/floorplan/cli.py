"""Command line entry point: ``python -m floorplan.cli``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .api import RequestError, generate_from
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
        description="Generate residential floor plans from a footprint and a room program.",
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    formats = [f.strip().lower() for f in args.formats.split(",") if f.strip()]
    unknown = [f for f in formats if f not in FORMATS]
    if unknown:
        print(f"floorplan: unknown format(s): {', '.join(unknown)}", file=sys.stderr)
        return 2
    payload = payload_from(args)
    try:
        plans = generate_from(payload)
        scenes = [build_scene(p, sheet=payload.get("sheet"), scale=payload.get("scale"))
                  for p in plans]
    except (RequestError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"floorplan: {exc}", file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    for rank, (plan, scene) in enumerate(zip(plans, scenes), start=1):
        stem = args.out / f"plan-{rank}-seed{plan.seed}"
        written = []
        if "svg" in formats:
            stem.with_suffix(".svg").write_text(render_svg(scene), encoding="utf-8")
            written.append("svg")
        if "pdf" in formats:
            stem.with_suffix(".pdf").write_bytes(render_pdf(scene))
            written.append("pdf")
        if "png" in formats:
            stem.with_suffix(".png").write_bytes(render_png(scene, dpi=args.dpi))
            written.append("png")
        if "dxf" in formats:
            stem.with_suffix(".dxf").write_text(render_dxf(scene), encoding=DXF_ENCODING,
                                                errors="replace")
            written.append("dxf")
        if "json" in formats:
            stem.with_suffix(".json").write_text(
                json.dumps(plan.to_dict(), indent=2), encoding="utf-8"
            )
            written.append("json")
        if not args.quiet:
            summary = plan.summary()
            print(
                f"{stem.name}: score {summary['score']:.1f}  "
                f"{summary['bedrooms']} bed / {summary['bathrooms']} bath  "
                f"{format_area(plan.conditioned_sqft, plan.spec.units)}  "
                f"{scene.sheet.name} @ {scene.scale.label}  -> {', '.join(written)}"
            )
        if args.preview:
            print(ascii_plan(plan))
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
