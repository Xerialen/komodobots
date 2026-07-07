"""Contract tests for lab/server/kb2_matches_build.py (komodobots.kb2_matches.v2).

Fixtures under tests/fixtures/kb2_matches/ are real (trimmed) artifacts from
the servexeri komodobots2-lab mirror: two hm-era runs (run-meta + ktxstats +
a server.log filtered to match-begun/gapjump lines) and a truncated
records/bench.json. Stdlib only.
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lab" / "server"))

import kb2_matches_build as kb  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "kb2_matches"


class FeatureDerivation(unittest.TestCase):
    def test_hm_and_fov_from_cvars(self):
        tags = kb.derive_features(
            {"k_hm": "1", "k_hm_fov": "120", "k_kbot_routepolicy": "2"},
            "routepol-champ")
        self.assertEqual(tags, ["hm", "fov", "routepolicy"])

    def test_fov_zero_is_not_a_feature(self):
        self.assertNotIn("fov", kb.derive_features({"k_hm_fov": "0"}, ""))

    def test_stamp_derived_tags(self):
        self.assertIn("dials", kb.derive_features({}, "kbot-0.28.0-dials.mid-tl20"))
        self.assertIn("harvest", kb.derive_features({}, "kbot-0.26.0-harvest.comb-tl20"))
        self.assertIn("sng", kb.derive_features({}, "kbot-0.24.9-sngFloor.ws100"))

    def test_no_match_is_stock(self):
        self.assertEqual(kb.derive_features({}, "frogbot-stock"), ["stock"])


class GapjumpParsing(unittest.TestCase):
    LOG = "\n".join([
        "[2026-07-07 04:30:06] The match has begun!",
        "[2026-07-07 04:30:47] [gapjump] lane=ra2ya trial=0 result=FAIL_GAP"
        " land_pos=601,-210,-48 hdist=96 peak_speed=409 tair=0.94 vreq=324",
        "[2026-07-07 04:32:23] [gapjump] lane=ra2ya slot=3 name=Angua trial=0"
        " result=LAND land_pos=705,-230,56 hdist=48 peak_speed=425 tair=0.66 vreq=324",
    ])

    def test_land_events_with_match_relative_seconds(self):
        jumps, _lanes = kb.parse_gapjump_events(self.LOG)
        self.assertEqual(len(jumps), 1)
        j = jumps[0]
        self.assertEqual(j["t_s"], 137)  # 04:32:23 - 04:30:06
        self.assertEqual(j["name"], "Angua")
        self.assertEqual(j["lane"], "ra2ya")
        self.assertEqual(j["peak_speed"], 425)

    def test_warmup_jumps_before_match_begun_are_skipped(self):
        warmup = ("[2026-07-07 04:29:00] [gapjump] lane=ra2ya slot=1 name=hib"
                  " trial=0 result=LAND land_pos=1,2,3 hdist=1 peak_speed=400"
                  " tair=0.5 vreq=324\n")
        jumps, lanes = kb.parse_gapjump_events(warmup + self.LOG)
        self.assertEqual([j["name"] for j in jumps], ["Angua"])
        # warmup LAND is excluded from the counts too
        self.assertEqual(lanes["ra2ya"]["lands"], 1)

    def test_attempts_fails_and_declines_are_counted_per_lane(self):
        log = "\n".join([
            "[2026-07-07 04:30:06] The match has begun!",
            "[2026-07-07 04:30:20] [gapjump] lane=ra2ya result=APP_ENGAGE",
            "[2026-07-07 04:30:21] [gapjump] lane=ra2ya result=APP_DECLINE_SLOW",
            "[2026-07-07 04:30:30] [gapjump] lane=ra2ya result=APP_YIELD_SEEN",
            "[2026-07-07 04:30:47] [gapjump] lane=ra2ya trial=0 result=FAIL_GAP"
            " land_pos=601,-210,-48 hdist=96 peak_speed=409 tair=0.94 vreq=324",
            "[2026-07-07 04:31:02] [gapjump] lane=e12b trial=0 result=FAIL_TIMEOUT"
            " land_pos=-272,-800,336 hdist=1088 peak_speed=407 tair=4.01 vreq=324",
            "[2026-07-07 04:32:23] [gapjump] lane=ra2ya slot=3 name=Angua trial=0"
            " result=LAND land_pos=705,-230,56 hdist=48 peak_speed=425 tair=0.66 vreq=324",
        ])
        _jumps, lanes = kb.parse_gapjump_events(log)
        self.assertEqual(lanes["ra2ya"],
                         {"attempts": 2, "lands": 1, "fails": 1, "declines": 2})
        self.assertEqual(lanes["e12b"],
                         {"attempts": 1, "lands": 0, "fails": 1, "declines": 0})

    def test_real_world_decline_line_format_is_counted(self):
        # Verbatim from a bench server.log (2026-07-06): decline lines carry
        # along/lat/vh/floor fields, no trial= and no hdist= — they must fall
        # through GAPJUMP_RE and be counted by the decline matcher.
        log = "\n".join([
            "[2026-07-06 15:47:00] The match has begun!",
            "[2026-07-06 15:47:44] [gapjump] lane=ra2ya result=APP_ABORT_TIMEOUT"
            " along=-174 lat=6 vh=89 floor=389",
            "[2026-07-06 15:47:49] [gapjump] lane=ya2ra result=APP_ABORT_TIMEOUT"
            " along=-177 lat=-8 vh=8 floor=379",
        ])
        _jumps, lanes = kb.parse_gapjump_events(log)
        self.assertEqual(lanes["ra2ya"], {"attempts": 0, "lands": 0, "fails": 0, "declines": 1})
        self.assertEqual(lanes["ya2ra"]["declines"], 1)

    def test_app_engage_and_launch_are_not_declines(self):
        log = "\n".join([
            "[2026-07-07 04:30:06] The match has begun!",
            "[2026-07-07 04:30:20] [gapjump] lane=ra2ya result=APP_ENGAGE",
            "[2026-07-07 04:30:21] [gapjump] lane=ra2ya result=APP_LAUNCH",
        ])
        _jumps, lanes = kb.parse_gapjump_events(log)
        # phase breadcrumbs alone produce no outcome counts at all
        self.assertNotIn("ra2ya", lanes)

    def test_fixture_log_parses(self):
        text = (FIXTURES / "lab-runs" / "20260707T022951Z-p28601" /
                "server.log").read_text(encoding="utf-8")
        jumps, lanes = kb.parse_gapjump_events(text)
        self.assertGreaterEqual(len(jumps), 2)
        self.assertTrue(all(j["t_s"] >= 0 for j in jumps))
        total_lands = sum(l["lands"] for l in lanes.values())
        self.assertEqual(total_lands, len(jumps))
        self.assertTrue(all(l["attempts"] >= l["lands"] for l in lanes.values()))


class DeepLink(unittest.TestCase):
    def test_five_second_preroll_and_encoding(self):
        url = kb.demo_player_url("/demos/files/non-games/lab/Komodobots/kb2/x.mvd",
                                 "dm3", 300, 137)
        self.assertIn("from=132", url)
        self.assertIn("map=dm3", url)
        self.assertIn("duration=300", url)
        self.assertIn("%2Fdemos%2Ffiles%2F", url)

    def test_early_event_clamps_to_1(self):
        self.assertIn("from=1", kb.demo_player_url("/d.mvd", "dm3", None, 2))


class BuildFromFixtures(unittest.TestCase):
    def setUp(self):
        self.doc = kb.build(FIXTURES, demo_url_base="/demos/files/kb2")

    def test_schema_and_counts(self):
        self.assertEqual(self.doc["schema"], "komodobots.kb2_matches.v2")
        self.assertEqual(self.doc["source"]["runs_included"], 2)
        self.assertEqual(len(self.doc["matches"]), 2)

    def test_per_match_jump_accounting_and_feed_lane_aggregate(self):
        m = self.doc["matches"][0]
        self.assertGreaterEqual(m["jumps"]["attempts"], m["jumps"]["lands"])
        self.assertIn("lanes", m["jumps"])
        lanes = self.doc["jump_lanes"]
        self.assertGreater(len(lanes), 0)
        for lane in lanes.values():
            self.assertGreaterEqual(lane["attempts"], lane["lands"])
            if lane["attempts"]:
                self.assertAlmostEqual(
                    lane["land_rate"], lane["lands"] / lane["attempts"], places=4)

    def test_player_rows_carry_pickup_and_rl_and_ttd_columns(self):
        m = self.doc["matches"][0]
        p = m["players"][0]
        for key in ("quad", "pent", "ring", "rl_pickups", "lg_pickups",
                    "rl_direct_hits", "rl_attacks", "taken_to_die",
                    "avg_speed", "max_speed"):
            self.assertIn(key, p)
        # 4on4 dm3: someone in the match took the quad
        self.assertGreaterEqual(
            sum(x["quad"] for x in m["players"]), 1)

    def test_match_row_contract(self):
        m = self.doc["matches"][0]  # newest first
        self.assertEqual(m["run_id"], "20260707T022951Z-p28601")
        self.assertEqual(m["map"], "dm3")
        self.assertEqual(m["duration_s"], 300)
        self.assertIn("komo", m["team_frags"])
        self.assertIn("fbots", m["team_frags"])
        self.assertEqual(
            m["frag_margin"],
            m["team_frags"]["komo"] - m["team_frags"]["fbots"])
        self.assertIn(m["winner"], ("komo", "fbots", "draw"))
        self.assertEqual(m["cvars"]["k_hm"], "1")
        self.assertIn("hm", m["features"])
        self.assertIn("fov", m["features"])
        self.assertIsNone(m["demo"]["url"])  # fixture has no demo.mvd
        self.assertEqual(len(m["players"]), 8)

    def test_jumps_have_run_context_but_no_watch_url_without_demo(self):
        self.assertGreater(len(self.doc["jumps"]), 0)
        j = self.doc["jumps"][0]
        self.assertIn(j["run_id"],
                      ("20260707T022951Z-p28601", "20260707T021508Z-p28600"))
        self.assertIsNone(j["watch_url"])
        self.assertEqual(j["map"], "dm3")
        # LAND lines carry names; team resolved via ktxstats
        self.assertIsNotNone(j["name"])
        self.assertIn(j["team"], ("komo", "fbots"))

    def test_aggregates_and_record_holder(self):
        self.assertIn("hm", self.doc["features"])
        agg = self.doc["features"]["hm"]
        self.assertEqual(agg["matches"], 2)
        self.assertEqual(agg["wins"] + agg["losses"] + agg["draws"], 2)
        self.assertIsNotNone(agg["best"])
        # min_matches=3 -> no record holder from a 2-run fixture
        self.assertIsNone(self.doc["record_holder"]["feature"])

    def test_ledger_passthrough(self):
        self.assertIn("kbot-0.28.0-dials.mid-tl20", self.doc["ledger"]["bench"])
        self.assertEqual(self.doc["ledger"]["valid_games"], 29)


class DemoPublishAndUrl(unittest.TestCase):
    def test_hardlink_publish_and_watch_url(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td) / "data"
            shutil.copytree(FIXTURES, data)
            run = data / "lab-runs" / "20260707T022951Z-p28601"
            (run / "demo.mvd").write_bytes(b"\x00mvd")
            pub = Path(td) / "published"

            n = kb.publish_demos(data / "lab-runs", pub)
            self.assertEqual(n, 1)
            self.assertTrue((pub / "20260707T022951Z-p28601.mvd").is_file())
            # second pass is a no-op
            self.assertEqual(kb.publish_demos(data / "lab-runs", pub), 0)

            doc = kb.build(data, demo_url_base="/demos/files/kb2")
            m = next(x for x in doc["matches"]
                     if x["run_id"] == "20260707T022951Z-p28601")
            self.assertEqual(m["demo"]["url"],
                             "/demos/files/kb2/20260707T022951Z-p28601.mvd")
            j = next(x for x in doc["jumps"]
                     if x["run_id"] == "20260707T022951Z-p28601")
            self.assertIn("/demo-player/?demoUrl=", j["watch_url"])
            self.assertIn(f"from={max(1, j['t_s'] - 5)}", j["watch_url"])


class CorruptRunGuard(unittest.TestCase):
    def test_one_corrupt_run_meta_costs_one_row_not_the_feed(self):
        # A run-meta.json truncated by a dropped sftp transfer (but stamped
        # .synced) must be skipped with a warning — the rest of the feed
        # still builds (review P2 on PR #482).
        with tempfile.TemporaryDirectory() as td:
            data = Path(td) / "data"
            shutil.copytree(FIXTURES, data)
            bad = data / "lab-runs" / "20260707T999999Z-p28999"
            bad.mkdir()
            (bad / "run-meta.json").write_text('{"run_id": "trunca', encoding="utf-8")
            doc = kb.build(data, demo_url_base="/demos/files/kb2")
            self.assertEqual(doc["source"]["runs_included"], 2)
            self.assertEqual(doc["source"]["runs_failed"], 1)
            self.assertNotIn(
                "20260707T999999Z-p28999",
                [m["run_id"] for m in doc["matches"]])


class RecordHolderThreshold(unittest.TestCase):
    def test_record_holder_needs_min_matches(self):
        agg = {
            "a": {"matches": 5, "margin_mean": 3.0},
            "b": {"matches": 2, "margin_mean": 99.0},
        }
        rh = kb.record_holder(agg, min_matches=3)
        self.assertEqual(rh["key"], "a")


if __name__ == "__main__":
    unittest.main()
