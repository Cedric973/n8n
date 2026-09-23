"""Units are a boundary concern: convert in, format out, feet in between."""

import unittest

from floorplan import Polygon, PlanSpec, generate
from floorplan.api import RequestError, spec_from
from floorplan.dxf import DXF_ENCODING, render_dxf
from floorplan.pdf import render_pdf
from floorplan.raster import render_png
from floorplan.render import build_scene
from floorplan.svg import render_svg
from floorplan.units import (
    DEFAULT_EXTENT, DEFAULT_UNITS, IMPERIAL, METRIC, format_area, format_dimensions,
    format_feet, format_length, from_feet, from_sqft, normalise, scale_bar_options,
    to_feet, to_sqft,
)


class ConversionTests(unittest.TestCase):
    def test_round_trips_exactly(self):
        for value in (1.0, 3.5, 12.0, 91.44):
            with self.subTest(value=value):
                self.assertAlmostEqual(from_feet(to_feet(value, METRIC), METRIC), value, places=9)
                self.assertAlmostEqual(from_sqft(to_sqft(value, METRIC), METRIC), value, places=9)

    def test_imperial_is_the_identity(self):
        for fn in (to_feet, from_feet, to_sqft, from_sqft):
            self.assertEqual(fn(7.5, IMPERIAL), 7.5)

    def test_known_conversions(self):
        self.assertAlmostEqual(to_feet(1.0, METRIC), 3.280839895, places=6)
        self.assertAlmostEqual(to_sqft(1.0, METRIC), 10.763910417, places=6)

    def test_normalise_accepts_spellings_and_rejects_nonsense(self):
        for value in ("metric", "Metres", "SI", "m", "meters"):
            self.assertEqual(normalise(value), METRIC)
        for value in ("imperial", "FT", "feet"):
            self.assertEqual(normalise(value), IMPERIAL)
        self.assertEqual(normalise(None), DEFAULT_UNITS)
        with self.assertRaises(ValueError):
            normalise("cubits")


class DefaultTests(unittest.TestCase):
    def test_the_default_is_metric(self):
        self.assertEqual(DEFAULT_UNITS, METRIC)

    def test_a_spec_with_no_units_is_metric(self):
        spec = PlanSpec.from_program(Polygon.rectangle(48, 32), bedrooms=2, bathrooms=1)
        self.assertEqual(spec.units, METRIC)

    def test_default_extents_are_buildable_in_both_systems(self):
        for system, (width, depth) in DEFAULT_EXTENT.items():
            with self.subTest(units=system):
                area = to_feet(width, system) * to_feet(depth, system)
                self.assertGreater(area, 400)   # big enough for a small house
                self.assertLess(area, 4000)     # not absurd


class FormattingTests(unittest.TestCase):
    def test_imperial_is_feet_and_inches(self):
        self.assertEqual(format_feet(12.5), "12'-6\"")
        self.assertEqual(format_length(12.5, IMPERIAL), "12'-6\"")
        self.assertEqual(format_area(126, IMPERIAL), "126 SF")

    def test_metric_is_metres_and_square_metres(self):
        self.assertEqual(format_length(12.5, METRIC), "3.81 m")
        self.assertEqual(format_dimensions(12.5, 10.0, METRIC), "3.81 x 3.05 m")
        self.assertEqual(format_area(126, METRIC), "11.7 m²")

    def test_metric_names_its_unit_once(self):
        self.assertEqual(format_dimensions(12.5, 10.0, METRIC).count("m"), 1)

    def test_scale_bars_differ_by_system(self):
        self.assertEqual([label for _, label in scale_bar_options(IMPERIAL)][0], "10 FT")
        self.assertEqual([label for _, label in scale_bar_options(METRIC)][0], "3 m")


class SpecTests(unittest.TestCase):
    def test_spec_stores_and_normalises_units(self):
        spec = PlanSpec.from_program(Polygon.rectangle(48, 32), bedrooms=2,
                                     bathrooms=1, units="Metres")
        self.assertEqual(spec.units, METRIC)

    def test_units_survive_a_dict_round_trip(self):
        spec = PlanSpec.from_program(Polygon.rectangle(48, 32), bedrooms=2,
                                     bathrooms=1, units=METRIC)
        self.assertEqual(PlanSpec.from_dict(spec.to_dict()).units, METRIC)

    def test_unknown_units_are_rejected(self):
        with self.assertRaises(ValueError):
            PlanSpec.from_program(Polygon.rectangle(40, 30), bedrooms=1,
                                  bathrooms=1, units="furlongs")


class RequestTests(unittest.TestCase):
    def test_extents_are_read_in_the_callers_units(self):
        metric = spec_from({"shape": "rectangle", "width": 15, "depth": 10,
                            "units": "metric", "bedrooms": 3, "bathrooms": 2})
        self.assertAlmostEqual(metric.footprint.bounds.w, to_feet(15, METRIC), places=6)
        self.assertAlmostEqual(metric.footprint.bounds.h, to_feet(10, METRIC), places=6)

    def test_explicit_footprints_are_converted(self):
        spec = spec_from({"footprint": [[0, 0], [10, 0], [10, 8], [0, 8]],
                          "units": "metric", "bedrooms": 2, "bathrooms": 1})
        self.assertAlmostEqual(spec.footprint.area, to_sqft(80, METRIC), places=4)

    def test_explicit_room_areas_are_converted(self):
        spec = spec_from({"shape": "rectangle", "width": 12, "depth": 9, "units": "metric",
                          "rooms": [{"type": "living", "sqft": 30}, {"type": "bedroom"},
                                    {"type": "bathroom"}, {"type": "kitchen"}]})
        self.assertAlmostEqual(spec.rooms[0].target_sqft, to_sqft(30, METRIC), places=4)

    def test_bad_units_are_a_request_error(self):
        with self.assertRaises(RequestError):
            spec_from({"shape": "rectangle", "units": "smoots"})

    def test_extent_limits_are_applied_after_conversion(self):
        spec_from({"shape": "rectangle", "width": 20, "depth": 15, "units": "metric",
                   "bedrooms": 3, "bathrooms": 2})  # 65 x 49 ft: fine
        with self.assertRaises(RequestError):
            spec_from({"shape": "rectangle", "width": 2, "depth": 2, "units": "metric"})


class OutputTests(unittest.TestCase):
    def _texts(self, units):
        spec = PlanSpec.from_program(Polygon.l_shape(56, 40, 18, 14), bedrooms=4,
                                     bathrooms=3, garage=True, units=units,
                                     title="Units")
        plan = generate(spec, variants=1)[0]
        return plan, [t.value for t in build_scene(plan).texts]

    def test_metric_output_has_no_imperial_marks(self):
        _plan, texts = self._texts(METRIC)
        body = " ".join(texts)
        self.assertNotIn("'-", body)
        self.assertNotIn(" SF", body)
        self.assertIn("m²", body)

    def test_imperial_output_has_no_metric_marks(self):
        _plan, texts = self._texts(IMPERIAL)
        body = " ".join(texts)
        self.assertNotIn("m²", body)
        self.assertIn("'-", body)

    def test_dimension_chains_follow_the_unit_system(self):
        for units, needle in ((METRIC, " m"), (IMPERIAL, "'-")):
            spec = PlanSpec.from_program(Polygon.rectangle(48, 32), bedrooms=3,
                                         bathrooms=2, units=units)
            plan = generate(spec, variants=1)[0]
            chains = [t.value for t in build_scene(plan).texts if t.layer == "A-DIMS"]
            with self.subTest(units=units):
                self.assertTrue(chains)
                self.assertTrue(all(needle in c for c in chains), chains[:3])

    def test_geometry_is_identical_across_unit_systems(self):
        """Units are presentation only; the same seed must lay out the same."""
        footprint = Polygon.rectangle(48, 32)
        imperial = generate(PlanSpec.from_program(footprint, bedrooms=3, bathrooms=2,
                                                  units=IMPERIAL), variants=1)[0]
        metric = generate(PlanSpec.from_program(footprint, bedrooms=3, bathrooms=2,
                                                units=METRIC), variants=1)[0]
        self.assertEqual([r.to_dict() for r in imperial.rooms],
                         [r.to_dict() for r in metric.rooms])

    def test_every_backend_handles_the_square_metre_sign(self):
        plan, _ = self._texts(METRIC)
        scene = build_scene(plan)
        self.assertIn("m²", render_svg(scene))
        self.assertTrue(render_pdf(scene).rstrip().endswith(b"%%EOF"))
        self.assertTrue(render_png(scene, width=500).startswith(b"\x89PNG"))
        encoded = render_dxf(scene).encode(DXF_ENCODING, "replace")
        self.assertIn("m²".encode(DXF_ENCODING), encoded)
        self.assertIn(b"ANSI_1252", encoded)


if __name__ == "__main__":
    unittest.main()
