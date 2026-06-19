"""Tests for scripts/gmv_believability.py — the G-MV believability battery (T5.3).

Pure standard library; runs under ``python -m unittest``. No third-party imports,
no demo files needed: the real-human POSITIVE control reads a committed slice
fixture (``tests/fixtures/gmv_human_dm3_4on4_slice.json``) extracted from a real
dm3 4on4 self-POV ``.qwd`` by the same extractor the catalog ETL uses, and the
NEGATIVE control is the in-module synthetic face-and-run generator.

Coverage:
  * angle math (wrap180 / velocity_angle / yaw_minus_velocity)
  * G-MV1 (HARD, no face-and-run collapse) — pass, fail, insufficient
  * G-MV3 (strafe cadence) — in-band, too-fast, too-slow/dead-stick, insufficient
  * G-MV4 (speed band) — inside, outside, per-player vs pool band
  * CONTROL: real human .qwd slice fixture PASSES G-MV1 (and G-MV3)
  * CONTROL: synthetic face-and-run FAILS G-MV1 while PASSING the soft band gates
    (the discrimination proof: G-MV1 alone catches face-and-run)
"""
from __future__ import annotations

import json
import math
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import gmv_believability as g  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "gmv_human_dm3_4on4_slice.json"
ANCHORS = REPO_ROOT / "references" / "dm3_4on4_anchors.json"


def airborne_seq(angle_offsets_deg, speed=320.0, side_period=30, n=2000):
    """Build a synthetic airborne (state, usercmd) sequence whose yaw sits a
    chosen offset off a wandering velocity direction. ``angle_offsets_deg`` is a
    callable i -> offset (deg)."""
    ticks = []
    heading = 0.0
    for i in range(n):
        heading += math.sin(i * 0.05) * 2.0
        rad = math.radians(heading)
        vx = speed * math.cos(rad)
        vy = speed * math.sin(rad)
        yaw = g.velocity_angle_deg(vx, vy) + angle_offsets_deg(i)
        side_sign = 1 if (i // side_period) % 2 == 0 else -1
        ticks.append({"vx": vx, "vy": vy, "yaw": yaw, "hspeed": speed,
                      "onground": False, "msec": 13.0, "sidemove": 400 * side_sign})
    return ticks


class TestAngleMath(unittest.TestCase):
    def test_wrap180_range(self):
        self.assertAlmostEqual(g.wrap180(0.0), 0.0)
        self.assertAlmostEqual(g.wrap180(190.0), -170.0)
        self.assertAlmostEqual(g.wrap180(-190.0), 170.0)
        self.assertAlmostEqual(g.wrap180(360.0), 0.0)
        self.assertAlmostEqual(g.wrap180(540.0), 180.0)
        # endpoint maps to +180, not -180
        self.assertAlmostEqual(g.wrap180(180.0), 180.0)

    def test_velocity_angle(self):
        self.assertAlmostEqual(g.velocity_angle_deg(1.0, 0.0), 0.0)
        self.assertAlmostEqual(g.velocity_angle_deg(0.0, 1.0), 90.0)
        self.assertAlmostEqual(g.velocity_angle_deg(-1.0, 0.0), 180.0)

    def test_yaw_minus_velocity_wraps(self):
        # yaw 10, vel pointing at 350 deg (-10) -> difference +20, wrapped
        d = g.yaw_minus_velocity_deg(10.0, math.cos(math.radians(-10)), math.sin(math.radians(-10)))
        self.assertAlmostEqual(d, 20.0, places=4)

    def test_percentile(self):
        vals = list(range(0, 101))  # 0..100, already sorted
        self.assertAlmostEqual(g._percentile(vals, 0.0), 0.0)
        self.assertAlmostEqual(g._percentile(vals, 1.0), 100.0)
        self.assertAlmostEqual(g._percentile(vals, 0.5), 50.0)
        self.assertAlmostEqual(g._percentile(vals, 0.95), 95.0)


class TestGMV1(unittest.TestCase):
    def test_pass_human_shaped(self):
        # yaw held ~40 deg off velocity, oscillating -> human-shaped, not collapsed
        seq = airborne_seq(lambda i: 40.0 * (1 if (i // 30) % 2 == 0 else -1))
        r = g.gate_mv1(g.normalize_sequence(seq))
        self.assertTrue(r["passed"])
        self.assertEqual(r["status"], "pass")
        self.assertGreater(r["statistic"]["median_yaw_vs_vel_deg"], 30.0)
        self.assertLess(r["statistic"]["aligned_frac_within_5_deg"], 0.1)
        self.assertGreater(r["margin"]["median_minus_collapse_cut_deg"], 0.0)

    def test_fail_collapsed(self):
        # yaw == velocity direction every tick (face-and-run) -> collapse
        seq = airborne_seq(lambda i: 0.0)
        r = g.gate_mv1(g.normalize_sequence(seq))
        self.assertFalse(r["passed"])
        self.assertEqual(r["status"], "fail")
        self.assertAlmostEqual(r["statistic"]["median_yaw_vs_vel_deg"], 0.0, places=3)
        self.assertAlmostEqual(r["statistic"]["aligned_frac_within_5_deg"], 1.0, places=3)

    def test_fail_near_collapse_with_jitter(self):
        # tiny +-2 deg jitter around velocity: still collapsed (median<8 AND mostly aligned)
        seq = airborne_seq(lambda i: 2.0 * math.sin(i))
        r = g.gate_mv1(g.normalize_sequence(seq))
        self.assertFalse(r["passed"])

    def test_insufficient_when_too_few_airborne(self):
        # all on the ground -> no airborne-moving ticks to judge
        seq = airborne_seq(lambda i: 40.0)
        for t in seq:
            t["onground"] = True
        r = g.gate_mv1(g.normalize_sequence(seq))
        self.assertIsNone(r["passed"])
        self.assertEqual(r["status"], "insufficient")

    def test_low_speed_ticks_excluded(self):
        # below the min hspeed, velocity angle is noise and the tick is dropped
        seq = airborne_seq(lambda i: 40.0, speed=50.0)  # < mv1_min_hspeed (150)
        r = g.gate_mv1(g.normalize_sequence(seq))
        self.assertIsNone(r["passed"])  # insufficient: all filtered out
        self.assertEqual(r["n_ticks"], 0)


class TestGMV3(unittest.TestCase):
    def test_in_band(self):
        # flip strafe direction every 30 ticks (~0.4 s) -> ~150 flips/min, in band
        seq = airborne_seq(lambda i: 40.0, side_period=30)
        r = g.gate_mv3(g.normalize_sequence(seq))
        self.assertTrue(r["passed"])
        self.assertGreater(r["statistic"]["flips_per_min"], g.DEFAULT_THRESHOLDS["mv3_min_flips_per_min"])
        self.assertLess(r["statistic"]["flips_per_min"], g.DEFAULT_THRESHOLDS["mv3_max_flips_per_min"])

    def test_too_fast_jitter_fails(self):
        # flip every single tick -> ~2300 flips/min, far over the band (jitter)
        seq = airborne_seq(lambda i: 40.0, side_period=1)
        r = g.gate_mv3(g.normalize_sequence(seq))
        self.assertFalse(r["passed"])
        self.assertGreater(r["statistic"]["flips_per_min"], g.DEFAULT_THRESHOLDS["mv3_max_flips_per_min"])

    def test_dead_stick_fails(self):
        # hold one strafe direction the whole time -> zero flips (a robot dead-stick)
        seq = airborne_seq(lambda i: 40.0, side_period=10_000)
        r = g.gate_mv3(g.normalize_sequence(seq))
        self.assertFalse(r["passed"])
        self.assertEqual(r["statistic"]["flips"], 0)

    def test_insufficient_when_no_strafe(self):
        seq = airborne_seq(lambda i: 40.0)
        for t in seq:
            t["sidemove"] = 0
        r = g.gate_mv3(g.normalize_sequence(seq))
        self.assertIsNone(r["passed"])
        self.assertEqual(r["status"], "insufficient")

    def test_zero_run_between_flips_is_one_flip(self):
        # +side ... zeros ... -side counts as a single L/R flip (coast doesn't reset)
        rows = ([{"sidemove": 400}] * 60) + ([{"sidemove": 0}] * 60) + ([{"sidemove": -400}] * 60)
        r = g.gate_mv3(g.normalize_sequence(rows))
        self.assertEqual(r["statistic"]["flips"], 1)


class TestGMV4(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.anchors = g.load_anchors(ANCHORS)

    def _const_speed_seq(self, speed):
        # gate_mv4 (like all gates) consumes normalized ticks; hspeed is derived
        # from vx/vy by normalize_tick.
        return g.normalize_sequence(
            [{"vx": speed, "vy": 0.0, "yaw": 0.0, "onground": False,
              "sidemove": 0, "msec": 13.0} for _ in range(500)])

    def test_avg_inside_pool_band(self):
        # 290 qu/s sits inside the avg pool band [252,316]; the avg check passes.
        # (A constant-speed seq has avg==p95, so it cannot satisfy both the avg and
        # the much-higher p95 band at once — band-membership of the full battery is
        # exercised on real/synthetic bursty sequences in the control tests.)
        r = g.gate_mv4(self._const_speed_seq(290.0), self.anchors)
        self.assertEqual(r["statistic"]["checks"]["avg"]["band_field"], "avg_horizontal_speed_qu_per_s")
        self.assertTrue(r["statistic"]["checks"]["avg"]["inside"])

    def test_below_band_fails(self):
        r = g.gate_mv4(self._const_speed_seq(100.0), self.anchors)
        self.assertFalse(r["passed"])
        self.assertFalse(r["statistic"]["checks"]["avg"]["inside"])
        self.assertLess(r["margin"]["avg"], 0.0)  # negative distance == outside

    def test_above_band_fails(self):
        r = g.gate_mv4(self._const_speed_seq(900.0), self.anchors)
        self.assertFalse(r["passed"])
        self.assertLess(r["margin"]["p95"], 0.0)

    def test_per_player_band_selected(self):
        r = g.gate_mv4(self._const_speed_seq(290.0), self.anchors, player_band="Milton")
        self.assertEqual(r["band_player"], "Milton")
        self.assertEqual(r["statistic"]["checks"]["avg"]["band_source"], "per_player:Milton")

    def test_unknown_player_band_raises(self):
        with self.assertRaises(KeyError):
            g.gate_mv4(self._const_speed_seq(290.0), self.anchors, player_band="NoSuchPlayer")

    def test_band_comes_from_anchor_file(self):
        # the band the gate reports must equal the anchor JSON's per-player min/max
        fld = self.anchors["metrics"]["movement"]["fields"]["avg_horizontal_speed_qu_per_s"]
        exp = fld["per_player"]["Milton"]["stats"]
        r = g.gate_mv4(self._const_speed_seq(290.0), self.anchors, player_band="Milton")
        chk = r["statistic"]["checks"]["avg"]
        self.assertAlmostEqual(chk["band_min"], exp["min"], places=2)
        self.assertAlmostEqual(chk["band_max"], exp["max"], places=2)


class TestPositiveControlRealHuman(unittest.TestCase):
    """POSITIVE control: a committed slice of REAL human dm3 4on4 (state, usercmd)
    must PASS the hard G-MV1 (and the strafe-cadence G-MV3)."""

    def test_human_passes_gmv1(self):
        self.assertTrue(FIXTURE.exists(), "missing real-human fixture %s" % FIXTURE)
        ticks = g.load_sequence_json(FIXTURE)
        res = g.run_battery(ticks)
        mv1 = res["gates"]["G-MV1"]
        self.assertTrue(mv1["passed"], "real human must PASS G-MV1; got %r" % mv1)
        self.assertTrue(res["believable"])
        # human yaw-vs-velocity spread is large (air-strafing), not collapsed
        self.assertGreater(mv1["statistic"]["median_yaw_vs_vel_deg"], 20.0)
        self.assertLess(mv1["statistic"]["aligned_frac_within_5_deg"], 0.30)

    def test_human_passes_gmv3(self):
        ticks = g.load_sequence_json(FIXTURE)
        res = g.run_battery(ticks)
        self.assertTrue(res["gates"]["G-MV3"]["passed"])


class TestNegativeControlFaceAndRun(unittest.TestCase):
    """NEGATIVE control: the synthetic face-and-run (yaw == velocity angle every
    tick) must FAIL the hard G-MV1 — while PASSING the soft band gates — proving
    G-MV1 alone discriminates the FrikBotNex collapse."""

    def test_face_and_run_fails_gmv1(self):
        seq = g.synth_face_and_run(n=2000)
        res = g.run_battery(seq)
        mv1 = res["gates"]["G-MV1"]
        self.assertFalse(mv1["passed"], "face-and-run must FAIL G-MV1")
        self.assertEqual(mv1["status"], "fail")
        self.assertFalse(res["believable"])
        self.assertAlmostEqual(mv1["statistic"]["median_yaw_vs_vel_deg"], 0.0, places=2)

    def test_face_and_run_passes_soft_band_gates(self):
        # the discrimination point: a band-perfect sequence is STILL caught by G-MV1
        anchors = g.load_anchors(ANCHORS)
        seq = g.synth_face_and_run(n=2000)
        res = g.run_battery(seq, anchors=anchors)
        self.assertTrue(res["gates"]["G-MV3"]["passed"], "negative control should pass strafe cadence")
        self.assertTrue(res["gates"]["G-MV4"]["passed"], "negative control should pass speed band")
        # ...yet overall NOT believable, because the hard gate failed
        self.assertFalse(res["believable"])

    def test_discrimination_gap(self):
        # the proof in one assertion: human median yaw-vs-vel >> face-and-run median
        human = g.run_battery(g.load_sequence_json(FIXTURE))["gates"]["G-MV1"]
        far = g.run_battery(g.synth_face_and_run(n=2000))["gates"]["G-MV1"]
        self.assertGreater(human["statistic"]["median_yaw_vs_vel_deg"],
                           far["statistic"]["median_yaw_vs_vel_deg"] + 20.0)


class TestSyntheticHumanLike(unittest.TestCase):
    def test_human_like_passes_gmv1(self):
        res = g.run_battery(g.synth_human_like(n=2000))
        self.assertTrue(res["gates"]["G-MV1"]["passed"])


class TestBatteryAndCLI(unittest.TestCase):
    def test_battery_shape(self):
        res = g.run_battery(g.synth_human_like(n=500))
        self.assertEqual(res["schema"], g.SCHEMA)
        self.assertIn("G-MV1", res["gates"])
        self.assertIn("G-MV3", res["gates"])
        self.assertEqual(res["hard_gate"], "G-MV1")

    def test_cli_synthetic_face_and_run_exit2(self):
        # CLI returns non-zero iff the HARD gate actually failed
        rc = g.main(["--synthetic", "face_and_run", "--anchors", str(ANCHORS)])
        self.assertEqual(rc, 2)

    def test_cli_synthetic_human_like_exit0(self):
        rc = g.main(["--synthetic", "human_like", "--anchors", str(ANCHORS)])
        self.assertEqual(rc, 0)

    def test_cli_sequence_json(self):
        rc = g.main(["--sequence-json", str(FIXTURE), "--anchors", str(ANCHORS)])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
