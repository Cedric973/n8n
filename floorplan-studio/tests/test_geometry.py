"""Geometry: footprints, decomposition and wall adjacency."""

import unittest

from floorplan.geometry import Polygon, Rect, Segment, format_feet, shared_wall

SHAPES = {
    "rectangle": Polygon.rectangle(40, 30),
    "l": Polygon.l_shape(40, 30, 14, 12),
    "t": Polygon.t_shape(40, 30, 16, 10),
    "u": Polygon.u_shape(40, 30, 12, 10),
}


class PolygonTests(unittest.TestCase):
    def test_areas_match_construction(self):
        self.assertAlmostEqual(SHAPES["rectangle"].area, 1200)
        self.assertAlmostEqual(SHAPES["l"].area, 1200 - 14 * 12)
        self.assertAlmostEqual(SHAPES["t"].area, 40 * 20 + 16 * 10)
        self.assertAlmostEqual(SHAPES["u"].area, 1200 - 12 * 10)

    def test_rejects_diagonal_edges(self):
        with self.assertRaises(ValueError):
            Polygon([(0, 0), (10, 4), (10, 10), (0, 10)])

    def test_rejects_degenerate_ring(self):
        with self.assertRaises(ValueError):
            Polygon([(0, 0), (10, 0), (10, 0)])

    def test_drops_collinear_points(self):
        poly = Polygon([(0, 0), (5, 0), (10, 0), (10, 10), (0, 10)])
        self.assertEqual(len(poly.points), 4)

    def test_winding_is_normalised(self):
        clockwise = Polygon([(0, 10), (10, 10), (10, 0), (0, 0)])
        self.assertEqual(clockwise.points, Polygon.rectangle(10, 10).points)

    def test_contains_point_includes_boundary(self):
        poly = SHAPES["l"]
        self.assertTrue(poly.contains_point((1, 1)))
        self.assertTrue(poly.contains_point((0, 5)))       # on an edge
        self.assertFalse(poly.contains_point((39, 29)))    # inside the notch
        self.assertFalse(poly.contains_point((-1, 5)))


class DecompositionTests(unittest.TestCase):
    def test_decomposition_covers_exactly(self):
        for name, poly in SHAPES.items():
            with self.subTest(shape=name):
                parts = poly.decompose()
                self.assertAlmostEqual(sum(r.area for r in parts), poly.area, places=6)

    def test_decomposition_parts_are_disjoint(self):
        for name, poly in SHAPES.items():
            with self.subTest(shape=name):
                parts = poly.decompose()
                for i in range(len(parts)):
                    for j in range(i + 1, len(parts)):
                        self.assertAlmostEqual(parts[i].overlap_area(parts[j]), 0.0, places=6)

    def test_decomposition_stays_inside(self):
        for name, poly in SHAPES.items():
            with self.subTest(shape=name):
                for part in poly.decompose():
                    self.assertTrue(poly.contains_point(part.center))

    def test_rectangle_is_one_piece(self):
        self.assertEqual(len(SHAPES["rectangle"].decompose()), 1)

    def test_l_shape_is_two_pieces(self):
        self.assertEqual(len(SHAPES["l"].decompose()), 2)


class RectTests(unittest.TestCase):
    def test_aspect_and_dimensions(self):
        r = Rect(0, 0, 20, 10)
        self.assertEqual(r.aspect, 2.0)
        self.assertEqual(r.min_dim, 10)
        self.assertEqual(r.center, (10.0, 5.0))

    def test_overlap_area(self):
        self.assertEqual(Rect(0, 0, 10, 10).overlap_area(Rect(5, 5, 10, 10)), 25)
        self.assertEqual(Rect(0, 0, 10, 10).overlap_area(Rect(10, 0, 5, 5)), 0)


class SharedWallTests(unittest.TestCase):
    def test_vertical_contact(self):
        seg = shared_wall(Rect(0, 0, 10, 10), Rect(10, 2, 5, 6))
        self.assertIsNotNone(seg)
        self.assertTrue(seg.vertical)
        self.assertAlmostEqual(seg.length, 6)

    def test_horizontal_contact(self):
        seg = shared_wall(Rect(0, 0, 10, 10), Rect(3, 10, 4, 5))
        self.assertIsNotNone(seg)
        self.assertTrue(seg.horizontal)
        self.assertAlmostEqual(seg.length, 4)

    def test_corner_touch_is_not_a_wall(self):
        self.assertIsNone(shared_wall(Rect(0, 0, 10, 10), Rect(10, 10, 5, 5)))

    def test_separated_rects_do_not_touch(self):
        self.assertIsNone(shared_wall(Rect(0, 0, 10, 10), Rect(11, 0, 5, 5)))


class SegmentTests(unittest.TestCase):
    def test_sub_segment_is_centred_and_clamped(self):
        seg = Segment(0, 0, 10, 0)
        sub = seg.sub(0.5, 4)
        self.assertAlmostEqual(sub.length, 4)
        self.assertAlmostEqual(sub.midpoint[0], 5)
        self.assertAlmostEqual(seg.sub(0.5, 40).length, 10)  # cannot exceed the wall


class FormatTests(unittest.TestCase):
    def test_feet_and_inches(self):
        self.assertEqual(format_feet(12.5), "12'-6\"")
        self.assertEqual(format_feet(10.0), "10'-0\"")
        self.assertEqual(format_feet(9.96), "10'-0\"")  # rounds to the nearest inch


if __name__ == "__main__":
    unittest.main()
