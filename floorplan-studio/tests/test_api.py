"""Request handling: validation, replay, and the HTTP surface."""

import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from floorplan.api import RequestError, catalog, footprint_from, generate_from, replay, spec_from
from floorplan.server import Handler

#: Requests in this suite state their units, because the default is metric and
#: these assertions are about feet.
RECT = {"shape": "rectangle", "width": 48, "depth": 32, "units": "imperial",
        "bedrooms": 3, "bathrooms": 2}


class FootprintTests(unittest.TestCase):
    def test_presets_have_the_requested_extents(self):
        for shape in ("rectangle", "l", "t", "u"):
            with self.subTest(shape=shape):
                bounds = footprint_from({"shape": shape, "width": 50, "depth": 36,
                                         "units": "imperial"}).bounds
                self.assertAlmostEqual(bounds.w, 50)
                self.assertAlmostEqual(bounds.h, 36)

    def test_explicit_points_win_over_a_preset(self):
        poly = footprint_from({"shape": "u", "units": "imperial",
                               "footprint": [[0, 0], [20, 0], [20, 10], [0, 10]]})
        self.assertAlmostEqual(poly.area, 200)

    def test_rejects_unknown_shape(self):
        with self.assertRaises(RequestError):
            footprint_from({"shape": "hexagon"})

    def test_rejects_absurd_extents(self):
        for payload in ({"width": 2, "depth": 30, "units": "imperial"},
                        {"width": 60, "depth": 9999, "units": "imperial"}):
            with self.subTest(payload=payload):
                with self.assertRaises(RequestError):
                    footprint_from(payload)

    def test_rejects_too_few_corners(self):
        with self.assertRaises(RequestError):
            footprint_from({"footprint": [[0, 0], [10, 0], [10, 10]]})

    def test_rejects_too_many_corners(self):
        with self.assertRaises(RequestError):
            footprint_from({"footprint": [[i, 0] for i in range(70)]})

    def test_rejects_diagonal_edges(self):
        with self.assertRaises(RequestError):
            footprint_from({"footprint": [[0, 0], [10, 4], [10, 10], [0, 10]]})


class SpecTests(unittest.TestCase):
    def test_program_builds_the_expected_rooms(self):
        spec = spec_from(dict(RECT, garage=True, office=True))
        keys = [r.type_key for r in spec.rooms]
        self.assertIn("garage", keys)
        self.assertIn("office", keys)
        self.assertEqual(keys.count("bedroom") + keys.count("primary_bedroom"), 3)

    def test_explicit_room_list_is_honoured(self):
        spec = spec_from({
            "shape": "rectangle", "width": 30, "depth": 24, "units": "imperial",
            "rooms": [{"type": "living"}, {"type": "kitchen", "name": "Galley", "sqft": 90},
                      {"type": "bedroom"}, {"type": "bathroom"}],
        })
        self.assertEqual(len(spec.rooms), 4)
        self.assertEqual(spec.rooms[1].label, "Galley")
        self.assertEqual(spec.rooms[1].target_sqft, 90)

    def test_rejects_unknown_room_type(self):
        with self.assertRaises(RequestError):
            spec_from({"shape": "rectangle", "rooms": [{"type": "ballroom"}]})

    def test_rejects_out_of_range_counts(self):
        for payload in (dict(RECT, bedrooms=0), dict(RECT, bathrooms=99)):
            with self.subTest(payload=payload):
                with self.assertRaises(RequestError):
                    spec_from(payload)

    def test_metric_is_the_default(self):
        """A request that says nothing gets metres, not feet."""
        spec = spec_from({"shape": "rectangle", "bedrooms": 3, "bathrooms": 2})
        self.assertEqual(spec.units, "metric")
        self.assertAlmostEqual(spec.footprint.bounds.w, 15 * 3.280839895, places=6)
        self.assertAlmostEqual(spec.footprint.bounds.h, 10 * 3.280839895, places=6)

    def test_title_is_truncated(self):
        self.assertLessEqual(len(spec_from(dict(RECT, title="x" * 200)).title), 80)


class GenerateTests(unittest.TestCase):
    def test_variant_count_is_clamped(self):
        self.assertEqual(len(generate_from(dict(RECT, variants=99))), 6)
        self.assertEqual(len(generate_from(dict(RECT, variants=0))), 1)

    def test_rejects_a_program_that_cannot_fit(self):
        with self.assertRaises(RequestError) as caught:
            generate_from({"shape": "rectangle", "width": 20, "depth": 20,
                           "units": "imperial", "bedrooms": 8, "bathrooms": 8,
                           "garage": True})
        self.assertIn("will not fit", str(caught.exception))

    def test_replay_reproduces_a_variant_exactly(self):
        plans = generate_from(dict(RECT, seed=4, variants=3))
        for plan in plans:
            with self.subTest(seed=plan.seed):
                again = replay(dict(RECT, seed=4), plan.seed)
                self.assertEqual(
                    [r.to_dict() for r in again.rooms], [r.to_dict() for r in plan.rooms]
                )

    def test_catalog_describes_every_room_type(self):
        entries = catalog()
        self.assertGreater(len(entries), 10)
        self.assertLessEqual({"key", "label", "zone", "target_sqft", "min_dim"}, set(entries[0]))


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.httpd.quiet = True
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def post(self, path, payload):
        request = urllib.request.Request(
            self.base + path, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers, exc.read()

    def test_serves_the_ui(self):
        with urllib.request.urlopen(self.base + "/", timeout=10) as response:
            body = response.read().decode()
        self.assertEqual(response.status, 200)
        self.assertIn("<title>Floorplan Studio</title>", body)

    def test_catalog_endpoint(self):
        with urllib.request.urlopen(self.base + "/api/catalog", timeout=10) as response:
            payload = json.load(response)
        self.assertGreater(len(payload["rooms"]), 10)

    def test_generate_returns_svg_variants(self):
        status, _, raw = self.post("/api/generate", dict(RECT, variants=2))
        self.assertEqual(status, 200)
        variants = json.loads(raw)["variants"]
        self.assertEqual(len(variants), 2)
        for variant in variants:
            self.assertTrue(variant["svg"].startswith("<svg"))
            self.assertIn("score", variant["summary"])
            self.assertEqual(len(variant["rooms"]), variant["summary"]["rooms"])

    def test_export_returns_each_format(self):
        _, _, raw = self.post("/api/generate", dict(RECT, variants=1))
        seed = json.loads(raw)["variants"][0]["seed"]
        for fmt, head in (("pdf", b"%PDF"), ("svg", b"<svg"), ("dxf", b"0\nSECTION")):
            with self.subTest(format=fmt):
                status, headers, blob = self.post("/api/export", dict(RECT, seed=seed, format=fmt))
                self.assertEqual(status, 200)
                self.assertTrue(blob.startswith(head))
                self.assertIn("attachment;", headers["Content-Disposition"])
                self.assertIn(f".{fmt}", headers["Content-Disposition"])

    def test_bad_requests_get_a_useful_400(self):
        cases = [
            ("/api/generate", {"shape": "hexagon"}),
            ("/api/generate", {"footprint": [[0, 0], [1, 0], [1, 1]]}),
            ("/api/export", dict(RECT, format="dwg", seed=0)),
            ("/api/export", RECT),  # no seed
        ]
        for path, payload in cases:
            with self.subTest(path=path, payload=payload):
                status, _, raw = self.post(path, payload)
                self.assertEqual(status, 400)
                self.assertTrue(json.loads(raw)["error"])

    def test_malformed_json_is_rejected(self):
        request = urllib.request.Request(
            self.base + "/api/generate", data=b"{not json",
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=10)
        self.assertEqual(caught.exception.code, 400)

    def test_unknown_routes_are_404(self):
        status, _, _ = self.post("/api/nope", {})
        self.assertEqual(status, 404)

    def test_static_traversal_is_blocked(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self.base + "/static/../../../etc/passwd", timeout=10)
        self.assertIn(caught.exception.code, (400, 404))


if __name__ == "__main__":
    unittest.main()
