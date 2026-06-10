"""Every censused route must load from a clean checkout (Codex PR #60 P2).

On CI, artifacts/ does not exist, so this test passes only if load_route()
resolves the census and every per-route human replay through the committed
evidence fallbacks (experiments/nav_doctrine/evidence/).
"""

import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import verify_route  # noqa: E402

CENSUS = REPO / "experiments" / "nav_doctrine" / "evidence" / "trick-census" / "census.json"


class TestLoadRouteReproducible(unittest.TestCase):
    def test_census_evidence_committed(self):
        self.assertTrue(CENSUS.exists(), f"{CENSUS} must be committed")

    def test_every_censused_route_loads(self):
        for name in json.loads(CENSUS.read_text()):
            with self.subTest(route=name):
                route = verify_route.load_route(name)
                self.assertEqual(route["name"], name)
                self.assertTrue(Path(route["human"]).exists())
                self.assertIsInstance(route["tele_entrances"], tuple)

    def test_default_route_loads(self):
        route = verify_route.load_route("sng_to_rl")
        self.assertTrue(route["native_dist"])
        self.assertIsNotNone(route["geom"])


if __name__ == "__main__":
    unittest.main()
