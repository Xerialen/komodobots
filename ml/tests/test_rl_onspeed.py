"""ml/tests/test_rl_onspeed.py — regression tests for the PPO-on-speed RL loop
(ml/rl_onspeed.py). Two Codex-found correctness bugs, each pinned by a focused
fails-before / passes-after test:

  * Finding 1 [High]: the PPO log-prob head set. collect_rollout stored old_logp summed
    over ALL discrete heads INCLUDING attack, but ppo_update recomputed new_logp over only
    fwd/side/up/jump — so for an UNCHANGED policy the joint ratio became 1/p_attack
    (e.g. 5.0 / 2.0 / 1.25 at p_attack 0.2 / 0.5 / 0.8) instead of 1.0, and approx_kl was
    nonzero. The fix routes BOTH old and new through discrete_joint_logp (executed heads
    only). The test drives the REAL collect_rollout + the real recompute and asserts the
    unchanged-policy ratio == 1.0 (and approx_kl == 0) across attack probabilities.

  * Finding 3 [Medium] (ported to #427's arc-length progress): the reward carry (self._rstate)
    is rebuilt each _reset_state, re-seeding prev_arc to the NEW segment's start arc, so the
    first r_prog after a reset reflects only the bot's own movement, not a stale cross-segment
    arc. The test resets twice to different straight routes and asserts the first post-reset
    step's arc-length progress is the bot's +5qu stub move (+0.1), not a jump.

These need torch (RLPolicy/BroadBCPolicy + Categorical) so they are torch-GATED here in
ml/tests (the deps-heavy subtree), NOT in the stdlib-only merge-gate tests/. They build a
TINY policy + a STUB env (no checkpoint / catalog / BSP needed) so the binding correctness
check runs anywhere torch is importable (the ml-tests CI job installs torch via
ml/requirements-ci.txt for exactly this).
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


@unittest.skipUnless(_HAVE_TORCH, "torch required for the RL PPO/env regression tests")
class TestPPOLogProbHeadParity(unittest.TestCase):
    """Finding 1: old_logp (collect_rollout) and new_logp (ppo_update) MUST sum over the
    SAME executed discrete heads (fwd/side/up/jump), excluding the sampled-but-discarded
    attack head. For an UNCHANGED policy the joint PPO ratio must be 1.0 exactly."""

    def _build_policy(self, attack_p_class1):
        """A tiny RLPolicy whose attack head emits FIXED logits giving a known probability
        `attack_p_class1` to attack class 1 (so the sampled attack log-prob is a known
        constant, making the buggy ratio a deterministic 1/p). Everything else is the
        ordinary v5 BroadBCPolicy(yaw_head=True)."""
        import torch
        from train_broad_bc import BroadBCPolicy
        import rl_onspeed as RL
        torch.manual_seed(0)
        self_dim = 21
        base = BroadBCPolicy(f_obs=self_dim, f_ent=0, f_aux=0, n_max=1,
                             self_dim=self_dim, yaw_head=True)
        # Pin the attack head (head index 4, 2-way) to constant logits regardless of input:
        # zero its weight so only the bias matters, and set the bias to the logits that yield
        # P(class1)=attack_p_class1 (=> P(class0)=1-p). The attack SAMPLE then has a known,
        # input-independent probability, so the old (5-head) vs new (4-head) mismatch shows
        # up as a clean ratio = 1/p_attack(sampled).
        with torch.no_grad():
            base.heads[4].weight.zero_()
            logit1 = math.log(attack_p_class1 / (1.0 - attack_p_class1))
            base.heads[4].bias.copy_(torch.tensor([0.0, float(logit1)]))
        rl = RL.RLPolicy(base)
        rl.eval()
        return rl

    def _stub_env(self, self_dim=21, msec=13):
        """A minimal env with the PmoveEnv interface collect_rollout drives: reset() ->
        (self_in[self_dim], ents[], mask[], msec); step(...) -> (obs, reward, done, info)
        with the info keys collect_rollout reads. No pmove/BSP/catalog needed — the PPO
        log-prob accounting is independent of the reward/dynamics."""
        class _Env:
            def __init__(self):
                self.t = 0

            def _obs(self):
                # f_ent=0 -> empty ents/mask; self_in is a flat [self_dim] vector.
                return ([0.05 * (i % 7) for i in range(self_dim)], [], [], msec)

            def reset(self):
                self.t = 0
                return self._obs()

            def step(self, fwd, side, up, jump, yaw, m, fwd_argmax=None, side_argmax=None):
                self.t += 1
                info = {"hspeed": 100.0, "onground": False, "fwd_press": int(fwd == 2),
                        "r_vel": 0.0, "v_along": 0.0, "r_phi": 0.0, "r_prog": 0.0,
                        "p_hack": 0.0, "r_cad": 0.0, "r_press": 0.0, "strafe_sign": 0,
                        "perp_frac": 0.0, "r_strafe": 0.0, "ap_rate": 0.0, "p_collide": 0.0}
                return self._obs(), 0.0, False, info
        return _Env()

    def _unchanged_ratio_and_kl(self, attack_p_class1):
        """Run the REAL collect_rollout (produces old_logp), then recompute new_logp the
        way ppo_update does on the SAME unchanged weights, and form the joint PPO ratio +
        approx_kl. Returns (max|ratio-1|, mean ratio, |approx_kl|)."""
        import torch
        import rl_onspeed as RL
        rl = self._build_policy(attack_p_class1)
        envs = [self._stub_env() for _ in range(3)]
        torch.manual_seed(123)
        roll = RL.collect_rollout(envs, rl, "cpu", n_steps=8)

        # flatten exactly like ppo_update
        obs = torch.cat(roll["obs"], dim=0)
        ent = torch.cat(roll["ent"], dim=0)
        em = torch.cat(roll["em"], dim=0)
        aux = torch.zeros((obs.shape[0], 0))
        old_logp = torch.cat(roll["logp"], dim=0)
        old_yaw = torch.cat(roll["yaw"], dim=0)
        old_yawlogp = torch.cat(roll["yawlogp"], dim=0)
        acts = {nm: torch.cat(roll["act"][nm], dim=0) for nm in roll["act"]}

        # recompute on the UNCHANGED policy, mirroring ppo_update's recompute
        with torch.no_grad():
            logits, yaw_mean, _ = rl(obs, ent, em, aux)
            dists = [torch.distributions.Categorical(logits=lg) for lg in logits]
            head_names = ("fwd", "side", "up", "jump")
            mb_acts = [acts[nm] for nm in head_names]
            new_logp = RL.discrete_joint_logp(dists, mb_acts)
            yaw_std = rl.yaw_log_std.exp().clamp(min=1e-2)
            new_yawlogp = (-0.5 * ((old_yaw - yaw_mean) / yaw_std) ** 2
                           - rl.yaw_log_std - 0.5 * math.log(2 * math.pi))
            ratio = torch.exp((new_logp + new_yawlogp) - (old_logp + old_yawlogp))
            approx_kl = (old_logp - new_logp).mean()
        return (float((ratio - 1.0).abs().max()), float(ratio.mean()), float(approx_kl.abs()))

    def test_unchanged_policy_ratio_is_one(self):
        # For an unchanged policy the FULL joint-action ratio must be 1.0 (and approx_kl 0)
        # at every attack probability. Under the bug (old over 5 heads, new over 4) the ratio
        # would be 1/p_attack — these asserts FAIL before the fix, PASS after.
        for p in (0.2, 0.5, 0.8):
            max_err, mean_ratio, kl = self._unchanged_ratio_and_kl(p)
            self.assertLess(max_err, 1e-5,
                            f"p_attack={p}: ratio deviates from 1.0 (max|r-1|={max_err}); "
                            f"old_logp/new_logp head sets disagree")
            self.assertAlmostEqual(mean_ratio, 1.0, places=5,
                                   msg=f"p_attack={p}: mean ratio {mean_ratio} != 1.0")
            self.assertLess(kl, 1e-5, f"p_attack={p}: approx_kl {kl} != 0 for unchanged policy")

    def test_discrete_joint_logp_excludes_attack(self):
        # The shared helper must sum over EXACTLY the executed heads (PPO_ACTION_HEADS=4),
        # so a 5-head dists list yields the SAME log-prob as its first 4 heads.
        import torch
        import rl_onspeed as RL
        self.assertEqual(RL.PPO_ACTION_HEADS, 4)
        torch.manual_seed(1)
        dists = [torch.distributions.Categorical(logits=torch.randn(5, k))
                 for k in (3, 3, 3, 2, 2)]
        acts = [torch.zeros(5, dtype=torch.long) for _ in range(5)]
        full = RL.discrete_joint_logp(dists, acts)
        manual4 = sum(d.log_prob(a) for d, a in zip(dists[:4], acts[:4]))
        self.assertTrue(torch.allclose(full, manual4))
        # and it must DIFFER from a (buggy) 5-head sum whenever the attack log-prob is nonzero
        five = sum(d.log_prob(a) for d, a in zip(dists, acts))
        self.assertFalse(torch.allclose(full, five))


@unittest.skipUnless(_HAVE_TORCH, "torch required for the RL env reset regression test")
class TestResetArcProgressNeutral(unittest.TestCase):
    """Finding 3, ported to #427: after a reset to a NEW segment the first step's arc-length
    progress (r_prog) must reflect only the bot's own movement, not a jump from a stale
    cross-segment arc. _reset_state rebuilds the reward carry (self._rstate), re-seeding
    prev_arc to the new segment's start arc — this pins that."""

    def _make_env(self):
        """A PmoveEnv with pmove/run_frame stubbed out (no BSP) and two straight +x reference
        routes at DIFFERENT absolute positions (distinct per-tick origins => non-degenerate
        polyline so projection/arc-length work). Only the reset/reward-carry bookkeeping runs."""
        import rl_onspeed as RL

        # A straight +x human-reference route of n vertices 100qu apart, starting at x0. A segment
        # is a list of tick dicts; only ["self"] (origin/velocity/yaw) + ["act"]["msec"] are read.
        def seg(x0, n=6, dx=100.0):
            return [{"self": {"ox": x0 + k * dx, "oy": 0.0, "oz": 0.0, "vx": 320.0, "vy": 0.0,
                              "vz": 0.0, "yaw": 0.0, "goal": [x0 + (n - 1) * dx, 0.0]},
                     "act": {"msec": 13}} for k in range(n)]
        segments = [(0, 0, seg(0.0)), (1, 0, seg(1000.0))]   # seg0 @x=0..500, seg1 @x=1000..1500

        env = RL.PmoveEnv.__new__(RL.PmoveEnv)        # bypass __init__ (no world/BSP)
        env.world = None
        env.stats = {}
        env.segments = segments
        env.n_max = 1
        env.map_name = "dm3"
        env.horizon = 5
        env.air_press_thresh = 0.40                   # _reset_state seeds the carry's ap_rate from this
        env._rcfg = dict(RL.RW.DEFAULT_WEIGHTS)        # __init__ (bypassed here) normally builds this

        # deterministic segment selection: first reset -> seg0, second -> seg1.
        class _SeqRNG:
            def __init__(self, seq):
                self.seq, self.i = seq, 0

            def randint(self, _n):
                v = self.seq[self.i % len(self.seq)]
                self.i += 1
                return v
        env.rng = _SeqRNG([0, 1])

        # stub pmove: a frame that moves the origin a small fixed step ALONG the route (+x) and
        # keeps the bot airborne — no real physics needed for the arc-progress check.
        class _StubPm:
            def run_frame(self, st, cmd):
                st.origin[0] += 5.0          # 5qu along the +x route per tick
                st.onground = False
        env.pm = _StubPm()

        # build_obs touches the obs encoder; stub it so the reset/step bookkeeping is isolated.
        env._build_obs = lambda: ([0.0], [], [], 13)
        return env, RL

    def test_first_step_arc_progress_neutral_after_each_reset(self):
        # Drives the REAL reset()+step() twice across DIFFERENT routes. The +0.1 expected value is
        # the 5qu the stub moves along the route per tick (+5 / prog_scale 50), the ONLY legitimate
        # progress on step 1. A stale carried-over arc would make the post-reset first r_prog jump.
        env, RL = self._make_env()

        # reset #1 -> seg0 (start arc 0). First step's r_prog is the +5qu move.
        env.reset()
        _, _, _, info1 = env.step(1, 1, 1, 0, 0.0, 13)   # no-yaw, neutral move keys
        self.assertAlmostEqual(info1["r_prog"], 0.1, places=3)
        for _ in range(3):                                # advance so prev_arc is well past 0
            env.step(1, 1, 1, 0, 0.0, 13)

        # reset #2 -> seg1 (a DIFFERENT route, start arc 0). The rebuilt carry must re-seed
        # prev_arc to ~0 (this segment's start), so the first step is again the +5qu move (+0.1),
        # not a jump computed against seg0's accumulated arc.
        env.reset()
        self.assertAlmostEqual(env._rstate["prev_arc"], 0.0, places=1,
                               msg="reset did not re-seed the reward carry's prev_arc")
        _, _, _, info2 = env.step(1, 1, 1, 0, 0.0, 13)
        self.assertAlmostEqual(info2["r_prog"], 0.1, places=3,
                               msg="first arc-progress after reset to a new route is polluted by "
                                   "the previous route's arc")
        self.assertGreaterEqual(info2["r_prog"], 0.0,
                                "first post-reset r_prog must not be a large negative from a "
                                "stale (previous-segment) arc")


if __name__ == "__main__":
    unittest.main()
