"""The conversion report: what was read, what was done, and how far to trust it."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .model import Drawing, Provenance, Role


def build_report(drawing: Drawing, outputs: dict[str, str], reconstructed: bool = True) -> dict:
    by_prov: dict[str, dict[str, int]] = {p.value: {} for p in Provenance}
    for e in drawing.entities:
        by_prov[e.provenance.value][e.role.value] = by_prov[e.provenance.value].get(e.role.value, 0) + 1
    unknown_roles = sum(1 for e in drawing.entities if e.role == Role.OTHER)
    warnings = [n for n in drawing.notes if any(
        k in n.lower() for k in ("warning", "unknown", "low confidence", "not converted",
                                 "not vectorised", "disagree", "skipped", "cannot"))]
    return {
        "source_file": drawing.source,
        "source_format": drawing.format,
        "source_quality": drawing.quality,
        "detected_discipline": drawing.metadata.get("disciplines", ["architecture"]),
        "detected_scale": drawing.scale_label,
        "scale_provenance": drawing.scale_provenance.value,
        "detected_units": drawing.units,
        "units_provenance": drawing.units_provenance.value,
        "sheets_in_source": drawing.sheets,
        "extent_m": drawing.metadata.get("extent_m"),
        "building_extent_m": drawing.metadata.get("building_extent_m"),
        "output_formats": sorted(outputs),
        "outputs": outputs,
        "reconstruction_performed": "YES" if reconstructed else "NO",
        "reconstruction_kind": "vector re-issue on a standard sheet" if reconstructed else "none",
        "verified_elements": by_prov[Provenance.VERIFIED.value],
        "calculated_elements": by_prov[Provenance.CALCULATED.value],
        "inferred_elements": by_prov[Provenance.INFERRED.value],
        "unknown_elements": {"unclassified_entities": unknown_roles,
                             "unreadable_text_lines": drawing.metadata.get("unreadable_text", 0),
                             **by_prov[Provenance.UNKNOWN.value]},
        "layers_in_source": drawing.layers(),
        "warnings": warnings,
        "notes": drawing.notes,
        "date": date.today().isoformat(),
    }


def report_markdown(report: dict) -> str:
    def block(title: str, mapping: dict) -> str:
        if not mapping:
            return f"**{title}:** none\n"
        rows = "\n".join(f"| {k} | {v} |" for k, v in sorted(mapping.items()))
        return f"**{title}:**\n\n| element | count |\n|---|---|\n{rows}\n"

    lines = [
        f"# Conversion report — {Path(report['source_file']).name}",
        "",
        f"- **Source file:** `{report['source_file']}` ({report['source_format'].upper()}, "
        f"{report['sheets_in_source']} sheet(s))",
        f"- **Source quality:** {report['source_quality']}",
        f"- **Detected discipline:** {', '.join(report['detected_discipline'])}",
        f"- **Detected scale:** {report['detected_scale'] or 'unknown'} "
        f"[{report['scale_provenance'].upper()}]",
        f"- **Detected units:** {report['detected_units'] or 'unknown'} "
        f"[{report['units_provenance'].upper()}]",
        f"- **Drawing extent:** {report['extent_m'][0]} × {report['extent_m'][1]} m" if report.get("extent_m") else "- **Drawing extent:** unknown",
        f"- **Building extent (walls):** {report['building_extent_m'][0]} × {report['building_extent_m'][1]} m" if report.get("building_extent_m") else "- **Building extent (walls):** no walls recognised",
        f"- **Output format(s):** {', '.join(f.upper() for f in report['output_formats']) or 'none'}",
        f"- **Reconstruction performed:** {report['reconstruction_performed']} "
        f"({report['reconstruction_kind']})",
        "",
        block("Verified elements", report["verified_elements"]),
        block("Calculated elements", report["calculated_elements"]),
        block("Inferred elements", report["inferred_elements"]),
        block("Unknown elements", report["unknown_elements"]),
        "**Readability (text overlaps / small print / text on walls):**",
        *([f"- {level}: {r['overlap']} overlap(s), {r['small']} small, {r['over-wall']} on walls"
           for level, r in report.get("readability", {}).items()] or ["- not checked"]),
        "",
        "**Warnings:**",
        *([f"- {w}" for w in report["warnings"]] or ["- none"]),
        "",
        "**Processing notes:**",
        *([f"- {n}" for n in report["notes"]] or ["- none"]),
        "",
        "**Outputs:**",
        *[f"- `{p}`" for p in report["outputs"].values()],
        "",
        f"_Generated {report['date']}. Provenance: VERIFIED = read directly from the source; "
        "CALCULATED = derived from reliable source data; INFERRED = likely interpretation, "
        "drawn dashed; UNKNOWN = could not be determined._",
    ]
    return "\n".join(lines) + "\n"


def report_json(report: dict) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False) + "\n"
