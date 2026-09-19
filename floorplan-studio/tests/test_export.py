"""The three export backends must all describe the same scene, validly."""

import re
import unittest
import xml.dom.minidom

from floorplan import Polygon, PlanSpec, RoomSpec, generate
from floorplan.drawing import Scene, hex_to_rgb
from floorplan.dxf import SKIP_LAYERS, render_dxf
from floorplan.geometry import Rect
from floorplan.metrics import text_width
from floorplan.pdf import render_pdf
from floorplan.raster import Canvas, render_png
from floorplan.preview import ascii_plan
from floorplan.render import FACES, _edge_divisions, _fit, build_scene
from floorplan.svg import render_svg


def sample_plan(**kwargs):
    spec = PlanSpec.from_program(
        Polygon.l_shape(56, 40, 18, 14), bedrooms=4, bathrooms=3,
        garage=True, title="Export Test", **kwargs
    )
    return generate(spec, variants=1)[0]


class SceneTests(unittest.TestCase):
    def setUp(self):
        self.scene = build_scene(sample_plan())

    def test_scene_contains_geometry_and_labels(self):
        self.assertGreater(len(self.scene.paths), 50)
        self.assertGreater(len(self.scene.texts), 10)

    def test_scene_is_larger_than_the_footprint(self):
        """There must be margin for dimensions and the title block."""
        plan = sample_plan()
        bounds = plan.footprint.bounds
        self.assertLess(self.scene.bounds.x, bounds.x)
        self.assertLess(self.scene.bounds.y, bounds.y)
        self.assertGreater(self.scene.bounds.w, bounds.w)

    def test_expected_layers_are_present(self):
        self.assertLessEqual(
            {"FLOOR", "WALLS", "DOORS", "TEXT", "SHEET"}, set(self.scene.layers())
        )

    def test_dimensions_can_be_suppressed(self):
        plain = build_scene(sample_plan(), show_dimensions=False)
        self.assertNotIn("DIMS", plain.layers())

    def test_hex_parsing(self):
        self.assertEqual(hex_to_rgb("#ffffff"), (1.0, 1.0, 1.0))
        self.assertEqual(hex_to_rgb("#000"), (0.0, 0.0, 0.0))


class DimensionTests(unittest.TestCase):
    """A plan must be dimensioned from every face, not just two of them."""

    def setUp(self):
        self.plan = sample_plan()

    def test_all_four_faces_are_dimensioned(self):
        for name, along_x, far in FACES:
            with self.subTest(face=name):
                self.assertGreaterEqual(len(_edge_divisions(self.plan, along_x, far)), 2)

    def test_runs_sum_to_the_span(self):
        for name, along_x, far in FACES:
            divisions = _edge_divisions(self.plan, along_x, far)
            runs = sum(b - a for a, b in zip(divisions, divisions[1:]))
            with self.subTest(face=name):
                self.assertAlmostEqual(runs, divisions[-1] - divisions[0], places=6)

    def test_no_degenerate_runs(self):
        for footprint in (Polygon.rectangle(48, 32), Polygon.l_shape(56, 40, 18, 14),
                          Polygon.u_shape(54, 38, 16, 12)):
            spec = PlanSpec.from_program(footprint, bedrooms=3, bathrooms=2)
            for plan in generate(spec, variants=2):
                for name, along_x, far in FACES:
                    divisions = _edge_divisions(plan, along_x, far)
                    for a, b in zip(divisions, divisions[1:]):
                        with self.subTest(face=name):
                            self.assertGreaterEqual(b - a, 0.25)

    def test_far_faces_span_only_what_exists(self):
        """On an L-shape the north and east faces are shorter than the bounding box."""
        spec = PlanSpec.from_program(Polygon.l_shape(56, 40, 18, 14), bedrooms=3, bathrooms=2)
        plan = generate(spec, variants=1)[0]
        bounds = plan.footprint.bounds
        north = _edge_divisions(plan, True, True)
        east = _edge_divisions(plan, False, True)
        self.assertLess(north[-1] - north[0], bounds.w - 1)
        self.assertLess(east[-1] - east[0], bounds.h - 1)

    def test_near_faces_span_the_whole_building(self):
        bounds = self.plan.footprint.bounds
        south = _edge_divisions(self.plan, True, False)
        west = _edge_divisions(self.plan, False, False)
        self.assertAlmostEqual(south[-1] - south[0], bounds.w, places=4)
        self.assertAlmostEqual(west[-1] - west[0], bounds.h, places=4)

    def test_scene_leaves_room_for_every_chain(self):
        scene = build_scene(self.plan)
        bounds = self.plan.footprint.bounds
        dims = [i for i in scene.items if i.layer == "DIMS"]
        self.assertGreater(len(dims), 20)
        for item in dims:
            points = item.points if hasattr(item, "points") else [(item.x, item.y)]
            for x, y in points:
                self.assertGreaterEqual(x, scene.bounds.x)
                self.assertLessEqual(x, scene.bounds.x2)
                self.assertGreaterEqual(y, scene.bounds.y)
                self.assertLessEqual(y, scene.bounds.y2)

    def test_north_arrow_clears_the_east_chain(self):
        scene = build_scene(self.plan)
        bounds = self.plan.footprint.bounds
        east = [i for i in scene.items if i.layer == "DIMS"
                and getattr(i, "points", None) and i.points[0][0] > bounds.x2]
        arrow = [i for i in scene.items if i.layer == "SHEET"
                 and getattr(i, "points", None) and i.points[0][0] > bounds.x2]
        self.assertTrue(east and arrow)
        furthest_dim = max(x for i in east for x, _ in i.points)
        nearest_arrow = min(x for i in arrow for x, _ in i.points)
        self.assertGreater(nearest_arrow, furthest_dim)


class SvgTests(unittest.TestCase):
    def setUp(self):
        self.svg = render_svg(build_scene(sample_plan()))

    def test_is_well_formed_xml(self):
        xml.dom.minidom.parseString(self.svg)

    def test_declares_size_and_viewbox(self):
        self.assertIn("viewBox=", self.svg)
        self.assertTrue(self.svg.startswith("<svg"))
        self.assertTrue(self.svg.rstrip().endswith("</svg>"))

    def test_escapes_text(self):
        spec = PlanSpec.from_program(Polygon.rectangle(40, 30), bedrooms=2, bathrooms=1,
                                     title='Ampersand & "quotes" <tag>')
        svg = render_svg(build_scene(generate(spec, variants=1)[0]))
        xml.dom.minidom.parseString(svg)
        self.assertIn("&amp;", svg)
        self.assertNotIn("<tag>", svg)


class PdfTests(unittest.TestCase):
    def setUp(self):
        self.pdf = render_pdf(build_scene(sample_plan()))

    def test_has_header_and_trailer(self):
        self.assertTrue(self.pdf.startswith(b"%PDF-1.4"))
        self.assertTrue(self.pdf.rstrip().endswith(b"%%EOF"))

    def test_xref_offsets_point_at_their_objects(self):
        start = int(re.search(rb"startxref\s+(\d+)", self.pdf).group(1))
        rows = [l for l in self.pdf[start:].split(b"\n") if l.endswith(b"00000 n ")]
        self.assertGreater(len(rows), 4)
        for number, row in enumerate(rows, start=1):
            offset = int(row.split()[0])
            match = re.match(rb"(\d+) 0 obj", self.pdf[offset:offset + 24])
            self.assertIsNotNone(match, f"object {number} is not at its offset")
            self.assertEqual(int(match.group(1)), number)

    def test_content_stream_length_is_accurate(self):
        match = re.search(rb"<< /Length (\d+) >>\nstream\n", self.pdf)
        declared = int(match.group(1))
        actual = self.pdf.index(b"\nendstream", match.end()) - match.end()
        self.assertEqual(declared, actual)

    def test_text_width_grows_with_the_string(self):
        self.assertGreater(text_width("KITCHEN", 10), text_width("BATH", 10))
        self.assertGreater(text_width("M", 10, bold=True), text_width("i", 10, bold=True))
        self.assertAlmostEqual(text_width("", 10), 0.0)

    def test_parentheses_in_the_title_do_not_break_the_stream(self):
        spec = PlanSpec.from_program(Polygon.rectangle(40, 30), bedrooms=2, bathrooms=1,
                                     title="Plan (rev 2) \\ final")
        pdf = render_pdf(build_scene(generate(spec, variants=1)[0]))
        self.assertTrue(pdf.rstrip().endswith(b"%%EOF"))
        self.assertIn(rb"\(rev 2\)", pdf)


class DxfTests(unittest.TestCase):
    def setUp(self):
        self.dxf = render_dxf(build_scene(sample_plan()))
        self.lines = self.dxf.splitlines()

    def test_group_codes_pair_with_values(self):
        self.assertEqual(len(self.lines) % 2, 0)
        for code in self.lines[0::2]:
            self.assertTrue(code.strip().lstrip("-").isdigit(), f"bad group code {code!r}")

    def test_sections_are_balanced_and_terminated(self):
        self.assertEqual(self.lines.count("SECTION"), self.lines.count("ENDSEC"))
        self.assertEqual(self.lines[-1], "EOF")
        for section in ("HEADER", "TABLES", "ENTITIES"):
            self.assertIn(section, self.lines)

    def test_emits_linework_and_text(self):
        self.assertGreater(self.lines.count("LINE"), 50)
        self.assertGreater(self.lines.count("TEXT"), 5)

    def test_fill_only_layers_are_omitted(self):
        for layer in SKIP_LAYERS:
            self.assertNotIn(layer, self.lines)

    def test_coordinates_are_real_world_feet(self):
        """DXF is 1:1 in model space, so coordinates match the plan's own numbers."""
        plan = sample_plan()
        xs = [float(self.lines[i + 1]) for i, c in enumerate(self.lines) if c == "10" and i % 2 == 0]
        self.assertLess(max(xs), plan.footprint.bounds.x2 + 40)
        self.assertGreater(max(xs), plan.footprint.bounds.w / 2)


class PreviewTests(unittest.TestCase):
    def test_ascii_preview_has_shape_and_legend(self):
        art = ascii_plan(sample_plan(), width=80)
        body = art.split("\n\n")[0].splitlines()
        self.assertTrue(all(len(row) == 80 for row in body))
        self.assertIn("rooms:", art)
        self.assertIn("@", art)  # the front door


if __name__ == "__main__":
    unittest.main()


class RasterTests(unittest.TestCase):
    """The PNG backend, and the layout defects it was built to catch."""

    @classmethod
    def setUpClass(cls):
        cls.plan = sample_plan()
        cls.scene = build_scene(cls.plan)
        cls.png = render_png(cls.scene, width=700)

    def test_png_is_structurally_valid(self):
        self.assertTrue(self.png.startswith(b"\x89PNG\r\n\x1a\n"))
        length = int.from_bytes(self.png[8:12], "big")
        self.assertEqual(self.png[12:16], b"IHDR")
        self.assertEqual(length, 13)
        self.assertTrue(self.png.endswith(b"IEND\xae\x42\x60\x82"))

    def test_every_chunk_crc_checks_out(self):
        import zlib
        offset = 8
        seen = []
        while offset < len(self.png):
            length = int.from_bytes(self.png[offset:offset + 4], "big")
            kind = self.png[offset + 4:offset + 8]
            payload = self.png[offset + 8:offset + 8 + length]
            stored = int.from_bytes(self.png[offset + 8 + length:offset + 12 + length], "big")
            self.assertEqual(stored, zlib.crc32(kind + payload) & 0xFFFFFFFF, kind)
            seen.append(kind)
            offset += 12 + length
        self.assertEqual(seen, [b"IHDR", b"pHYs", b"IDAT", b"IEND"])

    def test_physical_size_is_declared(self):
        """pHYs records the real DPI, so the PNG knows how big it is."""
        import struct
        png = render_png(self.scene, dpi=150)
        index = png.index(b"pHYs")
        ppm_x, ppm_y, unit = struct.unpack(">IIB", png[index + 4:index + 13])
        self.assertEqual(unit, 1)  # metres
        self.assertEqual(ppm_x, ppm_y)
        self.assertAlmostEqual(ppm_x * 0.0254, 150, delta=1)

    def test_pixel_data_decompresses_to_the_declared_size(self):
        import zlib
        width = int.from_bytes(self.png[16:20], "big")
        height = int.from_bytes(self.png[20:24], "big")
        start = self.png.index(b"IDAT") + 4
        length = int.from_bytes(self.png[start - 8:start - 4], "big")
        raw = zlib.decompress(self.png[start:start + length])
        self.assertEqual(len(raw), height * (width * 3 + 1))

    def test_rendering_is_deterministic(self):
        self.assertEqual(self.png, render_png(build_scene(sample_plan()), width=700))

    def test_supersampling_keeps_the_requested_size(self):
        plain = render_png(self.scene, width=400)
        smooth = render_png(self.scene, width=400, supersample=2)
        self.assertEqual(plain[16:24], smooth[16:24])
        self.assertNotEqual(plain, smooth)


class LabelTests(unittest.TestCase):
    """Regressions found by looking at a rendered plan."""

    def _labels(self, plan):
        return [t for t in build_scene(plan).texts if t.layer == "TEXT"]

    def test_fit_shrinks_text_until_it_fits(self):
        """The unit that guarantees a label fits, rather than guessing a size."""
        long_name = "PRIMARY BEDROOM SUITE"
        size = _fit(long_name, 7.0, 0.78)
        self.assertLess(size, 0.78)
        self.assertLessEqual(text_width(long_name, size), 7.0 + 1e-9)
        # Short text is never enlarged past the preferred size.
        self.assertEqual(_fit("A", 50.0, 0.78), 0.78)

    def test_labels_fit_inside_their_room(self):
        """A label must not spill across the walls that bound it."""
        cases = [
            (Polygon.l_shape(56, 40, 18, 14), dict(bedrooms=4, bathrooms=3, garage=True)),
            (Polygon.rectangle(48, 32), dict(bedrooms=3, bathrooms=2)),
            (Polygon.rectangle(34, 26), dict(bedrooms=2, bathrooms=1)),
        ]
        specs = [PlanSpec.from_program(fp, **prog) for fp, prog in cases]
        # A deliberately long room name: without fitting, this overflows.
        specs.append(PlanSpec(
            footprint=Polygon.rectangle(40, 28),
            rooms=[RoomSpec("living", name="Great Room And Hearth"),
                   RoomSpec("kitchen", name="Kitchen And Scullery"),
                   RoomSpec("primary_bedroom", name="Primary Bedroom Suite"),
                   RoomSpec("primary_bath"), RoomSpec("bedroom", name="Guest Bedroom Two"),
                   RoomSpec("foyer")],
        ))
        for spec in specs:
            for plan in generate(spec, variants=2):
                for text in self._labels(plan):
                    room = min(plan.rooms, key=lambda r: (r.rect.center[0] - text.x) ** 2
                               + (r.rect.center[1] - text.y) ** 2)
                    net = room.net_rect(plan.spec, plan.footprint)
                    available = net.h if text.rotate else net.w
                    with self.subTest(room=room.label, text=text.value):
                        self.assertLessEqual(text_width(text.value, text.size), available)

    def test_rotated_labels_stack_across_their_baseline(self):
        """Rotated lines spread along x; stacking them in y would overlap them."""
        spec = PlanSpec.from_program(Polygon.rectangle(48, 32), bedrooms=3, bathrooms=2)
        checked = 0
        for plan in generate(spec, variants=4):
            for room in plan.rooms:
                lines = [t for t in self._labels(plan)
                         if t.rotate and room.rect.contains_point((t.x, t.y))]
                if len(lines) < 2:
                    continue
                checked += 1
                spread_x = max(l.x for l in lines) - min(l.x for l in lines)
                spread_y = max(l.y for l in lines) - min(l.y for l in lines)
                with self.subTest(room=room.label):
                    self.assertGreater(spread_x, 0.1)
                    self.assertLess(spread_y, 0.1)
        self.assertGreater(checked, 0, "no multi-line rotated label was exercised")

    def test_upright_labels_stack_vertically(self):
        spec = PlanSpec.from_program(Polygon.rectangle(48, 32), bedrooms=3, bathrooms=2)
        plan = generate(spec, variants=1)[0]
        checked = 0
        for room in plan.rooms:
            lines = [t for t in self._labels(plan)
                     if not t.rotate and room.rect.contains_point((t.x, t.y))]
            if len(lines) < 2:
                continue
            checked += 1
            self.assertGreater(max(l.y for l in lines) - min(l.y for l in lines), 0.1)
            self.assertLess(max(l.x for l in lines) - min(l.x for l in lines), 0.1)
        self.assertGreater(checked, 0)

    def test_title_block_cells_do_not_overlap(self):
        """Each cell holds its own text; nothing crosses a rule.

        Checked on a narrow plan, where the facts line does not fit its cell at
        the preferred size and has to be shrunk to stay inside it.
        """
        spec = PlanSpec.from_program(Polygon.rectangle(26, 22), bedrooms=1, bathrooms=1,
                                     formal_dining=False, pantry=False, title="Narrow Lot")
        plan = generate(spec, variants=1)[0]
        scene = build_scene(plan)
        bounds = plan.footprint.bounds
        sheet = [t for t in scene.texts if t.layer == "SHEET" and t.y < bounds.y]
        self.assertGreaterEqual(len(sheet), 4)
        left = bounds.x + bounds.w * 0.54
        right = bounds.x + bounds.w * 0.76
        for text in sheet:
            width = text_width(text.value, text.size)
            offset = {"start": 0.0, "middle": 0.5, "end": 1.0}[text.anchor]
            start = text.x - width * offset
            end = start + width
            with self.subTest(text=text.value):
                self.assertFalse(start < left < end, "text crosses the first rule")
                self.assertFalse(start < right < end, "text crosses the second rule")
