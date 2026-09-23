"""Readability checks, and the drawing rules they enforce on generated plans."""

from __future__ import annotations

import unittest

from floorplan import Polygon, PlanSpec, generate
from floorplan.drawing import Scene, Text
from floorplan.geometry import Rect
from floorplan.quality import Issue, check_scene, summary, text_box
from floorplan.render import _swing_boxes, build_scene
from floorplan.sheet import choose


def scene_at_scale(ratio: float = 50.0) -> Scene:
    sheet, scale = choose(60.0, 40.0, "metric", scale=f"1:{ratio:g}")
    return Scene(bounds=Rect(0, 0, 60, 40), sheet=sheet, scale=scale)


class CheckTests(unittest.TestCase):
    def test_overlapping_texts_are_reported_and_separated_ones_are_not(self):
        scene = scene_at_scale()
        scene.text(10, 10, "KITCHEN", size=0.8, bold=True)
        scene.text(10.4, 10.2, "15.6 m²", size=0.6)          # on top of the first
        scene.text(30, 10, "DINING", size=0.8, bold=True)      # far away
        issues = check_scene(scene)
        self.assertEqual([i.kind for i in issues], ["overlap"])
        self.assertIn("KITCHEN", issues[0].message)
        scene.items[1] = Text(10, 8.5, "15.6 m²", size=0.6)    # stacked under it instead
        self.assertEqual(check_scene(scene), [])

    def test_rotated_text_box_is_rotated(self):
        upright = text_box(Text(0, 0, "HALLWAY", size=1.0, rotate=0.0))
        turned = text_box(Text(0, 0, "HALLWAY", size=1.0, rotate=90.0))
        self.assertGreater(upright[2] - upright[0], upright[3] - upright[1])
        self.assertGreater(turned[3] - turned[1], turned[2] - turned[0])
        self.assertAlmostEqual(upright[2] - upright[0], turned[3] - turned[1], places=6)

    def test_small_print_is_reported_against_the_sheet_scale(self):
        scene = scene_at_scale(100.0)
        scene.text(5, 5, "2497", size=0.3)   # 0.3 ft = 91 mm real = 0.9 mm on paper at 1:100
        scene.text(20, 5, "LIVING", size=1.0)
        kinds = [i.kind for i in check_scene(scene)]
        self.assertEqual(kinds, ["small"])
        self.assertIn("2497", check_scene(scene)[0].message)

    def test_text_on_a_wall_is_reported(self):
        from floorplan.render import WALL
        scene = scene_at_scale()
        scene.rect(Rect(0, 9.5, 40, 1.0), fill=WALL, layer="A-WALL")
        scene.text(10, 10, "FOYER", size=0.8, layer="A-TEXT")
        scene.text(10, 20, "LIVING", size=0.8, layer="A-TEXT")
        issues = check_scene(scene)
        self.assertEqual([(i.kind, "FOYER" in i.message) for i in issues], [("over-wall", True)])
        counts = summary(issues)
        self.assertEqual((counts["issues"], counts["over-wall"], counts["overlap"]), (1, 1, 0))


class GeneratedPlanTests(unittest.TestCase):
    """The rules the generator's sheets must satisfy on every plan, not one."""

    @classmethod
    def setUpClass(cls):
        cls.plans = []
        for shape, seed in ((Polygon.rectangle(50, 32), 1), (Polygon.l_shape(56, 40, 18, 14), 7),
                            (Polygon.u_shape(60, 40, 14, 12), 3), (Polygon.t_shape(60, 40, 14, 12), 11)):
            spec = PlanSpec.from_program(shape, bedrooms=3, bathrooms=2, title="Q", units="metric")
            cls.plans.append(generate(spec, variants=1, attempts=6)[0])

    def test_client_plan_has_no_overlapping_or_wall_covered_text(self):
        for plan in self.plans:
            scene = build_scene(plan, level="client")
            bad = [i for i in check_scene(scene) if i.kind in ("overlap", "over-wall")]
            self.assertEqual(bad, [], f"seed {plan.seed}: {[str(i) for i in bad]}")

    def test_nothing_prints_small_at_any_level(self):
        for plan in self.plans:
            for level in ("client", "dimension", "technical"):
                scene = build_scene(plan, level=level)
                small = [i for i in check_scene(scene) if i.kind == "small"]
                self.assertEqual(small, [], f"seed {plan.seed} {level}: {[str(i) for i in small]}")

    def test_labels_keep_clear_of_door_swings(self):
        for plan in self.plans:
            scene = build_scene(plan, level="client")
            labels = [t for t in scene.texts if t.layer == "A-TEXT" and t.bold]
            for room in plan.rooms:
                for t in labels:
                    if t.value != room.label.upper():
                        continue
                    box = text_box(t)
                    for swing in _swing_boxes(plan, room):
                        clash = box[0] < swing.x2 and swing.x < box[2] and box[1] < swing.y2 and swing.y < box[3]
                        self.assertFalse(clash, f"seed {plan.seed}: {t.value} sits in a door swing")

    def test_fixtures_sit_inside_their_rooms_and_off_the_door_swings(self):
        for plan in self.plans:
            scene = build_scene(plan, level="client")
            fixtures = [p for p in scene.paths if p.layer == "A-FURN"]
            self.assertTrue(fixtures, f"seed {plan.seed}: no fixtures drawn")
            rooms = [(r, r.net_rect(plan.spec, plan.footprint)) for r in plan.rooms if r.rect.area > 0]
            for p in fixtures:
                xs = [x for x, _ in p.points]; ys = [y for _, y in p.points]
                box = Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
                home = [(r, net) for r, net in rooms
                        if box.x >= net.x - 1e-6 and box.y >= net.y - 1e-6
                        and box.x2 <= net.x2 + 1e-6 and box.y2 <= net.y2 + 1e-6]
                self.assertEqual(len(home), 1, f"seed {plan.seed}: a fixture is not inside one room")
                room = home[0][0]
                self.assertIn(room.type_key, ("bedroom", "primary_bedroom", "bathroom", "primary_bath",
                                              "powder", "kitchen"))
                for swing in _swing_boxes(plan, room):
                    self.assertFalse(box.x < swing.x2 and swing.x < box.x2 and box.y < swing.y2 and swing.y < box.y2,
                                     f"seed {plan.seed}: a fixture in {room.label} blocks a door")

    def test_every_bedroom_gets_a_bed(self):
        for plan in self.plans:
            scene = build_scene(plan, level="client")
            fixtures = [p for p in scene.paths if p.layer == "A-FURN"]
            for room in plan.rooms:
                if room.type_key not in ("bedroom", "primary_bedroom"):
                    continue
                net = room.net_rect(plan.spec, plan.footprint)
                inside = [p for p in fixtures if all(net.x - 1e-6 <= x <= net.x2 + 1e-6 and
                                                     net.y - 1e-6 <= y <= net.y2 + 1e-6 for x, y in p.points)]
                big = [p for p in inside if (max(x for x, _ in p.points) - min(x for x, _ in p.points)) *
                       (max(y for _, y in p.points) - min(y for _, y in p.points)) > 25.0]
                self.assertTrue(big, f"seed {plan.seed}: {room.label} has no bed")


if __name__ == "__main__":
    unittest.main()
