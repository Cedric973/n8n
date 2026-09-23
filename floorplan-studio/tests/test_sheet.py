"""Drawings are at a standard scale on a standard sheet, and can be measured."""

import re
import struct
import unittest

from floorplan import Polygon, PlanSpec, generate
from floorplan.pdf import render_pdf
from floorplan.raster import render_png
from floorplan.render import _edge_divisions, build_scene
from floorplan.sheet import (
    IMPERIAL_SCALES, METRIC_SCALES, POINTS_PER_FOOT, Scale, choose, find_scale,
    find_sheet, fits, sheets_for,
)
from floorplan.svg import render_svg


def plan_for(footprint, units="imperial", **program):
    program.setdefault("bedrooms", 3)
    program.setdefault("bathrooms", 2)
    spec = PlanSpec.from_program(footprint, units=units, **program)
    return generate(spec, variants=1)[0]


class ScaleTableTests(unittest.TestCase):
    def test_points_per_foot_follows_the_ratio(self):
        quarter_inch = IMPERIAL_SCALES[0]
        self.assertEqual(quarter_inch.ratio, 48)
        self.assertEqual(quarter_inch.points_per_foot, 18.0)  # 1/4 inch
        self.assertAlmostEqual(METRIC_SCALES[2].points_per_foot, POINTS_PER_FOOT / 100)

    def test_scales_are_ordered_largest_first(self):
        for table in (IMPERIAL_SCALES, METRIC_SCALES):
            ratios = [s.ratio for s in table]
            self.assertEqual(ratios, sorted(ratios))

    def test_sheets_are_ordered_smallest_first(self):
        for units in ("imperial", "metric"):
            areas = [s.width * s.height for s in sheets_for(units)]
            self.assertEqual(areas, sorted(areas))

    def test_lookup_by_name_and_rejection(self):
        self.assertEqual(find_scale("1:100", "metric").ratio, 100)
        self.assertEqual(find_sheet("ansi c", "imperial").name, "ANSI C")
        with self.assertRaises(ValueError):
            find_scale("1:37", "metric")
        with self.assertRaises(ValueError):
            find_sheet("A9", "metric")


class ChoiceTests(unittest.TestCase):
    def test_picks_the_largest_scale_that_fits(self):
        sheet, scale = choose(80, 60, "imperial")
        self.assertEqual(scale, IMPERIAL_SCALES[0])
        self.assertTrue(fits(sheet, scale, 80, 60))

    def test_steps_the_scale_down_only_when_it_must(self):
        _sheet, small = choose(400, 300, "imperial")
        self.assertGreater(small.ratio, IMPERIAL_SCALES[0].ratio)

    def test_different_plans_share_a_scale(self):
        """The whole point: two plans you can lay side by side and compare."""
        big = build_scene(plan_for(Polygon.l_shape(64, 46, 22, 16), garage=True))
        small = build_scene(plan_for(Polygon.rectangle(26, 22), bedrooms=1, bathrooms=1,
                                     formal_dining=False, pantry=False))
        self.assertEqual(big.scale.label, small.scale.label)
        # The label could match while the geometry does not; the drawn size of
        # a foot is what actually makes two sheets comparable.
        self.assertAlmostEqual(big.scale.points_per_foot,
                               small.scale.points_per_foot, places=9)
        self.assertAlmostEqual(big.placement()[0], small.placement()[0], places=9)

    def test_a_small_plan_takes_less_of_its_sheet(self):
        """A small plan must not be blown up to fill the page."""
        big = build_scene(plan_for(Polygon.rectangle(64, 46)))
        small = build_scene(plan_for(Polygon.rectangle(30, 24)))
        big_share = big.bounds.w * big.scale.points_per_foot / big.sheet.width
        small_share = small.bounds.w * small.scale.points_per_foot / small.sheet.width
        self.assertLess(small_share, big_share)

    def test_explicit_choices_are_honoured(self):
        sheet, scale = choose(40, 30, "imperial", sheet="ANSI B", scale="1/8\" = 1'-0\"")
        self.assertEqual(sheet.name, "ANSI B")
        self.assertEqual(scale.ratio, 96)

    def test_an_explicit_scale_picks_a_sheet_that_holds_it(self):
        sheet, scale = choose(100, 66, "imperial", scale="1/4\" = 1'-0\"")
        self.assertEqual(scale.ratio, 48)
        self.assertTrue(fits(sheet, scale, 100, 66))

    def test_an_impossible_scale_is_refused_with_a_workable_one(self):
        """Better than clipping the drawing off the edge of the paper."""
        with self.assertRaises(ValueError) as caught:
            choose(120, 90, "imperial", scale="1/4\" = 1'-0\"")
        message = str(caught.exception)
        self.assertIn("does not fit", message)
        self.assertIn("ANSI D", message)
        # The scale it suggests must be a real one that actually fits.
        suggested = [s for s in IMPERIAL_SCALES if s.label in message
                     and s.ratio != 48]
        self.assertTrue(suggested, message)
        self.assertTrue(fits(sheets_for("imperial")[-1], suggested[0], 120, 90))

    def test_oversized_plans_are_labelled_not_to_scale(self):
        _sheet, scale = choose(4000, 3000, "imperial")
        self.assertEqual(scale.label, "NOT TO SCALE")

    def test_metric_uses_metric_sheets_and_scales(self):
        sheet, scale = choose(60, 45, "metric")
        self.assertIn(sheet.name, [s.name for s in sheets_for("metric")])
        self.assertTrue(scale.label.startswith("1:"))


class MeasurableOutputTests(unittest.TestCase):
    """The reason for all of the above: a print you can hold a rule against."""

    def setUp(self):
        self.plan = plan_for(Polygon.l_shape(64, 46, 22, 16), bedrooms=4,
                             bathrooms=3, garage=True)
        self.scene = build_scene(self.plan)

    def test_pdf_page_is_the_sheet(self):
        pdf = render_pdf(self.scene)
        box = re.search(rb"MediaBox \[([^\]]+)\]", pdf).group(1).decode().split()
        self.assertAlmostEqual(float(box[2]), self.scene.sheet.width, places=2)
        self.assertAlmostEqual(float(box[3]), self.scene.sheet.height, places=2)

    def test_a_known_length_measures_correctly_on_the_page(self):
        """64 ft at 1/4 inch per foot must come out as exactly 16 inches."""
        divisions = _edge_divisions(self.plan, True, False)
        feet = divisions[-1] - divisions[0]
        points_per_foot, _ox, _oy = self.scene.placement()
        inches = feet * points_per_foot / 72.0
        self.assertAlmostEqual(inches, feet / self.scene.scale.ratio * 12.0, places=6)
        self.assertAlmostEqual(points_per_foot, 18.0, places=6)
        self.assertAlmostEqual(inches, 16.0, places=6)

    def test_svg_declares_a_true_physical_size(self):
        svg = render_svg(self.scene)
        width = float(re.search(r'width="([\d.]+)in"', svg).group(1))
        self.assertAlmostEqual(width, self.scene.sheet.inches()[0], places=2)
        box = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
        self.assertAlmostEqual(float(box.group(1)), self.scene.sheet.width, places=2)

    def test_svg_can_state_the_page_in_millimetres(self):
        svg = render_svg(self.scene, metric_page=True)
        width = float(re.search(r'width="([\d.]+)mm"', svg).group(1))
        self.assertAlmostEqual(width, self.scene.sheet.millimetres()[0], places=1)

    def test_png_pixels_match_the_sheet_at_the_requested_dpi(self):
        png = render_png(self.scene, dpi=100)
        width, height = struct.unpack(">II", png[16:24])
        sheet_w, sheet_h = self.scene.sheet.inches()
        self.assertEqual(width, round(sheet_w * 100))
        self.assertEqual(height, round(sheet_h * 100))

    def test_png_width_override_sets_the_resolution_not_the_crop(self):
        png = render_png(self.scene, width=800)
        width, height = struct.unpack(">II", png[16:24])
        sheet_w, sheet_h = self.scene.sheet.inches()
        self.assertEqual(width, 800)
        self.assertAlmostEqual(width / height, sheet_w / sheet_h, places=2)

    def test_the_scale_is_printed_on_the_drawing(self):
        labels = [t.value for t in self.scene.texts if t.value.startswith("SCALE")]
        self.assertEqual(len(labels), 1)
        self.assertIn(self.scene.scale.label, labels[0])


if __name__ == "__main__":
    unittest.main()
