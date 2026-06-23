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

  * Finding 3 [Medium]: _reset_state never (re)initialized _prev_goal_dist, so the first
    r_prog after a reset to a NEW segment was computed against the PREVIOUS segment's goal
    distance. The test resets twice to different segments and asserts the first post-reset
    step's route-progress reward is neutral (0.0).

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
                        "r_speed": 0.0, "r_phi": 0.0, "r_prog": 0.0, "p_hack": 0.0,
                        "r_cad": 0.0, "r_press": 0.0, "strafe_sign": 0,
                        "perp_frac": 0.0, "r_strafe": 0.0, "ap_rate": 0.0}
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
class TestResetGoalDistNeutral(unittest.TestCase):
    """Finding 3: after a reset to a NEW segment, the first step's route-progress reward
    must be neutral (0.0), not polluted by the PREVIOUS segment's goal distance."""

    def _make_env(self):
        """A PmoveEnv with pmove/run_frame stubbed out (no BSP) and two segments whose final
        goals are FAR apart, so a stale _prev_goal_dist would make the first post-reset r_prog
        large. Only the reset/goal-distance bookkeeping is exercised."""
        import numpy as np
        import rl_onspeed as RL

        # two segments: distinct start origins + distinct final goals (far apart). A segment is
        # a list of tick dicts; only ["self"] (origin/velocity/yaw/goal) + ["act"]["msec"] read.
        def seg(ox, oy, gx, gy, n=6):
            return [{"self": {"ox": ox, "oy": oy, "oz": 0.0, "vx": 320.0, "vy": 0.0,
                              "vz": 0.0, "yaw": 0.0, "goal": [gx, gy]},
                     "act": {"msec": 13}} for _ in range(n)]
        segments = [
            (0, 0, seg(0.0, 0.0, 100.0, 0.0)),       # near goal: starts 100qu away
            (1, 0, seg(0.0, 0.0, 5000.0, 0.0)),      # far goal: starts 5000qu away
        ]

        env = RL.PmoveEnv.__new__(RL.PmoveEnv)        # bypass __init__ (no world/BSP)
        env.world = None
        env.stats = {}
        env.segments = segments
        env.n_max = 1
        env.map_name = "dm3"
        env.horizon = 5
        env.band_lo, env.band_hi = 252.0, 316.0
        env.cad_hold_min, env.cad_hold_max, env.cad_hold_late = 14, 230, 240
        env.air_press_thresh = 0.40
        env.ap_rate_ema = 0.02
        env.r_cad_weight = 1.0

        # deterministic segment selection: first reset -> seg0 (near), second -> seg1 (far).
        class _SeqRNG:
            def __init__(self, seq):
                self.seq, self.i = seq, 0

            def randint(self, _n):
                v = self.seq[self.i % len(self.seq)]
                self.i += 1
                return v
        env.rng = _SeqRNG([0, 1])

        # stub pmove: a frame that moves the origin a small fixed step along +x and keeps the
        # bot airborne (so the air branch runs) — no real physics needed for the r_prog check.
        class _StubPm:
            def run_frame(self, st, cmd):
                st.origin[0] += 5.0          # 5qu toward the (far +x) goal per tick
                st.onground = False
        env.pm = _StubPm()

        # build_obs touches AO.encode_observation/_self_state_from_sim; stub _build_obs so the
        # reset/step bookkeeping is isolated from the obs encoder (not under test here).
        env._build_obs = lambda: ([0.0], [], [], 13)
        return env, RL

    def test_first_step_rprog_neutral_after_each_reset(self):
        # Drives the REAL reset()+step() twice across DIFFERENT segments. The bug shows up on
        # the SECOND reset: production step() reads d_prev via getattr(self,"_prev_goal_dist",
        # d_now), so the very first reset+step is incidentally neutral (getattr fallback), but
        # after that step the attribute persists; on the next reset _reset_state must re-seed
        # it to the NEW segment's start distance or the next first-step r_prog is computed
        # against the PREVIOUS segment's goal. The +0.1 expected value is the 5qu the stub
        # moves toward the goal per tick (+5/50), the ONLY legitimate progress on step 1.
        env, RL = self._make_env()

        # reset #1 -> near-goal segment (start dist 100). First step's r_prog is the +5qu step.
        env.reset()
        _, _, _, info1 = env.step(1, 1, 1, 0, 0.0, 13)   # no-yaw, neutral move keys
        self.assertAlmostEqual(info1["r_prog"], 0.1, places=3)

        # reset #2 -> FAR-goal segment (start dist 5000). After reset _prev_goal_dist must be
        # re-seeded to 5000 (this segment's start dist), so the first step's r_prog is again
        # the +5qu stub step (+0.1). Under the bug _prev_goal_dist still holds the near
        # segment's last distance (~95), so the first r_prog is (95 - 4995)/50 clamped to -1.0
        # — the pollution this regression pins.
        env.reset()
        self.assertAlmostEqual(env._prev_goal_dist, 5000.0, places=3,
                               msg="reset did not re-seed _prev_goal_dist to the new segment")
        _, _, _, info2 = env.step(1, 1, 1, 0, 0.0, 13)
        self.assertAlmostEqual(info2["r_prog"], 0.1, places=3,
                               msg="first r_prog after reset to a new segment is polluted by "
                                   "the previous segment's goal distance")
        self.assertGreaterEqual(info2["r_prog"], 0.0,
                                "first post-reset r_prog must not be a large negative from a "
                                "stale (previous-segment) goal distance")


if __name__ == "__main__":
    unittest.main()
