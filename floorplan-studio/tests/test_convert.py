"""The converter: readers, analyzer, cleaner and the end-to-end pipeline.

Every fixture is generated on the spot by the package's own exporters, so no
sample files ship with the tests and the round trip is exact: a plan goes out
as DXF, SVG and PDF, comes back through the readers, and the analyzer has to
recover what the generator knew — walls, doors, room names, units and scale.
"""

from __future__ import annotations

import json
import re
import struct
import tempfile
import unittest
from pathlib import Path

from floorplan import Polygon, PlanSpec, generate
from floorplan.convert.analyze import analyze
from floorplan.convert.clean import clean
from floorplan.convert.model import Drawing, Entity, Provenance, Role
from floorplan.dxf import DXF_ENCODING, render_dxf
from floorplan.pdf import render_pdf
from floorplan.render import build_scene
from floorplan.svg import render_svg

try:
    import ezdxf  # noqa: F401
    HAVE_EZDXF = True
except ImportError:  # pragma: no cover
    HAVE_EZDXF = False
try:
    import pdfminer  # noqa: F401
    HAVE_PDFMINER = True
except ImportError:  # pragma: no cover
    HAVE_PDFMINER = False

M = 3.280839895


class Fixture:
    """One generated plan, exported once per format into a temp dir."""

    _cache: dict = {}

    @classmethod
    def paths(cls) -> dict[str, Path]:
        if not cls._cache:
            spec = PlanSpec.from_program(Polygon.l_shape(17 * M, 12 * M, 6 * M, 4 * M),
                                         bedrooms=3, bathrooms=2, title="Round Trip")
            plan = generate(spec, variants=1)[0]
            scene = build_scene(plan)
            folder = Path(tempfile.mkdtemp(prefix="fp-fixture-"))
            (folder / "rt.dxf").write_text(render_dxf(scene), encoding=DXF_ENCODING)
            (folder / "rt.svg").write_text(render_svg(scene), encoding="utf-8")
            (folder / "rt.pdf").write_bytes(render_pdf(scene))
            cls._cache = {"dxf": folder / "rt.dxf", "svg": folder / "rt.svg", "pdf": folder / "rt.pdf",
                          "plan": plan, "scene": scene, "folder": folder}
        return cls._cache


def text_width_ft(label: str, t) -> float:
    from floorplan.metrics import text_width
    return text_width(label, t.size, t.bold)


def room_labels(plan) -> set[str]:
    return {r.label.upper() for r in plan.rooms}


# -- readers -------------------------------------------------------------------

@unittest.skipUnless(HAVE_EZDXF, "ezdxf not installed")
class DxfReaderTests(unittest.TestCase):
    def setUp(self):
        from floorplan.convert.readers.dxf import read_dxf
        self.drawing = read_dxf(Fixture.paths()["dxf"])

    def test_declared_units_are_verified(self):
        self.assertEqual(self.drawing.units, "ft")
        self.assertEqual(self.drawing.units_provenance, Provenance.VERIFIED)

    def test_layers_and_text_survive(self):
        self.assertIn("A-WALL", self.drawing.layers())
        texts = {e.text for e in self.drawing.texts()}
        self.assertTrue(room_labels(Fixture.paths()["plan"]) <= texts)

    def test_geometry_is_read(self):
        self.assertGreater(sum(1 for e in self.drawing.entities if e.kind == "line"), 200)


class SvgReaderTests(unittest.TestCase):
    def setUp(self):
        from floorplan.convert.readers.svg import read_svg
        self.drawing = read_svg(Fixture.paths()["svg"])

    def test_page_size_gives_paper_units(self):
        self.assertEqual(self.drawing.units, "svg")
        self.assertEqual(self.drawing.units_provenance, Provenance.VERIFIED)
        self.assertAlmostEqual(self.drawing.to_metres, 0.0254 / 72, places=6)  # points

    def test_y_axis_points_up(self):
        """SVG is y-down; the drawing must not be."""
        box = self.drawing.bounds()
        texts = self.drawing.texts()
        north = next(e for e in texts if e.text == "N")
        self.assertGreater(north.points[0][1], (box[1] + box[3]) / 2)  # the N sits near the top

    def test_filled_walls_are_flagged_filled(self):
        self.assertGreater(sum(1 for e in self.drawing.entities if e.filled), 50)

    def test_room_labels_are_read(self):
        self.assertTrue(room_labels(Fixture.paths()["plan"]) <= {e.text for e in self.drawing.texts()})

    def test_path_parser_handles_every_command(self):
        from floorplan.convert.readers.svg import _path
        subs = _path("M0 0 L10 0 l0 10 H0 V5 Z m20 0 a5 5 0 0 1 10 0 C40 0 40 10 30 10 q-5 0 -5 5 t-5 5 z")
        self.assertEqual(len(subs), 2)
        self.assertTrue(all(closed for _, closed in subs))
        end = _path("M0 0 A5 5 0 0 1 10 0")[0][0][-1]
        self.assertAlmostEqual(end[0], 10.0, places=6)
        self.assertAlmostEqual(end[1], 0.0, places=6)

    def test_transforms_compose(self):
        from floorplan.convert.readers.svg import _mul, _pt, _transform
        m = _transform("translate(10 20) scale(2) rotate(90)")
        x, y = _pt(m, 1, 0)
        self.assertAlmostEqual(x, 10, places=6)
        self.assertAlmostEqual(y, 22, places=6)
        self.assertEqual(_mul((1, 0, 0, 1, 0, 0), m), m)


@unittest.skipUnless(HAVE_PDFMINER, "pdfminer.six not installed")
class PdfReaderTests(unittest.TestCase):
    def setUp(self):
        from floorplan.convert.readers.pdf import read_pdf
        self.drawing = read_pdf(Fixture.paths()["pdf"])

    def test_page_matches_the_sheet_it_was_written_on(self):
        sheet = Fixture.paths()["scene"].sheet
        self.assertEqual(self.drawing.metadata["page_size_pt"], (sheet.width, sheet.height))
        self.assertEqual(self.drawing.sheets, 1)

    def test_printed_scale_is_read_as_verified(self):
        self.assertEqual(self.drawing.scale_label, Fixture.paths()["scene"].scale.label)
        self.assertEqual(self.drawing.scale_provenance, Provenance.VERIFIED)

    def test_room_labels_are_read(self):
        self.assertTrue(room_labels(Fixture.paths()["plan"]) <= {e.text for e in self.drawing.texts()})

    def test_rotated_text_keeps_its_height_and_place(self):
        """pdfminer reports a rotated glyph's advance as its size; we must not."""
        import math
        scene = Fixture.paths()["scene"]
        ppf, off_x, off_y = scene.placement()
        written = [t for t in scene.texts if t.rotate]
        self.assertGreater(len(written), 5)
        for t in written:
            candidates = [e for e in self.drawing.texts() if e.text == t.value and e.rotation]
            with self.subTest(text=t.value):
                self.assertTrue(candidates, "rotated label not read")
                # Page points -> world feet, then baseline start -> centre:
                # half the width along the baseline, half the height across it.
                def centre(e):
                    x, y = (e.points[0][0] - off_x) / ppf, (e.points[0][1] - off_y) / ppf
                    rad = math.radians(e.rotation)
                    half_w = text_width_ft(t.value, t) / 2
                    return (x + math.cos(rad) * half_w - math.sin(rad) * t.size * 0.5,
                            y + math.sin(rad) * half_w + math.cos(rad) * t.size * 0.5)
                e = min(candidates, key=lambda e: math.dist(centre(e), (t.x, t.y)))
                self.assertAlmostEqual(e.height / ppf, t.size, delta=t.size * 0.05)
                cx, cy = centre(e)
                self.assertAlmostEqual(cx, t.x, delta=0.3)
                self.assertAlmostEqual(cy, t.y, delta=0.3)

    def test_out_of_range_page_is_an_error(self):
        from floorplan.convert.readers.pdf import read_pdf
        with self.assertRaises(ValueError):
            read_pdf(Fixture.paths()["pdf"], page=2)


# -- analyzer ------------------------------------------------------------------

class AnalyzerTests(unittest.TestCase):
    @unittest.skipUnless(HAVE_EZDXF, "ezdxf not installed")
    def test_dxf_converts_declared_feet_to_metres(self):
        from floorplan.convert.readers.dxf import read_dxf
        d = analyze(clean(read_dxf(Fixture.paths()["dxf"])))
        self.assertEqual(d.units, "m")
        # The walls alone span the footprint plus half an exterior wall each side.
        walls = d.by_role(Role.WALL)
        xs = [x for e in walls for x, _ in e.points]
        ys = [y for e in walls for _, y in e.points]
        half = Fixture.paths()["plan"].spec.exterior_wall * 0.3048 / 2
        self.assertAlmostEqual(max(xs) - min(xs), 17 + 2 * half, delta=0.05)
        self.assertAlmostEqual(max(ys) - min(ys), 12 + 2 * half, delta=0.05)
        self.assertEqual(d.quality, "EXCELLENT")
        self.assertTrue(all(e.provenance == Provenance.VERIFIED for e in d.entities))

    def test_svg_scale_from_sheet_text_and_doors_from_geometry(self):
        from floorplan.convert.readers.svg import read_svg
        d = analyze(clean(read_svg(Fixture.paths()["svg"])))
        plan = Fixture.paths()["plan"]
        self.assertEqual(d.scale_label, Fixture.paths()["scene"].scale.label)
        self.assertEqual(d.scale_provenance, Provenance.VERIFIED)
        bw, bh = d.metadata["building_extent_m"]
        self.assertAlmostEqual(bw, 17.0, delta=0.4)
        self.assertAlmostEqual(bh, 12.0, delta=0.4)
        doors = d.by_role(Role.DOOR)
        swings = [o for o in plan.openings if o.kind in ("door", "entry")]
        self.assertEqual(len(doors), len(swings))
        self.assertTrue(all(e.provenance == Provenance.INFERRED for e in doors))
        self.assertGreater(len(d.by_role(Role.WALL)), 50)

    def test_scale_is_calculated_from_dimensions_when_not_printed(self):
        """Strip the printed scale; the tick-mark calibration must find it anyway."""
        from floorplan.convert.readers.svg import read_svg
        d = read_svg(Fixture.paths()["svg"])
        d.entities = [e for e in d.entities if not (e.kind == "text" and "SCALE" in (e.text or "").upper())]
        d = analyze(clean(d))
        self.assertEqual(d.scale_provenance, Provenance.CALCULATED)
        expected = Fixture.paths()["scene"].scale.ratio
        measured = float(d.scale_label.split(":")[1])
        self.assertAlmostEqual(measured, expected, delta=expected * 0.05)
        self.assertGreaterEqual(d.metadata["calibration_samples"], 3)

    def test_scale_stays_unknown_without_any_evidence(self):
        from floorplan.convert.readers.svg import read_svg
        d = read_svg(Fixture.paths()["svg"])
        d.entities = [e for e in d.entities if not (e.kind == "text" and (
            "SCALE" in (e.text or "").upper() or " m" in (e.text or "")))]
        d = analyze(clean(d))
        self.assertEqual(d.scale_provenance, Provenance.UNKNOWN)
        self.assertEqual(d.units, "paper")
        self.assertEqual(d.quality, "POOR")  # re-issuable, but only at paper size

    def test_only_pure_lengths_calibrate(self):
        """A ceiling height or a pod size is not a plan dimension."""
        from floorplan.convert.analyze import _is_pure_length
        for text in ("3.98 m", "12'-6\"", "3600", "1,20 m"):
            self.assertTrue(_is_pure_length(text), text)
        for text in ("ceil.height:2.48m", "1.00x1.05m", "11.88m2", "12", "150000", "REV 2"):
            self.assertFalse(_is_pure_length(text), text)

    def test_disagreeing_dimensions_do_not_make_a_scale(self):
        """Readings scattered over 80% are noise, and must leave the scale unknown."""
        from floorplan.convert.readers.svg import read_svg
        d = read_svg(Fixture.paths()["svg"])
        d.entities = [e for e in d.entities if not (e.kind == "text" and "SCALE" in (e.text or "").upper())]
        # Corrupt half the dimension strings so they no longer match their ticks.
        from floorplan.convert.analyze import _is_pure_length
        n = 0
        for e in d.entities:
            if e.kind == "text" and e.text and _is_pure_length(e.text):
                if n % 2 == 0:
                    e.text = f"{float(e.text[:-2]) * 3:.2f} m"
                n += 1
        d = analyze(clean(d))
        # The dimensions must not yield a scale. Room areas may still infer one,
        # and must say so; what is forbidden is a CALCULATED scale from noise.
        self.assertNotEqual(d.scale_provenance, Provenance.CALCULATED)
        self.assertNotIn("calculated from dimension strings", " ".join(d.notes))
        if d.scale_provenance == Provenance.INFERRED:
            self.assertIn("room-area", " ".join(d.notes))

    def test_layer_names_are_believed(self):
        d = Drawing(units="m", units_provenance=Provenance.VERIFIED, to_metres=1.0)
        d.entities = [Entity("line", [(0, 0), (5, 0)], layer="A-WALL"),
                      Entity("line", [(0, 0), (1, 0)], layer="MURS-EXT"),
                      Entity("arc", center=(0, 0), radius=0.9, start_angle=0, end_angle=90, layer="PORTES"),
                      Entity("line", [(0, 0), (1, 0)], layer="E-LIGHT"),
                      Entity("text", [(0, 0)], text="Cuisine", height=0.2, layer="TXT")]
        d = analyze(d)
        roles = [e.role for e in d.entities]
        self.assertEqual(roles[:3], [Role.WALL, Role.WALL, Role.DOOR])
        self.assertEqual(d.entities[-1].role, Role.TEXT)
        self.assertIn("electrical", d.metadata["disciplines"])

    def test_parallel_pairs_become_inferred_walls(self):
        d = Drawing(units="m", units_provenance=Provenance.VERIFIED, to_metres=1.0)
        d.entities = [Entity("line", [(0, 0), (6, 0)]), Entity("line", [(0, 0.2), (6, 0.2)]),
                      Entity("line", [(0, 3), (6, 3)]), Entity("line", [(0, 4.5), (6, 4.5)])]
        d = analyze(d)
        walls = d.by_role(Role.WALL)
        self.assertEqual(len(walls), 2)
        self.assertTrue(all(e.provenance == Provenance.INFERRED for e in walls))
        self.assertAlmostEqual(walls[0].thickness, 0.2, places=3)

    def test_bare_millimetre_dimensions_calibrate(self):
        """CAD writes "3600" for 3.6 m; that must calibrate like "3.60 m" does."""
        from floorplan.convert.readers.svg import read_svg
        d = read_svg(Fixture.paths()["svg"])
        for e in d.entities:
            if e.kind == "text" and "SCALE" in (e.text or "").upper():
                e.text = "REV A"
            elif e.kind == "text" and e.text and e.text.endswith(" m") and " x " not in e.text:
                e.text = str(int(round(float(e.text[:-2]) * 1000)))
        d = analyze(clean(d))
        self.assertEqual(d.scale_provenance, Provenance.CALCULATED)
        self.assertAlmostEqual(float(d.scale_label.split(":")[1]), Fixture.paths()["scene"].scale.ratio,
                               delta=Fixture.paths()["scene"].scale.ratio * 0.05)

    def test_thin_filled_polygon_is_a_wall_whatever_its_vertex_count(self):
        d = Drawing(units="m", units_provenance=Provenance.VERIFIED, to_metres=1.0)
        snake = [(0, 0), (8, 0), (8, 6), (7.8, 6), (7.8, 0.2), (0, 0.2)]  # an L-shaped wall run
        d.entities = [Entity("polyline", snake, closed=True, filled=True),
                      Entity("polyline", [(0, 3), (3, 3), (3, 6), (0, 6)], closed=True, filled=True),  # a slab
                      Entity("text", [(4, 3)], text="Kitchen", height=0.2)]
        d = analyze(d)
        self.assertEqual(d.entities[0].role, Role.WALL)
        self.assertAlmostEqual(d.entities[0].thickness, 0.2, delta=0.03)
        self.assertNotEqual(d.entities[1].role, Role.WALL)

    def test_walls_drawn_as_hatch_strokes_are_reconstructed(self):
        """A 0.2 m band of 45° hairlines 0.02 m apart is a wall, not 300 lines."""
        import math
        d = Drawing(units="m", units_provenance=Provenance.VERIFIED, to_metres=1.0)
        strokes = []
        x = 0.0
        while x < 6.0:  # a horizontal wall band from (0,0) to (6,0.2)
            strokes.append(Entity("line", [(x, 0.0), (min(x + 0.2, 6.0), min(0.2, 6.0 - x))]))
            x += 0.02
        d.entities = strokes + [Entity("text", [(3, 1.5)], text="Office", height=0.2),
                                Entity("line", [(0, 3), (6, 3)])]  # an ordinary line stays a line
        d = analyze(d)
        walls = [e for e in d.entities if e.role == Role.WALL and e.meta.get("hatch")]
        self.assertTrue(walls, "no wall region reconstructed from the hatching")
        xs = [p[0] for e in walls for p in e.points]; ys = [p[1] for e in walls for p in e.points]
        self.assertAlmostEqual(max(xs) - min(xs), 6.0, delta=0.15)
        self.assertAlmostEqual(max(ys) - min(ys), 0.2, delta=0.12)
        # analyze() returns a copy, so look the entities up in the result.
        consumed = [e for e in d.entities if e.kind == "line" and e.length < 0.5]
        self.assertTrue(consumed and all(e.meta.get("hatch_stroke") for e in consumed))
        plain = next(e for e in d.entities if e.kind == "line" and e.length > 5)
        self.assertNotEqual(plain.role, Role.WALL)

    def test_sparse_hatch_gives_a_solid_band_not_a_speckled_one(self):
        """Strokes far enough apart that some cells see only one of them
        still come back as one solid rectangle, not a band full of pinholes."""
        d = Drawing(units="m", units_provenance=Provenance.VERIFIED, to_metres=1.0)
        strokes = []
        x = 0.0
        while x < 6.0:  # 45° strokes 0.04 m apart on a 0.05 m grid: some cells
            strokes.append(Entity("line", [(x, 0.0), (x + 0.2, 0.2)]))   # see one stroke, some two
            x += 0.04
        d.entities = strokes + [Entity("text", [(3, 1.5)], text="Office", height=0.2)]
        d = analyze(d)
        walls = [e for e in d.entities if e.role == Role.WALL and e.meta.get("hatch")]
        self.assertTrue(walls, "no wall region reconstructed from the sparse hatching")
        area = sum(abs((e.points[2][0] - e.points[0][0]) * (e.points[2][1] - e.points[0][1])) for e in walls)
        self.assertGreater(area, 0.9 * 6.0 * 0.2, "the band has holes in it")
        self.assertLess(len(walls), 12, "the band came out as a pile of slivers")

    def test_door_swing_split_into_two_arcs_is_one_door_with_a_leaf(self):
        """A 90° swing exported as two 45° pieces on the same circle."""
        import math
        d = Drawing(units="m", units_provenance=Provenance.VERIFIED, to_metres=1.0)
        hinge, r = (5.0, 0.0), 0.9
        wall = [(0, -0.2), (10, -0.2), (10, 0), (0, 0)]   # the wall the door hangs in, below y=0
        d.entities = [Entity("polyline", wall, closed=True, filled=True)]
        for a0, a1 in ((0, 45), (45, 90)):
            pts = [(hinge[0] + r * math.cos(math.radians(a0 + (a1 - a0) * i / 8)),
                    hinge[1] + r * math.sin(math.radians(a0 + (a1 - a0) * i / 8))) for i in range(9)]
            d.entities.append(Entity("polyline", pts))
        d.entities.append(Entity("text", [(5, 3)], text="Office", height=0.2))
        d = analyze(d)
        doors = [e for e in d.entities if e.role == Role.DOOR]
        self.assertEqual(len(doors), 2, "both pieces belong to the door")
        leaves = [e.meta["leaf"] for e in doors if e.meta.get("leaf")]
        self.assertEqual(len(leaves), 1, "one leaf per swing")
        (hx, hy), (tx, ty) = leaves[0]
        self.assertAlmostEqual(hx, 5.0, delta=0.05); self.assertAlmostEqual(hy, 0.0, delta=0.05)
        self.assertAlmostEqual(ty, 0.9, delta=0.05, msg="the leaf goes to the end standing in the room")

    def test_lone_half_swing_hinged_on_a_wall_is_a_door(self):
        import math
        d = Drawing(units="m", units_provenance=Provenance.VERIFIED, to_metres=1.0)
        d.entities = [Entity("polyline", [(0, -0.2), (10, -0.2), (10, 0), (0, 0)], closed=True, filled=True),
                      Entity("text", [(5, 3)], text="Office", height=0.2)]
        for cx, cy in ((5.0, 0.0), (5.0, 3.0)):   # one on the wall, one floating in the room
            pts = [(cx + 0.9 * math.cos(math.radians(45 * i / 8)), cy + 0.9 * math.sin(math.radians(45 * i / 8)))
                   for i in range(9)]
            d.entities.append(Entity("polyline", pts))
        d = analyze(d)
        doors = [e for e in d.entities if e.role == Role.DOOR]
        self.assertEqual(len(doors), 1)
        self.assertAlmostEqual(doors[0].center[1], 0.0, delta=0.05)

    def test_window_read_from_a_line_bridging_a_gap_in_the_wall(self):
        """Wall stops, one thin line closes the opening, wall resumes."""
        d = Drawing(units="m", units_provenance=Provenance.VERIFIED, to_metres=1.0)
        d.entities = [Entity("polyline", [(0, 0), (4, 0), (4, 0.2), (0, 0.2)], closed=True, filled=True),
                      Entity("polyline", [(5.5, 0), (10, 0), (10, 0.2), (5.5, 0.2)], closed=True, filled=True),
                      Entity("line", [(4, 0.1), (5.5, 0.1)]),
                      Entity("line", [(4, 3), (5.5, 3)]),   # same length, not in the wall: not a window
                      Entity("text", [(5, 2)], text="Office", height=0.2)]
        d = analyze(d)
        symbols = [e for e in d.entities if e.role == Role.WINDOW and e.meta.get("symbol")]
        self.assertEqual(len(symbols), 1)
        self.assertAlmostEqual(symbols[0].points[0][0], 4.0, delta=0.02)
        self.assertAlmostEqual(symbols[0].points[1][0], 5.5, delta=0.02)
        self.assertAlmostEqual(symbols[0].thickness, 0.2, delta=0.02)
        self.assertTrue(d.entities[2].meta.get("glazing"))
        self.assertNotEqual(d.entities[3].role, Role.WINDOW)

    def test_windows_join_wall_runs_so_neither_side_is_pruned(self):
        """Two wall bodies linked only by a window are one building."""
        d = Drawing(units="m", units_provenance=Provenance.VERIFIED, to_metres=1.0)
        left = [Entity("polyline", [(0, 0), (4, 0), (4, 0.2), (0, 0.2)], closed=True, filled=True),
                Entity("polyline", [(0, 0), (0.2, 0), (0.2, 4), (0, 4)], closed=True, filled=True)]
        right = [Entity("polyline", [(5.5, 0), (10, 0), (10, 0.2), (5.5, 0.2)], closed=True, filled=True),
                 Entity("polyline", [(9.8, 0), (10, 0), (10, 4), (9.8, 4)], closed=True, filled=True)]
        d.entities = left + right + [Entity("line", [(4, 0.1), (5.5, 0.1)]),
                                     Entity("text", [(1, 2)], text="Office", height=0.2),
                                     Entity("text", [(1.2, 1.7)], text="12.00m2", height=0.2)]
        d = analyze(d)
        self.assertEqual([e.role for e in d.entities[:4]], [Role.WALL] * 4)

    def test_windows_inferred_from_glazing_lines_in_a_wall(self):
        d = Drawing(units="m", units_provenance=Provenance.VERIFIED, to_metres=1.0)
        wall = [(0, 0), (10, 0), (10, 0.25), (0, 0.25)]
        d.entities = [Entity("polyline", wall, closed=True, filled=True),
                      Entity("line", [(3, 0.08), (4.2, 0.08)]),   # glazing pair in the wall
                      Entity("line", [(3, 0.17), (4.2, 0.17)]),
                      Entity("line", [(6, 3.0), (7.2, 3.0)]),     # a pair out in the room: furniture
                      Entity("line", [(6, 3.1), (7.2, 3.1)]),
                      Entity("text", [(5, 2)], text="Office", height=0.2)]
        d = analyze(d)
        windows = d.by_role(Role.WINDOW)
        self.assertEqual(len(windows), 2)
        self.assertTrue(all(e.points[0][1] < 0.25 for e in windows))

    def test_sheet_type_is_inferred_from_its_words(self):
        for words, expected in ((["Living 18.4 m²"], "plan"), (["Elevation A-A"], "elevation/section"),
                                (["Door schedule", "lever handle"], "schedule")):
            d = Drawing(units="m", units_provenance=Provenance.VERIFIED, to_metres=1.0)
            d.entities = [Entity("line", [(0, 0), (5, 0)])] + [
                Entity("text", [(1, 1)], text=w, height=0.2) for w in words]
            with self.subTest(words=words):
                self.assertEqual(analyze(d).metadata["sheet_type"], expected)

    def test_units_inferred_from_magnitude(self):
        d = Drawing(units=None)
        d.entities = [Entity("line", [(0, 0), (15000, 0)]), Entity("line", [(0, 0), (0, 9000)])]
        d = analyze(d)
        self.assertEqual(d.units, "m")
        self.assertEqual(d.units_provenance, Provenance.INFERRED)
        self.assertAlmostEqual(d.metadata["extent_m"][0], 15.0, places=3)

    def test_empty_drawing_is_unusable(self):
        self.assertEqual(analyze(Drawing()).quality, "UNUSABLE")


class CleanerTests(unittest.TestCase):
    def test_noise_duplicates_snapping_and_merging(self):
        d = Drawing(units="m", to_metres=1.0)
        d.entities = [Entity("line", [(0, 0), (2, 0)]), Entity("line", [(2, 0), (5, 0)]),
                      Entity("line", [(5, 0.001), (9, 0)]), Entity("line", [(0, 0), (2, 0)]),
                      Entity("line", [(0, 0), (0, 0)]), Entity("line", [(0, 5), (6, 5.08)]),
                      Entity("text", [(0, 0)], text="   ")]
        clean(d)
        lines = [e for e in d.entities if e.kind == "line"]
        self.assertEqual(len(lines), 2)
        long = max(lines, key=lambda e: e.length)
        self.assertAlmostEqual(long.length, 9.0, places=6)
        self.assertEqual(long.points[0][1], long.points[1][1])  # snapped flat
        self.assertEqual(len(d.notes), 4)

    def test_cleaning_never_touches_text_content(self):
        d = Drawing(units="m", to_metres=1.0)
        d.entities = [Entity("text", [(1, 1)], text="Living  Room", height=0.2)]
        clean(d)
        self.assertEqual(d.entities[0].text, "Living  Room")


# -- pipeline ------------------------------------------------------------------

@unittest.skipUnless(HAVE_EZDXF and HAVE_PDFMINER, "converter dependencies not installed")
class PipelineTests(unittest.TestCase):
    def test_every_source_format_round_trips_to_every_output(self):
        from floorplan.convert.pipeline import convert_file
        out = Path(tempfile.mkdtemp(prefix="fp-conv-"))
        for fmt in ("dxf", "svg", "pdf"):
            with self.subTest(source=fmt):
                report = convert_file(Fixture.paths()[fmt], formats=("pdf", "dxf", "svg", "png"), out_dir=out)
                self.assertEqual(report["reconstruction_performed"], "YES")
                expected = {f"{lvl}_{f}" for lvl in ("client", "dimension", "technical")
                            for f in ("pdf", "dxf", "svg", "png")} | {"report_md", "report_json"}
                self.assertEqual(set(report["outputs"]), expected)
                pdf = Path(report["outputs"]["client_pdf"]).read_bytes()
                self.assertTrue(pdf.startswith(b"%PDF") and pdf.rstrip().endswith(b"%%EOF"))
                dxf = Path(report["outputs"]["technical_dxf"]).read_text(encoding=DXF_ENCODING)
                self.assertIn("A-WALL", dxf)
                self.assertEqual(dxf.splitlines()[-1], "EOF")
                png = Path(report["outputs"]["client_png"]).read_bytes()
                self.assertTrue(png.startswith(b"\x89PNG"))
                loaded = json.loads(Path(report["outputs"]["report_json"]).read_text())
                for key in ("source_quality", "detected_scale", "detected_units", "verified_elements",
                            "inferred_elements", "unknown_elements", "warnings"):
                    self.assertIn(key, loaded)

    def test_report_markdown_has_the_required_sections(self):
        from floorplan.convert.pipeline import convert_file
        out = Path(tempfile.mkdtemp(prefix="fp-conv-"))
        report = convert_file(Fixture.paths()["svg"], formats=("svg",), out_dir=out, levels=["client"])
        md = Path(report["outputs"]["report_md"]).read_text()
        for heading in ("Source file", "Source quality", "Detected discipline", "Detected scale",
                        "Detected units", "Output format", "Reconstruction performed",
                        "Verified elements", "Inferred elements", "Unknown elements", "Warnings"):
            self.assertIn(heading, md)

    def test_inferred_geometry_is_drawn_dashed(self):
        from floorplan.convert.readers.svg import read_svg
        from floorplan.convert.render import build_drawing_scene
        d = analyze(clean(read_svg(Fixture.paths()["svg"])))
        scene = build_drawing_scene(d, level="technical")
        doors = [p for p in scene.paths if p.layer == "A-DOOR" and p.stroke]
        self.assertTrue(doors)
        self.assertTrue(all(p.dash for p in doors), "inferred doors must be dashed")

    def test_client_plan_hides_provenance_and_clutter(self):
        """Presentation drawing: no AI vocabulary, no dashed inference, no ceiling heights."""
        from floorplan.convert.readers.svg import read_svg
        from floorplan.convert.render import build_drawing_scene
        d = analyze(clean(read_svg(Fixture.paths()["svg"])))
        client = build_drawing_scene(d, level="client")
        words = " ".join(t.value for t in client.texts).upper()
        for banned in ("INFERRED", "VERIFIED", "CALCULATED", "UNKNOWN", "QUALITY"):
            self.assertNotIn(banned, words)
        self.assertIn("FLOOR PLAN", words)
        self.assertIn("A-101", words)
        self.assertFalse(any(p.dash for p in client.paths), "nothing is dashed on the client plan")
        technical = build_drawing_scene(d, level="technical")
        self.assertIn("INFERRED", " ".join(t.value for t in technical.texts).upper())
        self.assertLess(len(client.items), len(technical.items))

    def test_client_plan_keeps_room_labels_and_drops_captions(self):
        """A room label is a name stacked over an area. A caption with no area
        under it — a furniture tag, a "to be precised" note — is not a room."""
        from floorplan.convert.render import display_text, room_labels
        name = Entity("text", [(4.0, 3.0)], text="KitchenLunchRoom", height=0.28, role=Role.TEXT)
        area = Entity("text", [(4.6, 2.65)], text="40.09m2", height=0.19, role=Role.TEXT)
        ceiling = Entity("text", [(4.5, 2.35)], text="ceil.height:2.48m", height=0.19, role=Role.TEXT)
        pod = Entity("text", [(9.0, 3.0)], text="OfficePod", height=0.16, role=Role.TEXT)
        pod2 = Entity("text", [(9.0, 2.8)], text="for1p.", height=0.16, role=Role.TEXT)
        note = Entity("text", [(1.0, 6.0)], text="TOBEPRECISED", height=0.28, role=Role.TEXT)
        far = Entity("text", [(4.0, 5.0)], text="Office", height=0.28, role=Role.TEXT)  # 2 m above
        kept = room_labels([name, area, ceiling, pod, pod2, note, far])
        self.assertEqual(kept, {id(name), id(area)})
        self.assertEqual(display_text("KitchenLunchRoom"), "Kitchen Lunch Room")
        self.assertEqual(display_text("Meetingroom1"), "Meeting room 1")
        self.assertEqual(display_text("40.09m2"), "40.09m2")           # the 2 of m2 stays put
        self.assertEqual(display_text("Salle de bain"), "Salle de bain")  # already spaced

    def test_converted_plan_draws_door_leaf_window_symbol_and_own_chains(self):
        import math
        from floorplan.convert.render import build_drawing_scene, exterior_chains
        from floorplan.render import GLASS
        d = Drawing(units="m", units_provenance=Provenance.VERIFIED, to_metres=1.0)
        d.entities = [Entity("polyline", [(0, 0), (4, 0), (4, 0.2), (0, 0.2)], closed=True, filled=True),
                      Entity("polyline", [(5.5, 0), (12, 0), (12, 0.2), (5.5, 0.2)], closed=True, filled=True),
                      Entity("polyline", [(0, 0), (0.2, 0), (0.2, 8), (0, 8)], closed=True, filled=True),
                      Entity("polyline", [(0, 7.8), (12, 7.8), (12, 8), (0, 8)], closed=True, filled=True),
                      Entity("polyline", [(11.8, 0), (12, 0), (12, 8), (11.8, 8)], closed=True, filled=True),
                      Entity("polyline", [(6, 0.2), (6.2, 0.2), (6.2, 7.8), (6, 7.8)], closed=True, filled=True),
                      Entity("line", [(4, 0.1), (5.5, 0.1)]),
                      Entity("text", [(2, 4)], text="Office", height=0.25),
                      Entity("text", [(2, 3.6)], text="44.00m2", height=0.25)]
        hinge = (8.0, 7.8)
        d.entities.append(Entity("polyline", [(hinge[0] + 0.9 * math.cos(math.radians(180 + 90 * i / 12)),
                                               hinge[1] + 0.9 * math.sin(math.radians(180 + 90 * i / 12)))
                                              for i in range(13)]))
        d = analyze(d)
        self.assertEqual(len([e for e in d.entities if e.role == Role.DOOR]), 1)
        south, west = exterior_chains(d)
        self.assertAlmostEqual(south[0], 0.0, delta=0.05); self.assertAlmostEqual(south[-1], 12.0, delta=0.05)
        self.assertTrue(any(abs(m - 4.0) < 0.05 for m in south) and any(abs(m - 5.5) < 0.05 for m in south),
                        "the window's ends are marks on the south chain")
        self.assertTrue(any(abs(m - 6.1) < 0.1 for m in south), "the partition is a bay mark")
        scene = build_drawing_scene(d, level="client")
        glazing = [p for p in scene.paths if p.stroke == GLASS and p.layer == "A-WIND"]
        self.assertEqual(len(glazing), 2, "a window is two glazing lines")
        leaves = [p for p in scene.paths if p.layer == "A-DOOR" and len(p.points) == 2]
        self.assertEqual(len(leaves), 1, "the door has its leaf")
        chain_texts = [t for t in scene.texts if t.layer == "A-DIMS"]
        self.assertTrue(any("12.00 m" in t.value for t in chain_texts), "the overall run is dimensioned")
        self.assertTrue(all(t.y < 0 or t.x < 0 for t in chain_texts), "chains sit outside the building")
        title = [t for t in scene.texts if t.layer == "G-ANNO" and "FLOOR PLAN" in t.value]
        self.assertTrue(title and title[0].y < min(t.y for t in chain_texts), "the title block is below the chains")

    def test_room_label_is_recentred_in_its_room_when_the_area_agrees(self):
        from floorplan.convert.render import label_stacks, recentre_labels
        d = Drawing(units="m", units_provenance=Provenance.VERIFIED, to_metres=1.0)
        shell = [Entity("polyline", [(0, 0), (8, 0), (8, 0.2), (0, 0.2)], closed=True, filled=True),
                 Entity("polyline", [(0, 5.8), (8, 5.8), (8, 6), (0, 6)], closed=True, filled=True),
                 Entity("polyline", [(0, 0), (0.2, 0), (0.2, 6), (0, 6)], closed=True, filled=True),
                 Entity("polyline", [(7.8, 0), (8, 0), (8, 6), (7.8, 6)], closed=True, filled=True),
                 Entity("polyline", [(3.9, 0), (4.1, 0), (4.1, 6), (3.9, 6)], closed=True, filled=True)]
        for e in shell:
            e.role, e.provenance = Role.WALL, Provenance.VERIFIED
        # Left room 3.7 x 5.6 = 20.7 m²; its label sits in a corner. Right room's label lies.
        left = [Entity("text", [(0.5, 5.0)], text="Office", height=0.25, role=Role.TEXT),
                Entity("text", [(0.5, 4.6)], text="20.70m2", height=0.25, role=Role.TEXT)]
        right = [Entity("text", [(6, 3)], text="Store", height=0.25, role=Role.TEXT),
                 Entity("text", [(6, 2.6)], text="80.00m2", height=0.25, role=Role.TEXT)]
        d.entities = shell + left + right
        stacks = label_stacks(left + right)
        moved = recentre_labels(d, stacks)
        self.assertIn(id(left[1]), moved)
        self.assertNotIn(id(right[1]), moved, "an area that disagrees with the room is not trusted")
        nx, ny = moved[id(left[0])]
        # The stack's centre lands on the room's centre (2.05, 3.0); the name
        # line keeps its offset above the area line.
        self.assertAlmostEqual(nx + 0.55 * 0.25 * len("Office") / 2, 2.05, delta=0.15)
        self.assertAlmostEqual(ny, 3.0 + 0.2 - 0.125, delta=0.15)
        self.assertAlmostEqual(moved[id(left[0])][1] - moved[id(left[1])][1], 0.4, delta=1e-6)

    def test_display_text_restores_word_breaks_from_the_word_list(self):
        from floorplan.convert.render import display_text
        self.assertEqual(display_text("Rentedspace2"), "Rented space 2")
        self.assertEqual(display_text("Restingroom"), "Resting room")
        self.assertEqual(display_text("Co-workingspace3"), "Co-working space 3")
        self.assertEqual(display_text("Hallway"), "Hallway")
        self.assertEqual(display_text("Xyzzyplugh"), "Xyzzyplugh")   # not words: left alone

    def test_text_is_never_printed_smaller_than_two_millimetres(self):
        """The source's 1 mm dimension figures are printed at a size a reader
        can make out at the chosen scale."""
        from floorplan.convert.render import build_drawing_scene
        from floorplan.units import FEET_PER_METRE
        d = Drawing(units="m", units_provenance=Provenance.VERIFIED, to_metres=1.0)
        d.entities = [Entity("polyline", [(0, 0), (12, 0), (12, 0.25), (0, 0.25)], closed=True, filled=True),
                      Entity("polyline", [(0, 8), (12, 8), (12, 8.25), (0, 8.25)], closed=True, filled=True),
                      Entity("text", [(6, 4)], text="Office", height=0.25),
                      Entity("text", [(6, 3.6)], text="40.00m2", height=0.25),
                      Entity("text", [(6, 1)], text="2497", height=0.05, role=Role.DIMENSION)]
        d = analyze(d)
        scene = build_drawing_scene(d, level="dimension")
        dim = next(t for t in scene.texts if t.value == "2497")
        paper_mm = dim.size / FEET_PER_METRE / scene.scale.ratio * 1000.0
        self.assertGreaterEqual(paper_mm, 1.99)

    def test_source_sheet_furniture_is_not_redrawn(self):
        """One title block, one north arrow, one scale bar: ours, not the source's."""
        from floorplan.convert.readers.svg import read_svg
        from floorplan.convert.render import build_drawing_scene
        d = analyze(clean(read_svg(Fixture.paths()["svg"])))
        self.assertGreater(len(d.by_role(Role.SHEET)), 10)
        scene = build_drawing_scene(d)
        norths = [t for t in scene.texts if t.value == "N"]
        scales = [t for t in scene.texts if t.value.startswith("SCALE")]
        self.assertEqual(len(norths), 1)
        self.assertEqual(len(scales), 1)
        # Without the old furniture the drawing fits the sheet it came from.
        self.assertEqual(scene.sheet.name, Fixture.paths()["scene"].sheet.name)

    def test_unsupported_sources_are_refused_with_advice(self):
        from floorplan.convert.pipeline import UnsupportedSource, read
        folder = Path(tempfile.mkdtemp(prefix="fp-bad-"))
        for name, hint in (("plan.dwg", "DXF"), ("scan.png", "raster"), ("model.rvt", "DXF")):
            (folder / name).write_bytes(b"")
            with self.subTest(file=name):
                with self.assertRaises(UnsupportedSource) as caught:
                    read(folder / name)
                self.assertIn(hint, str(caught.exception))

    def test_bad_output_format_is_rejected(self):
        from floorplan.convert.pipeline import convert_file
        with self.assertRaises(ValueError):
            convert_file(Fixture.paths()["svg"], formats=("dwg",))


@unittest.skipUnless(HAVE_EZDXF and HAVE_PDFMINER, "converter dependencies not installed")
class ServerConvertTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import threading
        from http.server import ThreadingHTTPServer
        from floorplan.server import Handler
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.httpd.quiet = True
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def upload(self, name: str, payload: bytes, fields: dict | None = None):
        import urllib.error
        import urllib.request
        boundary = "----floorplanTestBoundary"
        body = b""
        for key, value in (fields or {}).items():
            body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n").encode()
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
                 "Content-Type: application/octet-stream\r\n\r\n").encode() + payload + f"\r\n--{boundary}--\r\n".encode()
        request = urllib.request.Request(self.base + "/api/convert", data=body, headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_upload_converts_and_serves_downloads(self):
        import urllib.request
        status, data = self.upload("rt.svg", Fixture.paths()["svg"].read_bytes(), {"formats": "pdf,dxf,svg"})
        self.assertEqual(status, 200, data)
        self.assertEqual(data["report"]["source_quality"], "GOOD")
        self.assertTrue(data["svg"].startswith("<svg"))
        self.assertTrue({"client_pdf", "technical_dxf", "dimension_svg", "report_md", "report_json"} <= set(data["downloads"]))
        with urllib.request.urlopen(self.base + data["downloads"]["client_pdf"], timeout=30) as response:
            self.assertEqual(response.status, 200)
            self.assertTrue(response.read().startswith(b"%PDF"))
            self.assertIn("attachment", response.headers["Content-Disposition"])

    def test_unsupported_upload_is_a_clean_400(self):
        status, data = self.upload("plan.dwg", b"AC1027 not really", {})
        self.assertEqual(status, 400)
        self.assertIn("dxf", data["error"])

    def test_download_token_cannot_traverse(self):
        import urllib.error
        import urllib.request
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self.base + "/api/converted/nope/../../etc/passwd", timeout=10)
        self.assertIn(caught.exception.code, (400, 404))


if __name__ == "__main__":
    unittest.main()
