"""ml/tests/test_rl_baseline_smoke.py — T3.2 (#423) D2: the RL-loop PLUMBING smoke.

Proves the baseline PPO loop CLOSES on a degenerate, artifact-free world (no BSP / checkpoint /
catalog): state -> action -> NAIVE reward -> PPO update, with no NaN and a checkpoint written; plus
a stdlib-math check that the baseline reward is +ve for forward motion, -/0 otherwise.

torch-GATED (skipped where torch is absent, e.g. aws-dev) and NON-gating: it lives in ml/tests/
(the deps-heavy subtree run by ml-tests.yml), NOT the stdlib merge-gate `tests/`. rl_onspeed imports
torch/numpy at module top, so every import of it is done INSIDE a test method, after the skip.
"""
import importlib.util
import math
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ML = HERE.parent
REPO_ROOT = ML.parent
for p in (str(ML), str(REPO_ROOT / "scripts"), str(ML / "pipeline")):
    if p not in sys.path:
        sys.path.insert(0, p)

_HAVE_TORCH = importlib.util.find_spec("torch") is not None


@unittest.skipUnless(_HAVE_TORCH, "torch required for the RL baseline-smoke loop")
class TestBaselineRewardMath(unittest.TestCase):
    """The naive reward = horizontal displacement projected on the view-facing direction:
    +ve forward, -ve backward, 0 for no/perpendicular motion. Exact stdlib-math checks."""

    def test_forward_is_positive(self):
        import rl_onspeed as RL
        # facing +x, moved +10 in x -> +10
        self.assertAlmostEqual(RL.baseline_forward_reward((0.0, 0.0), (10.0, 0.0), 0.0), 10.0, 6)
        # facing +y (yaw 90), moved +7 in y -> +7
        self.assertAlmostEqual(RL.baseline_forward_reward((0.0, 0.0), (0.0, 7.0), 90.0), 7.0, 6)

    def test_backward_is_negative(self):
        import rl_onspeed as RL
        self.assertLess(RL.baseline_forward_reward((0.0, 0.0), (-10.0, 0.0), 0.0), 0.0)

    def test_no_or_perpendicular_motion_is_zero(self):
        import rl_onspeed as RL
        # no motion -> 0
        self.assertAlmostEqual(RL.baseline_forward_reward((3.0, 3.0), (3.0, 3.0), 45.0), 0.0, 9)
        # facing +x but moved purely sideways (+y) -> projection 0 (not "forward")
        self.assertAlmostEqual(RL.baseline_forward_reward((0.0, 0.0), (0.0, 5.0), 0.0), 0.0, 6)


@unittest.skipUnless(_HAVE_TORCH, "torch required for the RL baseline-smoke loop")
class TestSmokeLoopCloses(unittest.TestCase):
    """The PPO loop closes on the degenerate smoke world with finite losses + a ckpt write, under
    BOTH the naive baseline reward and the real round-6 reward (the latter must not be broken)."""

    def _assert_closed(self, res):
        self.assertTrue(res["ckpt_written"], "smoke did not write a checkpoint")
        for k in ("mean_reward", "pg", "vf"):
            self.assertTrue(math.isfinite(res[k]), f"{k} not finite: {res[k]}")
        self.assertEqual(res["f_obs"], 336)        # v5 self-history obs flowed through the loop

    def test_smoke_closes_with_baseline_reward(self):
        import rl_onspeed as RL
        self._assert_closed(RL.run_smoke("cpu", baseline_reward=True, n_iters=2))

    def test_smoke_closes_with_round6_reward(self):
        import rl_onspeed as RL
        self._assert_closed(RL.run_smoke("cpu", baseline_reward=False, n_iters=2))

    def test_smoke_cli_runs_with_zero_data_args(self):
        # the advertised artifact-free CLI: `rl_onspeed --smoke` must parse + run with NO
        # --db/--bsp/--norm-artifact/--anchors/--init-ckpt (regression for the required=True bug
        # that argparse rejected before the smoke branch). main() returns 0 on success.
        import rl_onspeed as RL
        self.assertEqual(RL.main(["--smoke", "--cpu"]), 0)
        self.assertEqual(RL.main(["--smoke", "--cpu", "--baseline-reward"]), 0)

    def test_smoke_ckpt_reloads_via_shared_loader(self):
        # the smoke ckpt must satisfy the repo's checkpoint contract: a REAL round-trip through the
        # shared load_rl_policy (the train/eval path), not just file-exists. Regression for dims
        # passed as a list (the loader reads dims["f_obs"] etc., a NAMED dict).
        import tempfile
        import rl_onspeed as RL
        with tempfile.NamedTemporaryFile(suffix="_smoke.pt", delete=False) as tf:
            ckpt = Path(tf.name)
        try:
            res = RL.run_smoke("cpu", baseline_reward=True, n_iters=1, out_ckpt=str(ckpt))
            self.assertTrue(res["ckpt_written"])
            rl, _anchor, _ckpt, dims, _head_dims = RL.load_rl_policy(ckpt, "cpu")
            self.assertEqual(dims["f_obs"], 336)
            self.assertIsNotNone(rl)
        finally:
            ckpt.unlink(missing_ok=True)


@unittest.skipUnless(_HAVE_TORCH, "torch required for the RL baseline-smoke loop")
class TestEnvStepWiresBaseline(unittest.TestCase):
    """PmoveEnv.step must RETURN the naive reward (== info['r_baseline']) when baseline_reward is
    set, and the round-6 diagnostics must still populate info either way."""

    def _make_env(self, baseline):
        import rl_onspeed as RL
        world = RL.build_smoke_world()
        segs = RL.build_smoke_segments()
        return RL.PmoveEnv(world, RL._SMOKE_STATS, segs, n_max=2, horizon=20, seed=7,
                           baseline_reward=baseline)

    def test_step_returns_baseline_when_flagged(self):
        env = self._make_env(True)
        env.reset()
        _obs, reward, _done, info = env.step(2, 1, 1, 0, 0.0, 13)   # press fwd, neutral side/up
        self.assertIn("r_baseline", info)
        self.assertTrue(math.isfinite(reward))
        self.assertAlmostEqual(reward, info["r_baseline"], places=6)
        # the physics diagnostics the rollout reads are still present + finite
        for k in ("hspeed", "fwd_press", "r_cad", "r_press"):
            self.assertIn(k, info)

    def test_step_uses_round6_when_not_flagged(self):
        env = self._make_env(False)
        env.reset()
        _obs, reward, _done, info = env.step(2, 1, 1, 0, 0.0, 13)
        self.assertTrue(math.isfinite(reward))
        self.assertIn("r_baseline", info)          # still reported, just not used as the reward


if __name__ == "__main__":
    unittest.main()
