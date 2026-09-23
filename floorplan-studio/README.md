# floorplan-studio

Generate residential floor plans from a footprint outline and a room program.
Draw a shape, say how many bedrooms you want, and get back dimensioned,
connected plans with doors and windows — as SVG, PDF or CAD-ready DXF.

Metric by default: metres, m², and 1:50.

It also works the other way round: give it an existing DXF, SVG or vector PDF
plan and it will read it, work out its units and scale, recognise walls and
doors, and re-issue it cleanly on a standard sheet — with a report that says
what it read, what it worked out, what it guessed and what it could not tell.

No third-party dependencies for generating plans. Python 3.10+, standard
library only. Converting *existing* plans is an optional extra that brings in
`ezdxf` and `pdfminer.six`.

```bash
python3 -m floorplan.server          # web UI on http://127.0.0.1:8000
python3 -m floorplan.cli --preview   # or straight to files
```

```bash
python3 -m floorplan.cli --width 17 --depth 12 --bedrooms 4      # metres
python3 -m floorplan.cli --units imperial --width 56 --depth 40  # feet
```

## The web UI

`python3 -m floorplan.server` serves a single-page app: pick a preset footprint
or click out any rectilinear shape on the grid, set the program, and generate.
Each option renders inline and downloads as PDF, SVG or DXF.

It binds to `127.0.0.1` and has no authentication, because it is a tool you run
on your own machine. Don't put it on a public interface.

## The CLI

```bash
python3 -m floorplan.cli \
    --shape l --width 17 --depth 12 \
    --bedrooms 4 --bathrooms 3 --garage --mudroom \
    --title "Rue des Lilas" --variants 3 \
    --out plans --formats svg,pdf,png,dxf --preview
```

`--preview` prints an ASCII plan per variant, which is the fastest way to see
whether a layout is sensible without opening anything. `--spec request.json`
takes the same JSON body the HTTP API accepts.

`--width` and `--depth` are metres unless you pass `--units imperial`, which
reads them as feet and prints feet, inches and square feet instead. The web UI
has the same switch.

`--sheet` and `--scale` override the automatic choice (`--sheet "ANSI C"`,
`--scale 1:100`). Asking for a scale that will not fit on any sheet is an error
naming one that will, rather than a drawing that runs off the paper.

## Three drawings from one plan

Every plan — generated or converted — is issued at three levels, each on its
own sheet, because a client, a builder and a checker do not want the same
drawing:

| Level | File suffix | Caption | What is on it |
|---|---|---|---|
| client | `01-client` | FLOOR PLAN | Walls, doors, windows, room name + area. Dimensions on two faces only. No provenance vocabulary. |
| dimension | `02-dimension` | DIMENSION PLAN | The client plan plus every dimension chain and the source's own figures. |
| technical | `03-technical` | TECHNICAL PLAN | Everything: furniture, grids, inferred geometry dashed and tinted, quality grade and VERIFIED / CALCULATED / INFERRED / UNKNOWN counts in the title block. |

`--level client,dimension,technical` (default `all`) picks which to write;
`--drawing-number` and `--revision` fill the title block. The web UI previews
the client plan and offers downloads grouped by level.

The line hierarchy is the same at every level: exterior walls heaviest,
interior walls lighter, a window is a clear opening with two thin glazing
lines, a door is its leaf and a thin swing arc. Colour is used sparingly and
only where the drawing still reads in black and white. No text is printed
smaller than 2 mm on the sheet, whatever size it had in the source.

The words VERIFIED, INFERRED and so on never appear on the client or dimension
plan. They belong to the technical plan and the conversion report, which is
where a checker looks for them.

Generated plans carry the few fixtures that make a room read as what it is:
a bed and nightstands in each bedroom, tub, WC and basin in each bath, a
counter run with sink and range in the kitchen. They sit against door-free
walls, never in a door's swing, and never under the room's label.

### Readability check

Every sheet is checked before it is written (`floorplan/quality.py`): two
texts whose boxes overlap, text that would print under 1.8 mm at the sheet's
scale, and a room label lying on a wall are each reported. The generator
prints them per plan; the converter puts a count per level in the report.
The client plan of a generated house has none by construction — labels step
out of door swings and fixtures keep clear of labels — and the test suite
holds that across footprints. A converted dimension plan usually has some,
because the source's own figures, enlarged to legible size, land on each
other; the count says how many.

## Converting an existing plan

```bash
pip install "floorplan-studio[convert]"        # ezdxf + pdfminer.six
python3 -m floorplan.cli convert plan.pdf --to pdf,dxf,svg,png --out converted
```

The web UI has the same thing as an upload panel. Either way you get the
re-issued plan in each requested format plus `plan-report.md` and
`plan-report.json`.

| Source | Reads | Notes |
|---|---|---|
| DXF | every revision, blocks, curves | units from `$INSUNITS` when declared |
| SVG | shapes, paths, transforms, text | page size from `width`/`viewBox` |
| PDF | vector paths and positioned text | one page at a time; scans are refused, not guessed at |
| DWG, DWF, RVT, IFC | — | refused with the export step that would work (DXF) |
| PNG, JPG, TIFF, scans, photos | — | refused; raster reconstruction is not implemented |

On a converted plan the client sheet also gets its own dimension chains on
the south and west faces, read off the reconstructed walls: bay marks where
a wall meets the face and both ends of each window in it, plus the overall
run. The dimension and technical sheets keep the source's dimensions instead
and get our chains only when the source had none — a plan is not
dimensioned twice. Room labels on the client and dimension sheets are set in
the middle of their room when a flood fill of the source's linework finds a
room whose area agrees with the printed one; otherwise they stay where the
source put them.

### What the analyzer does, and how far to trust it

Doors are recognised by their swing: a native arc, a flattened polyline on
one circle, a swing the export split into pieces (rejoined when the pieces
share a centre and radius and their sweeps add up), or a lone 45° half-swing
whose hinge sits on a wall. Each door then gets its leaf, from the hinge to
the end of the arc that stands out in the room. Windows are recognised two
ways: two or three glazing lines a few centimetres apart inside a wall, or a
gap in a wall run closed by one thin line along it — the way most plans draw
glass — which is redrawn as the standard symbol. Openings also join the wall
runs either side of them, so a building whose halves meet only at a window
is still one building to the pruning step.

Everything the converter knows carries a provenance, on every entity and on
the drawing's units and scale, and nothing is promoted silently:

| | Meaning | Example |
|---|---|---|
| **VERIFIED** | read directly from the source | a line on a layer called `A-WALL`; a printed `1:100` |
| **CALCULATED** | derived mathematically from reliable source data | a scale measured from dimension strings against their tick marks |
| **INFERRED** | a likely interpretation, not confirmed | two parallel lines 0.2 m apart called a wall; a quarter-circle of 0.9 m called a door |
| **UNKNOWN** | could not be determined | a PDF with no printed scale and no readable dimensions |

In order, the analyzer:

1. **Resolves units.** A DXF may declare them. Otherwise they are inferred from
   the drawing's extent — 15 000 across is millimetres, 15 is metres — and
   flagged as such. A PDF or SVG is in paper units until a scale is known.
2. **Resolves scale.** A printed scale on the sheet is believed. Failing that,
   every dimension string — "3.60 m", `12'-6"`, or a bare "3600" read as
   millimetres, as CAD writes it — is measured against the two tick marks it
   sits between; the median of at least three readings agreeing within 8% is a
   *calculated* scale, and scattered readings are refused rather than averaged
   into a confident wrong answer. Failing that, room-area labels ("51.88 m²")
   are flood-filled to their walls and set against the printed area; when most
   rooms agree, that is an *inferred* scale. Failing all three, the scale is
   unknown, the geometry stays in paper metres, and the sheet says so. A sheet
   stamped N.T.S. caps whatever was measured at *inferred*.
3. **Classifies by layer.** Layer names in several languages are believed
   (`WALL`, `MUR`, `WAND`; `DOOR`, `PORTE`; `FEN`, `WIND`; `DIM`, `COTE`…).
   Discipline follows from them too: `E-` or `LIGHT` means electrical is
   present, `P-` or `PIPE` plumbing, and so on.
4. **Infers from geometry** what no layer explained: thin filled outlines and
   parallel line pairs a wall's width apart become walls; arcs of a door's
   radius and sweep become doors; the largest body of walls *with room names
   inside it* is the building, so a sheet border — longer than any house — is
   not; anything far outside it, and any rule longer than half the building
   just outside it, is the source's own sheet furniture and is set aside, since
   the re-issued sheet supplies its own.
5. **Reconstructs walls the export flattened.** CAD plot drivers turn a SOLID
   or ANSI31 hatch into hundreds of hairline strokes 0.1 mm apart; no stroke is
   a wall and no pair is a wall face, so the rules above see nothing. Strokes
   are sampled on a 5 cm grid, cells crossed by two or more are solid, and a
   connected solid region with a wall's thickness is a wall — handed back as
   merged rectangles so it exports to CAD as linework. On a real ten-page set
   this turned 4,365 strokes into 27 wall regions and the recognised building
   from a 7 × 11 m fragment into the full 38 × 16 m.
6. **Cleans**: drops zero-length and duplicate entities, merges collinear
   segments, snaps lines within 1.5° of an axis. Each step is counted in the
   report. Text is never touched — except text from a font with no Unicode
   map, which arrives as `(cid:1234)` and is counted as unknown, kept in place
   in the report, and never drawn.
7. **Types and grades the sheet**: plan, elevation/section, schedule or
   detail from its own words; EXCELLENT to POOR from what it could establish.
   UNUSABLE is reserved for a source with no vector geometry at all, and
   nothing is exported for it.

`--pages all` (or `--pages 1,3,4`) converts a set, one report per page plus
a summary of page types and grades.

Inferred geometry is drawn **dashed** (walls in a distinct tint) so a reader
can tell recognised geometry from confirmed geometry on the sheet itself, and
the title block carries the provenance counts.

Two things this is not. It is not a DWG converter: DWG is a proprietary
binary and reading it needs Autodesk's or ODA's own tooling, so the converter
tells you to export DXF rather than produce a fake `.dwg`. And it is not a
scan vectoriser: a photographed or scanned plan is refused, because a
reconstruction from pixels would have to be presented as verified geometry to
be useful and it would not be.

The round trip is exact enough to test against: a generated plan exported as
PDF, read back with its printed scale deleted, comes back at 1:50 from
seventeen dimension readings that agree to within 0.1%, with every door found
from its swing alone.

## As a library

```python
from floorplan import Polygon, PlanSpec, generate
from floorplan.render import build_scene
from floorplan.svg import render_svg

# Footprints are always built in feet — that is the internal unit — but every
# printed dimension follows spec.units, which defaults to metric.
spec = PlanSpec.from_program(
    Polygon.rectangle(48, 32), bedrooms=3, bathrooms=2, title="Rue des Lilas"
)
best = generate(spec, variants=3)[0]
print(best.summary())
open("plan.svg", "w").write(render_svg(build_scene(best)))
```

Footprints can be `rectangle`, `l_shape`, `t_shape`, `u_shape`, or any
rectilinear `Polygon` you pass vertices for. Room types, target areas, minimum
dimensions and adjacency preferences all live in `spec.py` and are meant to be
edited.

## Sheets and scale

Every drawing is laid out on a standard sheet at a standard architectural
scale, not stretched to fill the page. That is what lets two plans be compared
side by side, and what lets a scale rule laid on a print read something true: at
1:50, a 20 m building measures exactly 400 mm on paper.

The scale is chosen by working outward from the largest — keeping as much detail
as the paper allows — and then taking the smallest sheet that holds it. So an
8 x 7 m cottage and a 20 x 14 m house both come out at 1:50; the cottage simply
occupies less of its sheet, which is information rather than wasted paper. Only when nothing standard fits does a drawing get fitted to the
largest sheet, and it is then labelled `NOT TO SCALE` rather than mislabelled.

| | Sheets | Scales |
|---|---|---|
| Metric (default) | A4 to A1 | 1:50, 1:75, 1:100, 1:150, 1:200 |
| Imperial | ANSI A to D | 1/4", 3/16", 1/8", 3/32", 1/16" = 1'-0" |

Scale is carried as points per foot, since the drawing is built in feet and PDF
measures in points. Both tables fall out of `864 / ratio`, a foot being 864
points at full size. The PDF page is the sheet, the SVG declares its true size
in inches or millimetres, and the PNG carries a `pHYs` chunk recording its real
DPI — so all three print at the scale they claim.

## Units

**Metric is the default.** Most of the world builds in metres, and a drawing
dimensioned in feet and inches is simply unreadable to a reader who does not
think in them. Pass `units="imperial"` — or `--units imperial` — to get the
other system; nothing else changes.

The solver works in feet throughout — the room catalog, minimum dimensions and
wall thicknesses are all authored that way — so units are a boundary concern.
Lengths and areas are converted to feet on the way in and formatted back on the
way out; nothing in the geometry or the layout knows which system you asked for,
and the same seed produces geometrically identical plans either way.

| | Metric (default) | Imperial |
|---|---|---|
| Dimension | `3.81 m` | `12'-6"` |
| Room | `3.81 x 3.05 m` | `12'-6" x 10'-0"` |
| Area | `11.7 m²` | `126 SF` |
| Scale bar | 3 m | 10 ft |
| Sheet and scale | A4–A1, 1:50–1:200 | ANSI A–D, 1/4"–1/16" = 1'-0" |
| Default extent | 15 × 10 m | 48 × 32 ft |

Metric output uses metres to two decimals rather than millimetres. Millimetres
are the ISO convention for construction drawings, but this is a schematic tool
and `5.03 m` reads better than `5030` for someone sizing a house.

Because `m²` is outside ASCII, DXF is written as CP1252 with a `$DWGCODEPAGE`
header rather than UTF-8 — R12 predates Unicode, and a file the CAD package
mis-decodes is worse than one that says which code page it used.

## How it generates a plan

There is no trained model here, and it does not need one. A floor plan is a
constraint problem, and solving it directly is faster and reproducible: the
same seed always gives the same plan, which is what makes the download button
able to rebuild exactly the option you clicked.

For each seed:

1. **Decompose** the footprint into rectangles. A vertical sweep cuts at every
   vertex, reads the interior y-intervals of each strip, and merges strips that
   share an interval. An L-shape yields two rectangles, a U-shape three.
2. **Scale** the room program so its areas exactly fill the footprint. Catalog
   areas are wishes, not constraints; relative proportions are what survive.
3. **Pack** rooms into those rectangles in zone order, so public, private and
   service rooms stay clustered instead of interleaving.
4. **Slice** each rectangle into zone blocks, then each block into rooms, by
   recursive guillotine cuts. Cuts run across the long side and are rejected
   when they would starve a room of its minimum dimension.
5. **Carve** a corridor out of any private block big enough to need one,
   running toward whichever side faces the rest of the house, with rooms
   balanced on either side.
6. **Open** doors along a spanning tree of the adjacency graph, rooted at the
   front door, then add windows to exterior walls.
7. **Score** the result, and keep the best plans that are not near-duplicates.

Three decisions do most of the work for plan quality:

- **Rooms are sliced in a designed sequence, not by size.** A guillotine cut
  keeps neighbours in the sequence adjacent, so listing the kitchen after the
  dining room is what makes them share a wall. Satellite rooms — a pantry, a
  walk-in, an ensuite — are marked as attached and are never cut away from what
  they serve.
- **Minimum dimensions are enforced at the cut, not just penalised.** A cut is
  pushed far enough from both edges for each side to be usable, trading a
  little area accuracy for shape validity. When neither side can have what it
  wants, the tighter requirement wins, because a bathroom's width is set by its
  fixtures and a bedroom's is not.
- **Doors come from a spanning tree**, not from "connect everything that
  touches", so circulation is deliberate. Bathrooms, closets and the garage are
  forced to be leaves of that tree — you never walk through a bathroom to reach
  a bedroom.

Many seeds are tried per request and scored on area error, room proportions,
starved dimensions, daylight, adjacency preferences, plumbing grouping and
connectivity. Roughly one seed in eight produces a plan with an unreachable
room; scoring rejects those, and no plan returned by `generate()` has one.

## Drawing and export

`render.py` builds one `Scene` of primitives in world feet, and each backend
serialises that same scene — so the SVG, the PDF and the DXF cannot drift apart.

| Output | Notes |
|---|---|
| SVG | For the browser and the web UI; declares its true physical size. |
| PDF | Hand-written PDF 1.4 writer; the page is the sheet, at true scale. |
| PNG | Hand-written scanline rasteriser and PNG encoder, with a real DPI. |
| DXF | AutoCAD R12 ASCII, 1:1 in model space in feet, on named layers, linework only. |
| JSON | The full plan: rooms, rects, openings, score breakdown. |

The PNG backend exists because you cannot trust a drawing you have never looked
at. Numeric checks confirm a label sits at some coordinate; only an image shows
that two labels are on top of each other. Rasterising in pure Python means the
plan can be inspected anywhere, with no graphics stack installed, and it caught
two layout defects that every numeric test had passed.

It draws text with the single-stroke font in `font.py`, so letterforms differ
from the Helvetica used by SVG and PDF. Each glyph is advanced and squeezed to
its real Helvetica width, though, so a string covers exactly the span it will in
the real output — which is what makes the preview trustworthy for judging
whether a label fits its room.

Walls are centred on room boundaries, so the footprint outline is the exterior
wall centreline and a room's rect runs to the middle of its walls. The
dimensions printed inside each room are the net, inside-face figures.

## Layout

| Module | Role |
|---|---|
| `geometry.py` | Rects, segments, rectilinear polygons, decomposition |
| `spec.py` | Room catalog, adjacency preferences, the program |
| `plan.py` | Result types: placed rooms, openings, a scored plan |
| `layout.py` | The solver |
| `openings.py` | Doors and windows |
| `scoring.py` | Ranking plans against each other |
| `drawing.py` | Backend-independent scene primitives |
| `render.py` | Plan to scene: walls, swings, labels, dimensions, title block |
| `svg.py` `pdf.py` `dxf.py` `raster.py` | Scene to file |
| `metrics.py` | Helvetica character widths, for placing and fitting text |
| `units.py` | Imperial and metric conversion and formatting |
| `sheet.py` | Sheet sizes and architectural scales |
| `font.py` | Single-stroke vector font, used only by the rasteriser |
| `preview.py` | ASCII plan for the terminal |
| `api.py` | JSON request to spec, shared by the CLI and the server |
| `convert/model.py` | Entities with roles and provenance |
| `convert/readers/` | DXF (ezdxf), SVG (stdlib), PDF (pdfminer.six) |
| `convert/analyze.py` | Units, scale, classification, sheet furniture, quality grade |
| `convert/clean.py` | Dedupe, merge, snap |
| `convert/render.py` | Drawing to scene, inferred geometry dashed |
| `convert/report.py` `convert/pipeline.py` | The report and the one-call pipeline |
| `cli.py` `server.py` | Entry points |

## Tests

```bash
python3 -m unittest discover -s tests -t . -v
```

226 tests. The layout suite checks the invariants that matter across every
footprint, program and seed: rooms tile the footprint exactly, never overlap,
never come out with zero area, and the same seed always gives the same plan.
The circulation suite checks that every returned plan is fully reachable from
the front door and that no bathroom or closet is a through-route. The export
suite validates the PDF cross-reference table and stream lengths, DXF group-code
pairing, PNG chunk CRCs, and SVG well-formedness by parsing it.

The sheet suite checks the property the whole thing exists for: two differently
sized plans come out at the same points per foot, a small plan takes up less of
its sheet rather than being blown up, and a known 64 ft length measures exactly
16 inches on the page.

The converter suite ships no sample files: every fixture is a generated plan
exported by the package's own writers, read back, and required to yield what
the generator knew — wall extents to 5 cm, every door, every room label, the
declared units, and the printed scale. One test deletes the printed scale and
requires the calibration to recover it; another deletes the dimensions too and
requires the scale to be reported unknown rather than guessed.

The units suite checks that conversion happens at the boundary and nowhere else:
metric output carries no feet marks, imperial output carries no `m²`, and the
same seed lays out identically under either system.

The drawing tests are written to fail if their fix is reverted, which is worth
stating because the first versions of three of them did not: they grouped label
lines in a way that left the assertion unreached, and passed happily against
deliberately broken code. If you add one, break the thing it guards and watch it
fail before trusting it — and make the edit assert that it actually applied, or
a silently failed patch will look like a passing test.

## Known limitations

- **Rectilinear footprints only.** No curves or diagonals; a diagonal edge is
  rejected rather than approximated.
- **Single storey.** No stairs, no vertical circulation.
- **Guillotine slicing can't always satisfy every minimum.** On a tight
  program a bedroom can land a few percent under its target width when a single
  cut cannot serve both sides. The shortfall is shared deliberately, protecting
  the room with the harder constraint, and it is reported in the plan's score.
- **No fixtures.** Rooms are labelled boxes; there is no furniture, casework or
  plumbing layout.
- **Schematic only.** This is a massing and layout tool. It knows nothing about
  structure, egress, energy or your local code, and its output is not a
  construction document.
- **The readability check is mechanical.** It sees text boxes, wall fills
  and print size; it does not see a bed drawn through a door or a chain that
  crosses a north arrow. The PNG exists so the rest can be seen.
- **Word spacing in converted labels is a guess.** A PDF font with no space
  glyph hands over `KitchenLunchRoom`; the client and dimension plans put a
  space back before each capital or digit, and between the words of a short
  English/French room vocabulary (`Rentedspace` → `Rented space`). The
  technical plan keeps the source text as it was. A name outside that
  vocabulary stays joined.
- **Oblique walls come back stepped.** Hatch reconstruction works on a 5 cm
  grid, so a wall at an angle is a staircase of small rectangles, and rooms
  behind it are not always sealed for the label fill.
- **Open-plan labels stay put.** Where zones share one space, the fill finds
  the whole floor and the label is left where the source drew it.
- **The PDF has not been opened.** Its structure is validated — cross-reference
  offsets, stream lengths, escaping — its page size and scale are asserted, and
  it shares its geometry with the PNG, which has been looked at. But no PDF
  viewer was available to render it, so that is the one output whose appearance
  is inferred rather than seen.

## License

MIT.
