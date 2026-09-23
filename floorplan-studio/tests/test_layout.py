"""Layout invariants: the solver must tile the footprint and stay deterministic."""

import unittest

from floorplan import Polygon, PlanSpec
from floorplan.geometry import Rect
from floorplan.layout import _Item, generate, layout_once, slice_layout
import random

FOOTPRINTS = {
    "rect": Polygon.rectangle(48, 32),
    "small": Polygon.rectangle(30, 24),
    "l": Polygon.l_shape(56, 40, 18, 14),
    "t": Polygon.t_shape(52, 38, 20, 12),
    "u": Polygon.u_shape(54, 38, 16, 12),
}
PROGRAMS = {
    "1bd": dict(bedrooms=1, bathrooms=1, formal_dining=False, pantry=False),
    "3bd": dict(bedrooms=3, bathrooms=2),
    "4bd": dict(bedrooms=4, bathrooms=3, office=True, mudroom=True),
    "5bd_garage": dict(bedrooms=5, bathrooms=3, garage=True, mudroom=True),
}


def specs():
    for fname, footprint in FOOTPRINTS.items():
        for pname, program in PROGRAMS.items():
            spec = PlanSpec.from_program(footprint, **program)
            if footprint.area / len(spec.rooms) < 25:
                continue  # the API rejects these as unbuildable
            yield f"{fname}/{pname}", spec


class SliceTests(unittest.TestCase):
    def test_slice_fills_the_rectangle(self):
        rng = random.Random(0)
        rect = Rect(0, 0, 30, 20)
        items = [_Item(i, area) for i, area in enumerate([200, 150, 90, 60, 100])]
        placed = slice_layout(items, rect, rng)
        self.assertEqual(len(placed), len(items))
        self.assertAlmostEqual(sum(r.area for r in placed.values()), rect.area, places=6)

    def test_slice_respects_minimum_dimension_when_feasible(self):
        rng = random.Random(1)
        placed = slice_layout(
            [_Item("big", 300, 10.0), _Item("small", 60, 6.0)], Rect(0, 0, 30, 12), rng
        )
        self.assertGreaterEqual(placed["small"].min_dim, 5.9)
        self.assertGreaterEqual(placed["big"].min_dim, 9.9)

    def test_slice_ignores_zero_area_items(self):
        placed = slice_layout([_Item("a", 10), _Item("b", 0)], Rect(0, 0, 5, 2), random.Random(0))
        self.assertEqual(set(placed), {"a"})

    def test_empty_input_is_empty_output(self):
        self.assertEqual(slice_layout([], Rect(0, 0, 10, 10), random.Random(0)), {})


class InvariantTests(unittest.TestCase):
    def test_rooms_tile_the_footprint_exactly(self):
        for label, spec in specs():
            for seed in range(8):
                with self.subTest(spec=label, seed=seed):
                    plan = layout_once(spec, seed)
                    covered = sum(room.area for room in plan.rooms)
                    self.assertAlmostEqual(covered, spec.footprint.area, places=4)

    def test_rooms_never_overlap(self):
        for label, spec in specs():
            for seed in range(4):
                plan = layout_once(spec, seed)
                rects = [r.rect for r in plan.rooms]
                for i in range(len(rects)):
                    for j in range(i + 1, len(rects)):
                        with self.subTest(spec=label, seed=seed, pair=(i, j)):
                            self.assertAlmostEqual(rects[i].overlap_area(rects[j]), 0.0, places=4)

    def test_every_room_is_placed_with_area(self):
        for label, spec in specs():
            plan = layout_once(spec, 3)
            with self.subTest(spec=label):
                self.assertEqual(len(plan.rooms), len(spec.rooms))
                self.assertTrue(all(room.area > 0 for room in plan.rooms))

    def test_rooms_stay_inside_the_footprint(self):
        for label, spec in specs():
            plan = layout_once(spec, 2)
            for room in plan.rooms:
                with self.subTest(spec=label, room=room.label):
                    self.assertTrue(spec.footprint.contains_point(room.rect.center))


class DeterminismTests(unittest.TestCase):
    def test_same_seed_gives_the_same_plan(self):
        spec = PlanSpec.from_program(FOOTPRINTS["rect"], bedrooms=3, bathrooms=2)
        a, b = layout_once(spec, 11), layout_once(spec, 11)
        self.assertEqual([r.to_dict() for r in a.rooms], [r.to_dict() for r in b.rooms])
        self.assertEqual(a.score, b.score)

    def test_different_seeds_can_differ(self):
        spec = PlanSpec.from_program(FOOTPRINTS["rect"], bedrooms=3, bathrooms=2)
        layouts = {
            tuple(sorted((r.label, round(r.rect.x, 2), round(r.rect.y, 2)) for r in layout_once(spec, s).rooms))
            for s in range(12)
        }
        self.assertGreater(len(layouts), 1)


class GenerateTests(unittest.TestCase):
    def test_returns_the_requested_number_of_variants(self):
        spec = PlanSpec.from_program(FOOTPRINTS["rect"], bedrooms=3, bathrooms=2)
        for count in (1, 3, 5):
            with self.subTest(variants=count):
                self.assertEqual(len(generate(spec, variants=count)), count)

    def test_variants_are_ordered_best_first(self):
        spec = PlanSpec.from_program(FOOTPRINTS["l"], bedrooms=4, bathrooms=3)
        scores = [p.score for p in generate(spec, variants=4)]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_rejects_zero_variants(self):
        spec = PlanSpec.from_program(FOOTPRINTS["rect"], bedrooms=2, bathrooms=1)
        with self.assertRaises(ValueError):
            generate(spec, variants=0)

    def test_chosen_plans_are_not_near_duplicates(self):
        spec = PlanSpec.from_program(FOOTPRINTS["rect"], bedrooms=4, bathrooms=2)
        plans = generate(spec, variants=3)
        for i in range(len(plans)):
            for j in range(i + 1, len(plans)):
                shared = sum(
                    a.rect.overlap_area(b.rect) for a, b in zip(plans[i].rooms, plans[j].rooms)
                )
                with self.subTest(pair=(i, j)):
                    self.assertLess(shared / plans[i].total_sqft, 0.9)


class SpecTests(unittest.TestCase):
    def test_program_areas_fill_the_footprint(self):
        spec = PlanSpec.from_program(FOOTPRINTS["rect"], bedrooms=3, bathrooms=2)
        self.assertAlmostEqual(sum(spec.scaled_areas()), spec.footprint.area, places=6)

    def test_bathroom_counting(self):
        spec = PlanSpec.from_program(FOOTPRINTS["rect"], bedrooms=3, bathrooms=3)
        plan = layout_once(spec, 0)
        self.assertEqual(plan.bedroom_count, 3)
        self.assertEqual(plan.bath_count, 3)

    def test_round_trip_through_dict(self):
        spec = PlanSpec.from_program(FOOTPRINTS["l"], bedrooms=2, bathrooms=2, title="Round Trip")
        clone = PlanSpec.from_dict(spec.to_dict())
        self.assertEqual(clone.title, "Round Trip")
        self.assertEqual([r.type_key for r in clone.rooms], [r.type_key for r in spec.rooms])
        self.assertAlmostEqual(clone.footprint.area, spec.footprint.area)

    def test_rejects_unknown_room_type(self):
        with self.assertRaises(ValueError):
            PlanSpec(footprint=FOOTPRINTS["rect"], rooms=[__import__("floorplan").RoomSpec("ballroom")])

    def test_rejects_empty_program(self):
        with self.assertRaises(ValueError):
            PlanSpec(footprint=FOOTPRINTS["rect"], rooms=[])


if __name__ == "__main__":
    unittest.main()
