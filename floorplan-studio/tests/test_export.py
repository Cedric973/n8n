"""The three export backends must all describe the same scene, validly."""

import re
import unittest
import xml.dom.minidom

from floorplan import Polygon, PlanSpec, generate
from floorplan.drawing import Scene, fit_scale, hex_to_rgb
from floorplan.dxf import SKIP_LAYERS, render_dxf
from floorplan.geometry import Rect
from floorplan.pdf import render_pdf, text_width
from floorplan.preview import ascii_plan
from floorplan.render import build_scene
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

    def test_fit_scale_respects_margins(self):
        scale = fit_scale(Rect(0, 0, 100, 50), 1000, 1000, margin=50)
        self.assertAlmostEqual(scale, 9.0)

    def test_hex_parsing(self):
        self.assertEqual(hex_to_rgb("#ffffff"), (1.0, 1.0, 1.0))
        self.assertEqual(hex_to_rgb("#000"), (0.0, 0.0, 0.0))


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
