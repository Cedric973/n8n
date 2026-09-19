# floorplan-studio

Generate residential floor plans from a footprint outline and a room program.
Draw a shape, say how many bedrooms you want, and get back dimensioned,
connected plans with doors and windows — as SVG, PDF or CAD-ready DXF.

No third-party dependencies at all. Python 3.10+, standard library only.

```bash
python3 -m floorplan.server          # web UI on http://127.0.0.1:8000
python3 -m floorplan.cli --preview   # or straight to files
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
    --shape l --width 56 --depth 40 \
    --bedrooms 4 --bathrooms 3 --garage --mudroom \
    --title "Cedar Ridge" --variants 3 \
    --out plans --formats svg,pdf,dxf --preview
```

`--preview` prints an ASCII plan per variant, which is the fastest way to see
whether a layout is sensible without opening anything. `--spec request.json`
takes the same JSON body the HTTP API accepts.

## As a library

```python
from floorplan import Polygon, PlanSpec, generate
from floorplan.render import build_scene
from floorplan.svg import render_svg

spec = PlanSpec.from_program(
    Polygon.rectangle(48, 32), bedrooms=3, bathrooms=2, title="Maple St"
)
best = generate(spec, variants=3)[0]
print(best.summary())
open("plan.svg", "w").write(render_svg(build_scene(best)))
```

Footprints can be `rectangle`, `l_shape`, `t_shape`, `u_shape`, or any
rectilinear `Polygon` you pass vertices for. Room types, target areas, minimum
dimensions and adjacency preferences all live in `spec.py` and are meant to be
edited.

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
| SVG | For the browser and the web UI. |
| PDF | Hand-written PDF 1.4 writer, Helvetica metrics included for correct text centring. |
| DXF | AutoCAD R12 ASCII, 1:1 in model space in feet, on named layers, linework only. |
| JSON | The full plan: rooms, rects, openings, score breakdown. |

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
| `svg.py` `pdf.py` `dxf.py` | Scene to file |
| `preview.py` | ASCII plan for the terminal |
| `api.py` | JSON request to spec, shared by the CLI and the server |
| `cli.py` `server.py` | Entry points |

## Tests

```bash
python3 -m unittest discover -s tests -t . -v
```

92 tests. The layout suite checks the invariants that matter across every
footprint, program and seed: rooms tile the footprint exactly, never overlap,
never come out with zero area, and the same seed always gives the same plan.
The circulation suite checks that every returned plan is fully reachable from
the front door and that no bathroom or closet is a through-route. The export
suite validates the PDF cross-reference table and stream lengths, DXF group-code
pairing, and SVG well-formedness by parsing it.

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

## License

MIT.
