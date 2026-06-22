"""ml/tests/test_eval_closedloop_yawrate.py — regression for Finding 2 [High]:
policy self-yaw eval fed ZERO yaw-rate after the first tick.

In ml/eval_broad_closedloop.closed_loop_rollout with aim_mode="policy", the loop builds the
obs from the pre-turn `yaw`, the policy integrates `policy_yaw = yaw + yd`, executes it, and
USED to set `prev_yaw = exec_view_yaw` (the POST-turn yaw). Next tick `yaw == policy_yaw ==
exec_view_yaw`, so `_yaw_rate_degps(yaw, prev_yaw, dt)` was 0 on EVERY policy tick after the
first — the turn-direction obs feature vanished in closed-loop (train/eval skew, since the
policy was trained with a real yaw_rate). The fix tracks the PRE-turn obs `yaw` as the next
tick's prev_yaw (mirroring eval_broad_dryroute's yaw_prev = yaw and the rl_onspeed env's
prev_yaw = cur_yaw pre-turn), so the next tick's yaw_rate == this tick's turn delta.

The test drives the REAL closed_loop_rollout policy loop with a fixed-turn stub model + a stub
pmove, and captures the yaw_rate fed into _self_state_from_sim each tick. It asserts the
yaw_rate is 0 on tick 0 and NONZERO (== the integrated turn delta in deg/s) on the next
policy tick. Fails-before (0 every tick) / passes-after. torch-gated (the loop calls
model.forward_with_yaw); placed near test_eval_closedloop.py.
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

import eval_broad_closedloop as CL     # noqa: E402  (deps-free at import time)

_HAVE_TORCH = importlib.util.find_spec("torch") is not None


class _StubState:
    def __init__(self):
        self.origin = [0.0, 0.0, 0.0]
        self.velocity = [320.0, 0.0, 0.0]   # moving along +x so hspeed > 0
        self.onground = False               # airborne: the air-strafe regime


class _StubPmove:
    """Pmove stub: run_frame advances the origin a hair and keeps the bot airborne. The
    yaw-rate bookkeeping under test is independent of the real physics."""
    def __init__(self, world):
        pass

    def run_frame(self, st, cmd):
        st.origin[0] += 1.0
        st.onground = False


class _StubPmModule:
    PlayerState = staticmethod(lambda o, v: _mk_state(o, v))
    Pmove = _StubPmove

    @staticmethod
    def Cmd(msec, angles, move, jump):
        return {"msec": msec, "angles": angles, "move": move, "jump": jump}


def _mk_state(o, v):
    s = _StubState()
    s.origin = [float(o[0]), float(o[1]), float(o[2])]
    s.velocity = [float(v[0]), float(v[1]), float(v[2])]
    return s


class _FixedTurnModel:
    """A policy stub whose yaw head ALWAYS proposes the same per-tick turn delta (deg), so
    the integrated policy_yaw advances by a known constant each tick. The discrete heads
    return fixed argmax classes (neutral move keys)."""
    def __init__(self, turn_deg, torch_mod, n_heads=5, head_dims=(3, 3, 3, 2, 2)):
        self.turn_deg = float(turn_deg)
        self.torch = torch_mod
        self.head_dims = head_dims

    def _logits(self):
        # argmax = class 1 for every head (neutral move / no jump / no attack)
        out = []
        for k in self.head_dims:
            v = [0.0] * k
            v[1] = 5.0
            out.append(self.torch.tensor([v]))
        return out

    def forward_with_yaw(self, obs, ent, em, aux):
        rad = self.turn_deg * math.pi / 180.0
        yaw2 = self.torch.tensor([[math.sin(rad), math.cos(rad)]])  # decodes to turn_deg
        return self._logits(), yaw2

    def __call__(self, obs, ent, em, aux):
        return self._logits()


@unittest.skipUnless(_HAVE_TORCH, "torch required for the closed-loop policy yaw-rate test")
class TestPolicyYawRateNonzero(unittest.TestCase):
    def _run_capture(self, turn_deg=12.0, n_ticks=5, msec=13):
        """Drive the REAL closed_loop_rollout policy loop, capturing the yaw_rate passed into
        _self_state_from_sim each tick. Returns the list of captured yaw_rates."""
        import torch

        captured = []
        orig_self_state = CL._self_state_from_sim

        def _spy_self_state(st, yaw, pitch, yaw_rate=0.0, goal=None):
            captured.append(float(yaw_rate))
            return orig_self_state(st, yaw, pitch, yaw_rate=yaw_rate, goal=goal)

        # a tiny encoder stub: fixed-length SELF + empty ents/mask (f_ent=0 path)
        class _AOStub:
            @staticmethod
            def encode_observation(self_state, others, stats, map_name, n_max):
                return {"self": [0.0] * CL._SELF_HISTORY, "ents": [], "mask": []}

        norm = {"_AO": _AOStub(), "_stats": {}}
        dims = {"f_ent": 0, "f_aux": 0}
        model = _FixedTurnModel(turn_deg, torch)

        # segment of n_ticks+1 ticks (loop runs n_ticks). seed yaw 0; goal absent (free-roam).
        seg = [{"self": {"ox": 0.0, "oy": 0.0, "oz": 0.0, "vx": 320.0, "vy": 0.0, "vz": 0.0,
                         "yaw": 0.0, "pitch": 0.0},
                "act": {"msec": msec}} for _ in range(n_ticks + 1)]

        CL._self_state_from_sim = _spy_self_state
        try:
            CL.closed_loop_rollout(
                _StubPmModule(), None, seg, "policy",
                model=model, dims=dims, norm=norm, map_name="dm3", n_max=1,
                device="cpu", torch_mod=torch, goal_mode="blind", aim_mode="policy")
        finally:
            CL._self_state_from_sim = orig_self_state
        return captured

    def test_yaw_rate_nonzero_after_first_policy_tick(self):
        turn_deg = 12.0
        msec = 13
        rates = self._run_capture(turn_deg=turn_deg, n_ticks=5, msec=msec)
        self.assertGreaterEqual(len(rates), 3)
        # tick 0: prev_yaw is None -> rate 0.0 (the build's first-tick=0 convention)
        self.assertEqual(rates[0], 0.0)
        # EVERY subsequent policy tick must see a NONZERO yaw-rate == the integrated turn
        # delta in deg/s (turn_deg / dt). Under the bug these were all 0.0.
        expected = turn_deg / (msec / 1000.0)   # deg/s
        for i, r in enumerate(rates[1:], start=1):
            self.assertAlmostEqual(r, expected, places=3,
                                   msg=f"policy tick {i}: yaw_rate {r} != {expected} "
                                       f"(turn-direction feature is 0 in closed-loop)")
            self.assertNotAlmostEqual(r, 0.0, places=6,
                                      msg=f"policy tick {i}: yaw_rate is 0 (Finding 2 bug)")


if __name__ == "__main__":
    unittest.main()
