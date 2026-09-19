# floorplan-studio

Generate residential floor plans from a footprint outline and a room program.
You give it a shape and a list of rooms; it returns dimensioned, connected
plans with doors and windows.

**Status: work in progress.** The generator works end to end in Python. The
export backends, the web UI and the test suite are not written yet — see
[Not done yet](#not-done-yet).

No third-party dependencies. Python 3.10+.

## Try it

```python
from floorplan.geometry import Polygon
from floorplan.spec import PlanSpec
from floorplan.layout import generate

spec = PlanSpec.from_program(
    Polygon.rectangle(48, 32), bedrooms=3, bathrooms=2, title="Maple St"
)
for plan in generate(spec, variants=3):
    print(plan.summary())
    for room in plan.rooms:
        print(f"  {room.label:18s} {room.rect.w:5.1f} x {room.rect.h:5.1f}")
```

Footprints can be a `rectangle`, `l_shape`, `t_shape` or `u_shape`, or any
rectilinear `Polygon` you pass vertices for.

## How it generates a plan

There is no trained model here, and it does not need one. A floor plan is a
constraint problem, and solving it directly is both faster and reproducible —
the same seed always gives the same plan.

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
   front door, then add windows on exterior walls.
7. **Score** the result, and keep the best plans that are not near-duplicates.

Two details do most of the work for plan quality:

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

Doors come from a spanning tree rather than "connect everything that touches",
so circulation is deliberate. Bathrooms, closets and the garage are forced to
be leaves of that tree — you never walk through a bathroom to reach a bedroom.

## Layout

| Module | Role |
|---|---|
| `geometry.py` | Rects, segments, rectilinear polygons, decomposition |
| `spec.py` | Room catalog, adjacency preferences, the program |
| `plan.py` | Result types: placed rooms, openings, a scored plan |
| `layout.py` | The solver |
| `openings.py` | Doors and windows |
| `scoring.py` | Ranking plans against each other |

## Not done yet

- `render.py` / `svg.py` / `pdf.py` / `dxf.py` — drawing the plan. The intent
  is one scene of primitives in world feet, serialised by each backend, so
  SVG, PDF and CAD output cannot drift apart.
- `server.py` and the browser UI for drawing a footprint and picking rooms.
- `cli.py`.
- The test suite. The solver has only been exercised by hand so far.

## License

MIT.
