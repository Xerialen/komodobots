"""Bot-attempts gallery contract tests (#424).

Mirrors the selection/formatting logic in BotAttemptsGallery.tsx and validates
the committed example ledger the page falls back to, without a browser runtime.
Stdlib only.
"""

import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "lab" / "dashboard" / "public" / "data" / "bot-attempts.example.json"

REQUIRED_ATTEMPT_KEYS = {
    "run_id", "ts_utc", "map", "n_bots", "mode", "demo", "freshness", "verdict", "artifact_dir",
}


def watch_href(demo: dict, map_name: str) -> str:
    """Python mirror of BotAttemptsGallery.watchHref (the in-dashboard watch link)."""
    from urllib.parse import quote
    return f"panes/demo.html?demo={quote(demo['url'], safe='')}&map={quote(map_name, safe='')}"


class BotAttemptsFixtureContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.attempts = cls.ledger["attempts"]

    def test_schema_and_shape(self):
        self.assertEqual(self.ledger["schema"], "komodobots.bot_attempts.v1")
        self.assertIn("map", self.ledger)
        self.assertIsInstance(self.attempts, list)
        self.assertGreaterEqual(len(self.attempts), 1)

    def test_every_attempt_has_the_required_keys(self):
        for a in self.attempts:
            missing = REQUIRED_ATTEMPT_KEYS - a.keys()
            self.assertEqual(missing, set(), f"attempt {a.get('run_id')} missing {missing}")
            self.assertIn(a["verdict"], {"GREEN", "RED"})
            self.assertIsInstance(a["freshness"]["ok"], bool)

    def test_demo_url_uses_served_online_route_when_present(self):
        # The gallery's "watch demo" link is only as good as the served URL: it
        # must use /demos/online/ (the /demos/files/ prefix has no cloud_hub route).
        for a in self.attempts:
            if a["demo"] is not None:
                self.assertTrue(a["demo"]["url"].startswith("/demos/online/"),
                                f"{a['run_id']} demo.url not served-online")
                self.assertNotIn("/demos/files/", a["demo"]["url"])

    def test_fixture_covers_both_a_green_recording_and_a_red_no_recording(self):
        verdicts = {a["verdict"] for a in self.attempts}
        self.assertEqual(verdicts, {"GREEN", "RED"}, "example should show both outcomes")
        green = next(a for a in self.attempts if a["verdict"] == "GREEN")
        red = next(a for a in self.attempts if a["verdict"] == "RED")
        self.assertIsNotNone(green["demo"])           # a claimed-good run links a recording
        self.assertIsNone(red["demo"])                # a failed run shows the absence

    def test_newest_first_ordering(self):
        ts = [a["ts_utc"] for a in self.attempts]
        self.assertEqual(ts, sorted(ts, reverse=True), "attempts must be newest-first")

    def test_watch_href_round_trips_the_served_url(self):
        green = next(a for a in self.attempts if a["demo"] is not None)
        href = watch_href(green["demo"], green["map"])
        self.assertTrue(href.startswith("panes/demo.html?demo="))
        self.assertIn("map=dm3", href)


if __name__ == "__main__":
    unittest.main()
