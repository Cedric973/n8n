"""Circulation: every room reachable, and no route through a bathroom."""

import unittest
from collections import defaultdict

from floorplan import Polygon, PlanSpec, generate
from floorplan.layout import layout_once
from floorplan.openings import TERMINAL, adjacency_graph
from floorplan.plan import exterior_segments
from floorplan.scoring import _reachable

CASES = [
    ("rect", Polygon.rectangle(48, 32), dict(bedrooms=3, bathrooms=2)),
    ("large", Polygon.rectangle(70, 44), dict(bedrooms=5, bathrooms=3, office=True)),
    ("l", Polygon.l_shape(56, 40, 18, 14), dict(bedrooms=4, bathrooms=3, garage=True, mudroom=True)),
    ("t", Polygon.t_shape(52, 38, 20, 12), dict(bedrooms=3, bathrooms=2, office=True)),
    ("u", Polygon.u_shape(54, 38, 16, 12), dict(bedrooms=3, bathrooms=2)),
]


def plans():
    for name, footprint, program in CASES:
        spec = PlanSpec.from_program(footprint, title=name, **program)
        for rank, plan in enumerate(generate(spec, variants=3)):
            yield f"{name}#{rank}", plan


class ReachabilityTests(unittest.TestCase):
    def test_every_returned_plan_is_fully_connected(self):
        for label, plan in plans():
            with self.subTest(plan=label):
                unreachable = [r.label for r in plan.rooms if r.index not in _reachable(plan)]
                self.assertEqual(unreachable, [])

    def test_every_plan_has_exactly_one_front_door(self):
        for label, plan in plans():
            with self.subTest(plan=label):
                entries = [o for o in plan.openings if o.kind == "entry"]
                self.assertEqual(len(entries), 1)

    def test_front_door_sits_on_an_exterior_wall(self):
        for label, plan in plans():
            entry = next(o for o in plan.openings if o.kind == "entry")
            room = plan.rooms[entry.rooms[0]]
            with self.subTest(plan=label):
                walls = exterior_segments(room.rect, plan.footprint)
                self.assertTrue(walls, f"{room.label} has no exterior wall")


class TerminalRoomTests(unittest.TestCase):
    def test_terminal_rooms_are_never_through_routes(self):
        for label, plan in plans():
            degree = defaultdict(int)
            for opening in plan.openings:
                if opening.kind in ("door", "opening") and len(opening.rooms) == 2:
                    for index in opening.rooms:
                        degree[index] += 1
            for room in plan.rooms:
                if room.type_key in TERMINAL:
                    with self.subTest(plan=label, room=room.label):
                        self.assertLessEqual(degree[room.index], 1)


class OpeningGeometryTests(unittest.TestCase):
    def test_doors_fit_inside_their_wall(self):
        for label, plan in plans():
            graph = adjacency_graph(plan.rooms, plan.spec.door_width)
            for opening in plan.openings:
                if opening.kind not in ("door", "opening") or len(opening.rooms) != 2:
                    continue
                a, b = sorted(opening.rooms)
                wall = graph.get((a, b))
                with self.subTest(plan=label, rooms=(a, b)):
                    self.assertIsNotNone(wall)
                    self.assertLessEqual(opening.width, wall.length + 1e-6)

    def test_openings_are_axis_aligned_and_positive(self):
        for label, plan in plans():
            for opening in plan.openings:
                with self.subTest(plan=label, kind=opening.kind):
                    self.assertTrue(opening.segment.vertical or opening.segment.horizontal)
                    self.assertGreater(opening.width, 0)

    def test_windows_sit_on_exterior_walls(self):
        for label, plan in plans():
            for opening in plan.openings:
                if opening.kind != "window":
                    continue
                room = plan.rooms[opening.rooms[0]]
                walls = exterior_segments(room.rect, plan.footprint)
                with self.subTest(plan=label, room=room.label):
                    self.assertTrue(walls)

    def test_garage_gets_an_overhead_door(self):
        spec = PlanSpec.from_program(
            Polygon.l_shape(60, 44, 20, 16), bedrooms=3, bathrooms=2, garage=True
        )
        plan = generate(spec, variants=1)[0]
        self.assertTrue(any(o.kind == "garage" for o in plan.openings))


class SummaryTests(unittest.TestCase):
    def test_summary_reports_the_program(self):
        spec = PlanSpec.from_program(
            Polygon.rectangle(60, 40), bedrooms=4, bathrooms=3, garage=True, title="Summary"
        )
        plan = generate(spec, variants=1)[0]
        summary = plan.summary()
        self.assertEqual(summary["title"], "Summary")
        self.assertEqual(summary["bedrooms"], 4)
        self.assertEqual(summary["rooms"], len(plan.rooms))
        self.assertLess(summary["conditioned_sqft"], summary["total_sqft"])  # garage excluded

    def test_half_baths_count_as_a_half(self):
        spec = PlanSpec.from_program(Polygon.rectangle(56, 38), bedrooms=2, bathrooms=3)
        plan = layout_once(spec, 0)
        self.assertIn(plan.bath_count, (2.5, 3))


if __name__ == "__main__":
    unittest.main()
