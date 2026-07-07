"""Contract tests for lab/server/version_history_build.py (kb2_versions.v1).

Pure joins only — no gh, no network. Stdlib only.
"""

import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lab" / "server"))

import version_history_build as vh  # noqa: E402

FEED = {
    "ledger": {
        "bench": {
            "kbot-0.26.0-harvest.comb-tl20": {
                "games_scored": 4, "candidate_wins": 3, "control_wins": 1,
                "frag_margin_mean": 5.0,
            },
            "kbot-0.28.0-dials.mid-tl20": {
                "games_scored": 2, "candidate_wins": 1, "control_wins": 1,
                "frag_margin_mean": -1.0,
            },
            "frogbot-stock": {
                "games_scored": 9, "candidate_wins": 4, "control_wins": 5,
                "frag_margin_mean": 0.0,
            },
        },
    },
    "matches": [
        {"in_ledger": False, "candidate": {"version": "kbot-0.26.0-harvest.solo"}},
        {"in_ledger": False, "candidate": {"version": "kbot-0.28.0-dials.d-mid"}},
        {"in_ledger": True, "candidate": {"version": "kbot-0.26.0-harvest.comb-tl20"}},
        {"in_ledger": False, "candidate": {"version": "routepol-champ"}},
    ],
}


class JoinImpact(unittest.TestCase):
    def test_bench_aggregate_weighted_over_matching_stamps(self):
        bench, tests = vh.join_impact(
            ["kbot-0.26.0-harvest", "kbot-0.28.0-dials"], FEED)
        self.assertEqual(bench["games"], 6)
        self.assertEqual(bench["wins"], 4)
        self.assertEqual(bench["losses"], 2)
        # weighted mean: (5*4 + -1*2)/6 = 3.0
        self.assertEqual(bench["margin_mean"], 3.0)
        # two scratch matches match the stamps; the in_ledger one is excluded
        self.assertEqual(tests, 2)

    def test_no_stamps_means_no_impact(self):
        bench, tests = vh.join_impact([], FEED)
        self.assertIsNone(bench)
        self.assertEqual(tests, 0)


class Build(unittest.TestCase):
    def test_curated_summary_and_fallback(self):
        prs = [
            {"number": 31, "title": "docs/tooling: decision-log", "mergedAt": "2026-07-06T20:44:36Z"},
            {"number": 99, "title": "uncurated PR", "mergedAt": "2026-07-07T00:00:00Z"},
        ]
        summaries = {"31": {"name": "Harvester & the dials",
                            "summary": "Plain words.",
                            "stamps": ["kbot-0.26.0-harvest"]}}
        doc = vh.build(prs, summaries, FEED, "Xerialen/komodobots2")
        self.assertEqual(doc["schema"], "komodobots.kb2_versions.v1")
        self.assertEqual(len(doc["versions"]), 2)
        newest = doc["versions"][0]  # sorted newest first
        self.assertEqual(newest["pr"], 99)
        self.assertEqual(newest["summary"], "uncurated PR")  # title fallback
        self.assertIsNone(newest["bench"])
        curated = doc["versions"][1]
        self.assertEqual(curated["name"], "Harvester & the dials")
        self.assertEqual(curated["bench"]["games"], 4)
        self.assertEqual(curated["test_matches"], 1)

    def test_summaries_file_parses_and_matches_schema(self):
        data = json.loads(vh.DEFAULT_SUMMARIES.read_text(encoding="utf-8"))
        for key, entry in data.items():
            if key.startswith("_"):
                continue
            self.assertIn("name", entry)
            self.assertIn("summary", entry)
            self.assertIsInstance(entry.get("stamps", []), list)


if __name__ == "__main__":
    unittest.main()
