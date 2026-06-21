"""ml/tests/test_dagger_loop.py -- tests for the DAgger D-2 DRIVER (ml/dagger/dagger_loop).

The driver owns rollout-capture (STEP 1, torch), relabel (STEP 2, pure) and aggregate/shard-
write (STEP 3, pyarrow+numpy). The torch rollout is exercised on pinnacle (not in CI); these
tests cover the parts that run deps-light:

  (A) RELABEL IS THE EXPERT, CONTRACT-SHAPED -- relabel_record turns a captured over-press
      visited state into the v5 `act` target the D-1.5 expert presses, via the CANONICAL
      agent_observation.encode_action (so the relabel target is byte-identical in shape to a
      human label). The over-press air state must relabel to fwd+side pressed (the diagonal
      air-strafe), NOT the bulldoze, and the row width must be ACT_DIM. Pure stdlib.
  (B) OVER-PRESS FLAGGING -- the OVERPRESS_FWD threshold is 0.9*MOVE_MAG (the same the
      diagnostic dump used); a fwd=MOVE_MAG press is flagged, a released fwd is not.
  (C) THE WRITTEN SHARD PASSES THE CONTRACT + ROUND-TRIPS (pyarrow+numpy) -- write_relabel_shard
      stamps the v5 metadata (registry_version 5, obs_dim 21, self_history_dim 336, act_dim 5)
      and the shard-contract guards (check_shard_meta + require_self_history_present) ACCEPT it;
      the REAL loader (core.read_shard) reads it back with the v5 widths intact. This is the
      proof the trainer will consume the relabel shard with no code change.

Pure stdlib for (A)/(B); (C) is skipped unless pyarrow+numpy are present (the ml-tests CI has
them; aws-dev's bare-stdlib floor skips it). No torch anywhere here.
"""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ML = HERE.parent
REPO_ROOT = ML.parent
for _p in (str(ML), str(ML / "dagger"), str(ML / "pipeline"), str(REPO_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from dagger import dagger_loop as DL          # noqa: E402  (the driver under test)
from dagger import expert as EX               # noqa: E402
from broad_bc import shard_contract as SC     # noqa: E402

_HAVE_NUMPY = importlib.util.find_spec("numpy") is not None
_HAVE_PYARROW = importlib.util.find_spec("pyarrow") is not None


def _overpress_air_record(tick=5):
    """A captured visited record in the exact shape run_policy_rollout's obs_capture emits,
    for an AIRBORNE over-press state (fwd bulldoze) drifting toward a goal -- the off-manifold
    covariate DAgger must relabel."""
    return {
        "tick": tick,
        "self_in": [0.0] * SC.EXPECTS_SELF_HISTORY_DIM,        # 336 (values irrelevant to relabel)
        "ents": [[0.0] * 13 for _ in range(7)],                # n_max=7, ENT=13 (solo-roam pad)
        "mask": [0.0] * 7,
        "ox": 100.0, "oy": 200.0, "oz": 24.0,
        "vx": -21.2, "vy": -345.0, "vz": 0.0,                  # ~346 qu/s airborne
        "onground": False,
        "goal": [500.0, 800.0, 24.0],
        "pol_fwd": EX.MOVE_MAG, "pol_side": 0.0,               # the bulldoze (fwd full, no strafe)
        "pol_up": 0.0, "pol_jump": 0,
    }


class RelabelTests(unittest.TestCase):
    def test_relabel_is_expert_diagonal_not_bulldoze(self):
        """(A) the over-press air state relabels to the expert's DIAGONAL air-strafe
        (fwd pressed AND side pressed), the v5 act target, width ACT_DIM."""
        rec = _overpress_air_record()
        act = DL.relabel_record(rec)
        self.assertEqual(len(act), len(SC.head_names()),
                         "relabel row must be ACT_DIM wide (fwd/side/up/jump/attack)")
        # the D-1.5 expert presses a forward COMPONENT + a strafe side in the air (the
        # diagonal that nets goal progress; NOT the strict-perp fwd=0 D-1 orbiter, and NOT
        # the policy's side=0 bulldoze).
        self.assertGreater(act[0], 0.0, "expert presses a forward component (diagonal)")
        self.assertNotEqual(act[1], 0.0, "expert presses a strafe side (air-strafe)")
        self.assertEqual(act[4], 0.0, "attack is not driven by the movement expert")
        # the target is the canonical [-1,1] move space (|.| <= 1), like a human label.
        self.assertLessEqual(abs(act[0]), 1.0)
        self.assertLessEqual(abs(act[1]), 1.0)

    def test_relabel_side_alternates_with_weave(self):
        """the L/R weave (orbit-killer) flips the relabel side sign across a weave period --
        consecutive-period ticks get opposite strafe sides (so the aggregated targets teach
        the alternation, not a fixed side that circles)."""
        per = EX.WEAVE_PERIOD_TICKS
        a0 = DL.relabel_record(_overpress_air_record(tick=0))           # first period
        a1 = DL.relabel_record(_overpress_air_record(tick=per))         # next period
        self.assertEqual(a0[1] * a1[1] < 0.0, True,
                         "relabel side sign must alternate L/R across the weave period")

    def test_overpress_threshold(self):
        """(B) OVERPRESS_FWD == 0.9*MOVE_MAG; a full fwd press is over-press, a release is not."""
        self.assertAlmostEqual(DL.OVERPRESS_FWD, 0.9 * EX.MOVE_MAG)
        self.assertTrue(EX.MOVE_MAG > DL.OVERPRESS_FWD)                 # bulldoze flagged
        self.assertFalse(0.0 > DL.OVERPRESS_FWD)                       # released not flagged

    def test_relabel_all_preserves_obs(self):
        """relabel_all KEEPS the captured obs (self_in/ents/mask) and pairs it with the
        expert act -- the DAgger invariant (same obs, corrected action)."""
        recs = [_overpress_air_record(tick=t) for t in (0, 3, 7)]
        pairs = DL.relabel_all(recs)
        self.assertEqual(len(pairs), 3)
        for (self_in, ents, mask, act), rec in zip(pairs, recs):
            self.assertEqual(self_in, rec["self_in"])                  # obs preserved verbatim
            self.assertEqual(mask, rec["mask"])
            self.assertEqual(len(act), len(SC.head_names()))


@unittest.skipUnless(_HAVE_PYARROW and _HAVE_NUMPY, "pyarrow/numpy not installed")
class ShardWriteTests(unittest.TestCase):
    def test_relabel_shard_passes_contract_and_roundtrips(self):
        """(C) the written relabel shard stamps the v5 contract, the guards ACCEPT it, and the
        REAL loader reads it back with the v5 widths intact."""
        recs = [_overpress_air_record(tick=t) for t in range(20)]
        pairs = DL.relabel_all(recs)
        with tempfile.TemporaryDirectory() as d:
            norm_p = Path(d) / "norm.json"
            # a minimal v5 norm artifact carrying the required yaw_rate key + registry 5
            norm_p.write_text(
                '{"artifact_version":"0.5.0-test","registry_version":5,'
                '"per_map":{"dm3":{"yaw_rate":{"mean":0.0,"std":1.0}}}}',
                encoding="utf-8")
            out_p = Path(d) / "relabel_dagger.parquet"
            manifest = DL.write_relabel_shard(pairs, out_p, norm_p, demo_id=990000)
            # the guard the trainer/loader run MUST accept the relabel shard
            self.assertTrue(manifest["guard"]["accepted"],
                            f"shard guard rejected: {manifest['guard']}")
            self.assertEqual(manifest["dims"]["self_history_dim"],
                             SC.EXPECTS_SELF_HISTORY_DIM)
            self.assertEqual(manifest["dims"]["obs"], SC.EXPECTS_SELF_DIM)
            self.assertEqual(manifest["dims"]["act_dim"], len(SC.head_names()))
            # round-trip through the REAL loader
            rt = DL.verify_shard_roundtrips(out_p)
            self.assertTrue(rt["roundtrip_ok"], f"roundtrip failed: {rt}")
            self.assertEqual(rt["registry_version"], SC.EXPECTS_REGISTRY_VERSION)
            self.assertEqual(rt["self_history_dim"], SC.EXPECTS_SELF_HISTORY_DIM)
            self.assertEqual(rt["n_windows"], len(pairs))


if __name__ == "__main__":
    unittest.main()
