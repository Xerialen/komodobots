"""Unit tests for scripts/catalog_etl_mvd.py — the MVD action-recovery ETL.

Pure stdlib, runnable on bare python3.12 (no qw-analyze binary, no BSP, no numpy/torch).
Exercises the recovery logic on small synthetic pos-streams:
  * angle16 -> degree conversion,
  * sidemove SIGN = -sign(yaw_rate) flips with the turn direction, gated to the bhop regime,
  * jump emitted on a geometric onground TRUE->FALSE transition, NOT on single-tick flicker,
  * the schema-version guard hard-fails on a schema-21-shaped dict,
  * the manifest reader keeps only EXPLICIT class=='TRAIN' rows and carries their content lock,
  * a sha256 mismatch against the manifest is flagged (provenance verify), and
  * every idm row is held out of training (is_interp=True) until per-head weights exist.
"""
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import catalog_etl_mvd as etl  # noqa: E402


class _FakeProber:
    """Stand-in for OngroundProber: returns onground from a caller-supplied per-call sequence,
    so the recovery logic is testable without a BSP. Honors the vz>MAXGROUNDSPEED early-out so
    that branch is exercised too."""

    def __init__(self, flags):
        self._flags = list(flags)
        self._i = 0

    def onground(self, origin, vz):
        g = self._flags[self._i]
        self._i += 1
        if vz > etl.MAXGROUNDSPEED_DEFAULT:
            return False
        return g


class Angle16Test(unittest.TestCase):
    def test_angle16_to_deg(self):
        # 16384 angle16 == 90 deg (quarter turn); 0 == 0; -32768 == -180.
        self.assertAlmostEqual(16384 * etl.ANGLE16_TO_DEG, 90.0, places=4)
        self.assertAlmostEqual(0 * etl.ANGLE16_TO_DEG, 0.0, places=6)
        self.assertAlmostEqual(-32768 * etl.ANGLE16_TO_DEG, -180.0, places=4)

    def test_player_frames_converts_angles_and_keeps_velocity(self):
        pos = {
            "t": [0, 13, 26],
            "x": [10.0, 11.0, 12.0], "y": [0.0, 0.0, 0.0], "z": [-88.0, -88.0, -88.0],
            "vx": [300.0, 305.0, 310.0], "vy": [5.0, 6.0, 7.0], "vz": [0.0, 1.0, 2.0],
            "vya": [16384, 16384, 16384],  # == 90 deg
            "vp": [0, 0, 0],
        }
        frames = etl._player_frames(pos)
        self.assertEqual(len(frames), 3)
        self.assertEqual(frames[0]["msec"], 13)
        self.assertEqual(frames[2]["msec"], 13)  # last tick reuses prior delta
        self.assertAlmostEqual(frames[0]["yaw"], 90.0, places=3)
        # velocity is used directly (analyzer already finite-differenced it)
        self.assertEqual(frames[0]["velocity"], [300.0, 5.0, 0.0])


class StrafeSignTest(unittest.TestCase):
    """sign(sidemove) == -sign(yaw_rate), gated to the >=STRAFE_SIGN_GATE bhop regime."""

    def _seg(self, yaws_deg, hspeed):
        """Build a frame segment at fixed hspeed with a yaw track; onground all False."""
        v = [hspeed, 0.0, 0.0]  # vx so hypot == hspeed
        return [{"origin": [float(i), 0.0, -88.0], "velocity": list(v),
                 "yaw": float(y), "pitch": 0.0, "msec": 13} for i, y in enumerate(yaws_deg)]

    def test_left_turn_gives_positive_sidemove_in_bhop(self):
        # increasing yaw (turning left, +yaw_rate) -> sidemove negative; decreasing -> positive.
        seg = self._seg([0.0, 0.0, 5.0, 10.0, 15.0], hspeed=500.0)  # >gate, rising yaw
        og = [False] * len(seg)
        jump = [False] * len(seg)
        ep = etl._pack_episode(seg, og, jump, 0)
        rows = ep["frames"]
        # tick0: prev_yaw None -> yr 0 -> no strafe label. ticks with +yaw_rate -> side<0.
        turning = [r for r in rows if r["side"] != 0.0]
        self.assertTrue(turning, "expected at least one strafing tick")
        for r in turning:
            self.assertLess(r["side"], 0.0)  # +yaw_rate -> -sidemove (sign still recovered)
            self.assertTrue(r["is_interp"])   # interim hold-out: idm rows excluded until per-head weights
            self.assertAlmostEqual(r["confidence"], etl.STRAFE_CONF)
            self.assertEqual(abs(r["side"]), etl.SIDEMOVE_MAG)  # full-magnitude prior

    def test_right_turn_flips_sign(self):
        seg = self._seg([20.0, 15.0, 10.0, 5.0, 0.0], hspeed=500.0)  # falling yaw -> -yaw_rate
        og = [False] * len(seg)
        ep = etl._pack_episode(seg, og, [False] * len(seg), 0)
        turning = [r for r in ep["frames"] if r["side"] != 0.0]
        self.assertTrue(turning)
        for r in turning:
            self.assertGreater(r["side"], 0.0)  # -yaw_rate -> +sidemove

    def test_below_gate_is_marked_interp(self):
        # same turn but slow (below STRAFE_SIGN_GATE) -> strafe sign unreliable -> is_interp.
        seg = self._seg([0.0, 5.0, 10.0, 15.0], hspeed=200.0)  # < 400
        og = [False] * len(seg)
        ep = etl._pack_episode(seg, og, [False] * len(seg), 0)
        turning = [r for r in ep["frames"] if r["side"] != 0.0]
        self.assertTrue(turning)
        for r in turning:
            self.assertTrue(r["is_interp"])  # below gate -> excluded from training
            self.assertLess(r["confidence"], etl.STRAFE_CONF)

    def test_forwardmove_prior_and_lossless_aim(self):
        seg = self._seg([0.0, 5.0, 10.0], hspeed=500.0)
        ep = etl._pack_episode(seg, [False] * len(seg), [False] * len(seg), 0)
        for r in ep["frames"]:
            self.assertEqual(r["fwd"], etl.FORWARDMOVE_PRIOR)  # forwardmove genuinely lost
            self.assertEqual(r["cmd_yaw"], r["yaw"])           # aim lossless: cmd == view
            self.assertEqual(r["cmd_pitch"], r["pitch"])


class JumpRecoveryTest(unittest.TestCase):
    def _frames(self, vzs):
        return [{"origin": [float(i), 0.0, -88.0], "velocity": [400.0, 0.0, vz],
                 "yaw": 0.0, "pitch": 0.0, "msec": 13} for i, vz in enumerate(vzs)]

    def test_jump_on_true_to_false_transition(self):
        # grounded, grounded, then leaves ground with upward vz and stays airborne.
        og = [True, True, False, False, False]
        vzs = [0.0, 0.0, 200.0, 150.0, 100.0]
        frames = self._frames(vzs)
        jump = etl._recover_jumps(og, frames)
        # press attributed to the LAST grounded tick (index 1).
        self.assertEqual(jump, [False, True, False, False, False])

    def test_no_jump_on_single_tick_flicker(self):
        # a single airborne tick between grounded ticks (flicker) must NOT register a jump
        # (JUMP_MIN_AIR=2 requires a sustained airborne run).
        og = [True, True, False, True, True]
        vzs = [0.0, 0.0, 200.0, 0.0, 0.0]
        frames = self._frames(vzs)
        jump = etl._recover_jumps(og, frames)
        self.assertEqual(sum(jump), 0)

    def test_no_jump_on_ledge_fall_without_upward_intent(self):
        # leaves ground but falling (vz<=0) -> a ledge step-off, not a jump.
        og = [True, True, False, False, False]
        vzs = [0.0, 0.0, -50.0, -80.0, -120.0]
        frames = self._frames(vzs)
        jump = etl._recover_jumps(og, frames)
        self.assertEqual(sum(jump), 0)

    def test_jump_encodes_buttons_and_upmove(self):
        seg = [{"origin": [float(i), 0.0, -88.0], "velocity": [400.0, 0.0, 0.0],
                "yaw": 0.0, "pitch": 0.0, "msec": 13} for i in range(4)]
        og = [True, True, False, False]
        jump = [False, True, False, False]
        ep = etl._pack_episode(seg, og, jump, 0)
        r = ep["frames"][1]
        self.assertTrue(r["buttons"] & etl.BUTTON_JUMP)
        self.assertEqual(r["up"], etl.SIDEMOVE_MAG)
        self.assertEqual(ep["frames"][0]["buttons"], 0)


class OngroundProberEarlyOutTest(unittest.TestCase):
    def test_recover_onground_uses_geometry_and_vz_earlyout(self):
        # _recover_onground calls prober.onground(origin, vz). The fake honors the
        # vz>MAXGROUNDSPEED early-out: a fast-rising frame is forced airborne even when the
        # geometry flag says grounded.
        frames = [
            {"origin": [0.0, 0.0, 0.0], "velocity": [0.0, 0.0, 0.0], "yaw": 0, "pitch": 0, "msec": 13},
            {"origin": [0.0, 0.0, 0.0], "velocity": [0.0, 0.0, 300.0], "yaw": 0, "pitch": 0, "msec": 13},
        ]
        prober = _FakeProber([True, True])  # geometry says grounded both ticks
        og = etl._recover_onground(frames, prober)
        self.assertEqual(og[0], True)
        self.assertEqual(og[1], False)  # vz 300 > 180 -> forced airborne


class SchemaGuardTest(unittest.TestCase):
    def test_schema21_shaped_dict_hard_fails(self):
        # schema 21: pos has only {t,x,y,z,li} -> must raise.
        bad = {"schemaVersion": 21,
               "streams": {"players": [{"pos": {"t": [0], "x": [0], "y": [0], "z": [0], "li": [0]}}]}}
        with self.assertRaises(ValueError) as cm:
            etl._validate_analysis(bad, "demo21.mvd")
        self.assertIn("schema", str(cm.exception).lower())

    def test_schema33_missing_velocity_fields_hard_fails(self):
        bad = {"schemaVersion": 33,
               "streams": {"players": [{"pos": {"t": [0], "x": [0], "y": [0], "z": [0], "li": [0]}}]}}
        with self.assertRaises(ValueError) as cm:
            etl._validate_analysis(bad, "demo33.mvd")
        self.assertIn("vya", str(cm.exception))

    def test_valid_schema33_passes(self):
        good = {"schemaVersion": 33,
                "streams": {"players": [{"pos": {
                    "t": [0], "x": [0], "y": [0], "z": [0], "li": [0],
                    "vp": [0], "vya": [0], "vx": [0], "vy": [0], "vz": [0]}}]}}
        etl._validate_analysis(good, "demo_ok.mvd")  # must not raise


class ManifestTest(unittest.TestCase):
    def _load(self, manifest):
        import json
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(manifest, fh)
            p = Path(fh.name)
        try:
            return etl.load_manifest(p)
        finally:
            p.unlink()

    def test_explicit_train_only_and_carries_content_lock(self):
        sha = "a" * 64
        manifest = {"schema": "v3", "demos": [
            {"path": "/a/train1.mvd", "class": "TRAIN", "sha256": sha, "size_bytes": 10},
            {"path": "/a/holdout.mvd", "class": "HOLDOUT", "sha256": sha, "size_bytes": 10},
            {"path": "/a/train2.mvd", "classification": "TRAIN", "sha256": sha.upper(), "size_bytes": 20},
        ]}
        out = self._load(manifest)
        self.assertEqual([e["path"] for e in out], ["/a/train1.mvd", "/a/train2.mvd"])
        self.assertEqual(out[0]["sha256"], sha)            # carried
        self.assertEqual(out[1]["sha256"], sha)            # normalized to lowercase
        self.assertEqual(out[0]["size_bytes"], 10)

    def test_missing_class_is_rejected_not_defaulted_to_train(self):
        # the old bug: a row with no class was silently treated as TRAIN. It must now be REJECTED.
        out = self._load({"demos": [{"abspath": "/a/noclass.mvd", "sha256": "b" * 64, "size_bytes": 5}]})
        self.assertEqual(out, [])


class ProvenanceVerifyTest(unittest.TestCase):
    def test_extract_demo_flags_sha_mismatch(self):
        import tempfile
        with tempfile.NamedTemporaryFile("wb", suffix=".mvd", delete=False) as fh:
            fh.write(b"not a real demo")
            p = fh.name
        try:
            r = etl.extract_demo(p, "/nonexistent-qwa", "/nonexistent-bsp", expected_sha256="f" * 64)
        finally:
            os.unlink(p)
        self.assertFalse(r["ok"])
        self.assertTrue(r.get("sha_mismatch"))
        self.assertIn("SHA_MISMATCH", r["error"])


class HoldoutInvariantTest(unittest.TestCase):
    """Anti-poisoning: until per-head weights exist, EVERY idm row is held out of training."""

    def _seg(self, yaws_deg, hspeed):
        v = [hspeed, 0.0, 0.0]
        return [{"origin": [float(i), 0.0, -88.0], "velocity": list(v),
                 "yaw": float(y), "pitch": 0.0, "msec": 13} for i, y in enumerate(yaws_deg)]

    def test_all_rows_held_out_regardless_of_gate(self):
        for hspeed in (200.0, 500.0):  # below and above the strafe-sign gate
            seg = self._seg([0.0, 5.0, 10.0, 15.0], hspeed)
            ep = etl._pack_episode(seg, [False] * len(seg), [False] * len(seg), 0)
            self.assertTrue(all(r["is_interp"] for r in ep["frames"]),
                            "every idm row must be is_interp=True (no move head trains)")


class SplitTest(unittest.TestCase):
    def test_group_by_demo_split_shape(self):
        labels = etl.assign_splits(10)
        self.assertEqual(len(labels), 10)
        self.assertIn("train", labels)
        self.assertIn("val", labels)
        self.assertIn("test", labels)


if __name__ == "__main__":
    unittest.main()
