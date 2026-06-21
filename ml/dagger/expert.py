"""ml/dagger/expert.py -- the analytic air-strafe EXPERT (DAgger oracle, D-1.5).

The DAgger relabeler answers "what is the RIGHT action in THIS visited state?". Ours is
analytic (no human-in-the-loop, fully offline): a goal-tracking, believability-capped
air-strafe controller for THIS engine. It REUSES the sim-proven
`eval_broad_closedloop.optimal_strafe_yaw` seam (the perpendicular-optimal reference yaw,
proven maximal vs the exact `pmove_sim._air_accelerate` by ml/tests/test_optimal_aim) --
it does NOT reimplement the air-accel math. On top of that reference it applies the two
D-1.5 corrections the D-1 validation proved necessary (orbit-killer + diagonal-aim):

    AIR  (the load-bearing action): fwd=+MOVE_MAG, side=+-MOVE_MAG (full diagonal press),
         up=0, jump=0. view_yaw = the seam's perpendicular-optimal yaw INTERPOLATED toward
         the goal heading by `forward_blend` (the believability cap -> wishdir ~59 deg off
         velocity, the human median, NOT 90). The side key ALTERNATES L/R on a weave period
         (the orbit-killer -> G-MV3 cadence).
    GROUND: jump=BUTTON_JUMP (auto-hop on land = the continuous bunnyhop), and -- only when
         nearly stopped -- forward to regain launch ground-speed (the cold-start launch
         convention). fwd is the launch push when stopped, else +MOVE_MAG diagonal as in air.

WHY D-1.5 changed the AIR action from D-1's `fwd=0` strict-perpendicular fixed-side:
the D-1 validation PROVED that controller UNSOUND -- per-tick speed-optimal but it ORBITS
(a wishdir held strictly perpendicular to velocity only ROTATES velocity, never aligns it
to a goal; a fixed side key then circles -> G-MV4 ~99 qu/s on ALL routes, G-MV3 flips=0,
route% ~13%). The evidence-backed fix (this module):
  1. ALTERNATE the side key L/R every `weave_period` ticks. The L/R weave nets straight
     goal-progress where a fixed side curves into a circle. (Geometric probe: straightness
     0.018 -> 0.918 just from alternating -- the dominant orbit fix.) Lands G-MV3 flips in
     the human band [8,360]/min (weave_period 18 ticks @ ~13ms -> ~256 flips/min, mid-band).
  2. LEAN the aim toward the goal (`forward_blend`) so the realized wishdir is the human
     DIAGONAL (~45-60 deg off velocity), NOT strict-perpendicular. Check (a) measured the
     human median wishdir-vs-velocity at 58.9 deg with fwd pressed on 54% of air frames ->
     elite humans deliberately sub-optimize per-tick for directionality. The diagonal also
     CAPS speed near the human band (strict-perp 90deg compounds to ~3x band; the diagonal
     tracks the goal instead). Default `forward_blend=0.7` lands ~59 deg (probe-confirmed).

KEY GEOMETRY (why fwd>0 alone is NOT enough -- the blend is a YAW lean, not a key trick):
`optimal_strafe_yaw` ALWAYS returns the yaw that makes the wishdir perpendicular to v,
*whatever* fwd/side magnitudes it is given (that is its contract: wishvel . v = 0). So
passing fwd>0 INTO the seam does not bend the wishdir below 90 -- the seam re-aims to keep
it perpendicular. To get the human diagonal we therefore take the seam's perpendicular yaw
as the REFERENCE and INTERPOLATE the executed view-yaw toward the goal heading; the seam is
still the (reused, not reimplemented) perpendicular anchor. We pass the SAME fwd/side into
the seam AND the usercmd so the perpendicular reference is computed for the real key set.

SIGN CONVENTION (matched to the live `--aim optimal` path, ml/eval_broad_dryroute.py:613,
NOT guessed): the same `side_mag`/`fwd_mag` go both INTO optimal_strafe_yaw and INTO the
engine usercmd `cmd.move[0..1]`, so the seam's reference is correct for the executed keys.
The side SIGN alternates over the weave; the goal-heading interpolation keeps net progress
toward the route goal regardless of which side the bot currently leans.

Pure: stdlib `math` only. Imports `optimal_strafe_yaw`, `MOVE_MAG`, `BUTTON_JUMP` from
eval_broad_closedloop, which is itself torch/numpy/duckdb-free at import time (torch is
imported lazily inside its torch CLI, not at module scope). No torch here.
"""
from __future__ import annotations

import logging
import math
import sys
from pathlib import Path

LOGGER = logging.getLogger(__name__)

# eval_broad_closedloop lives in ml/ (this file's parent) and imports its own siblings
# (gmv_believability, broad_bc.shard_contract) via ml/ + scripts/ on sys.path. Mirror the
# path setup test_optimal_aim uses so `import eval_broad_closedloop` resolves the seam.
_ML = Path(__file__).resolve().parent.parent          # .../ml
_REPO = _ML.parent                                     # repo root
for _p in (str(_ML), str(_REPO / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import eval_broad_closedloop as CL  # noqa: E402  (the proven seam: optimal_strafe_yaw)

MOVE_MAG = CL.MOVE_MAG          # 400.0 -- the usercmd full-press magnitude the sim consumes
BUTTON_JUMP = CL.BUTTON_JUMP    # 2    -- pmove jump button bit

# D-1.5 believability cap: fraction by which the executed view-yaw is leaned FROM the seam's
# perpendicular-optimal yaw TOWARD the goal heading. 0.0 == pure seam (strict perpendicular,
# the D-1 orbiter); 1.0 == aim straight at the goal. Default 0.7 lands the realized wishdir
# ~59 deg off velocity (the human median from check (a); probe_blend2 confirmed 0.7 -> 58.5
# deg). This is the diagonal-aim correction.
FORWARD_BLEND = 0.7

# D-1.5 orbit-killer: the side key alternates L/R every WEAVE_PERIOD_TICKS visited ticks.
# A flip is a +side <-> -side transition; at ~13 ms/tick a period of 18 ticks gives
# ~60000/(18*13) ~= 256 flips/min, mid-band in the G-MV3 human window [8,360]/min (8 ->
# need period <=~577; 360 -> need period >=~13). The weave nets straight goal-progress where
# a fixed side curves into a circle (geometric probe: straightness 0.018 -> 0.918).
WEAVE_PERIOD_TICKS = 18


def _angle_lerp(a: float, b: float, t: float) -> float:
    """Interpolate view-yaw a->b (degrees) along the SHORTEST arc by fraction t in [0,1].
    Used to lean the seam's perpendicular yaw toward the goal heading (the diagonal cap).
    t=0 -> a (perpendicular), t=1 -> b (goal heading). Pure float math."""
    d = ((float(b) - float(a) + 180.0) % 360.0) - 180.0
    return float(a) + float(t) * d


def weave_side_sign(tick: int, *, weave_period: int = WEAVE_PERIOD_TICKS) -> int:
    """The L/R strafe sign for visited tick `tick` under the weave: +1 for the first
    `weave_period` ticks, then -1 for the next, alternating. Deterministic in `tick` so the
    expert stays a pure function of its inputs (the DAgger relabeler passes the visited
    tick). `weave_period<=0` -> no weave (constant +1, the D-1 fixed-side behavior)."""
    if weave_period is None or int(weave_period) <= 0:
        return +1
    return +1 if (int(tick) // int(weave_period)) % 2 == 0 else -1


def goal_dir_yaw(ox: float, oy: float, goal) -> float:
    """Map-frame view yaw (DEGREES) from the ego origin toward `goal` (gx, gy).

    Matches the v5 COMPASS heading (agent_observation.goal_vector uses the same
    atan2(gy-oy, gx-ox)); we convert to degrees for the engine/seam view-yaw space and
    use it as the optimal_strafe_yaw fallback so the perpendicular branch picked bends
    toward the route goal. `goal is None` (free-roam) -> 0.0 (heading undefined)."""
    if goal is None:
        return 0.0
    gx, gy = float(goal[0]), float(goal[1])
    return math.degrees(math.atan2(gy - oy, gx - ox))


def expert_action(state: dict, *, side_sign: int | None = None, tick: int = 0,
                  forward_blend: float = FORWARD_BLEND,
                  weave_period: int = WEAVE_PERIOD_TICKS) -> tuple:
    """Goal-tracking air-strafe expert action for one visited sim state (D-1.5).

    Returns (fwd, side, up, jump, view_yaw) -- the SAME shape the rollout feeds the
    engine: fwd/side/up are usercmd magnitudes (+-MOVE_MAG / 0 = cmd.move[0..2]), jump is
    the BUTTON_JUMP bit (0 = released), view_yaw is the engine view yaw in DEGREES (the
    angles[1] passed to PM.Cmd). Pure float math, deterministic in its inputs.

    `state` keys (the visited pmove_sim state + the v5 goal):
        vx, vy      : world-frame horizontal velocity (qu/s).            REQUIRED.
        onground    : bool, the sim onground flag for THIS state.        REQUIRED.
        goal        : (gx, gy) route goal in world coords, or None.      optional.
        origin/ox,oy: ego position for the goal heading.                 optional.
        goal_dir_yaw: precomputed fallback yaw (deg); overrides goal/origin if given.
        tick        : visited-tick index (drives the L/R weave); state value used if the
                      `tick` kwarg is left default and the state carries one.

    `side_sign` (+-1 or None): force a strafe side, or None (default) to DERIVE the side
    from the weave at `tick` (the orbit-killer L/R alternation). The DAgger loop may force
    a side per-state if a turn direction is preferred.
    `forward_blend` in [0,1]: lean the executed view-yaw from the seam's perpendicular
    reference toward the goal heading (the diagonal cap; see module docstring + FORWARD_BLEND).
    `weave_period` ticks: L/R alternation period (see WEAVE_PERIOD_TICKS).

    AIR  : fwd=MOVE_MAG, side=sign*MOVE_MAG, up=0, jump=0; view_yaw = the seam's
           perpendicular-optimal yaw leaned toward the goal heading by forward_blend.
    GROUND: jump=BUTTON_JUMP (auto-hop on land); fwd=MOVE_MAG (launch push -- the seam falls
            back to the goal heading when nearly stopped), side as in air, view_yaw as in air.
    """
    vx = float(state["vx"])
    vy = float(state["vy"])
    onground = bool(state["onground"])

    # fallback view yaw = the v5 goal heading (the seam's perpendicular branch bends to it,
    # and it is the lean target for the diagonal cap)
    if "goal_dir_yaw" in state and state["goal_dir_yaw"] is not None:
        fb_yaw = float(state["goal_dir_yaw"])
    else:
        goal = state.get("goal")
        if "origin" in state and state["origin"] is not None:
            ox, oy = float(state["origin"][0]), float(state["origin"][1])
        else:
            ox = float(state.get("ox", 0.0))
            oy = float(state.get("oy", 0.0))
        fb_yaw = goal_dir_yaw(ox, oy, goal)

    # the weave: alternate L/R unless the caller forces a side. Default the tick to the
    # state's own tick when the kwarg is left at 0 and the state supplies one.
    eff_tick = int(tick) if tick else int(state.get("tick", 0) or 0)
    sign = int(side_sign) if side_sign is not None else weave_side_sign(
        eff_tick, weave_period=weave_period)
    side = float(sign) * MOVE_MAG

    if onground:
        # auto-hop for sustain; forward is the launch push (the seam falls back to the goal
        # heading when nearly stopped, so this drives toward the goal off the ground)
        fwd = MOVE_MAG
        jump = BUTTON_JUMP
    else:
        fwd = MOVE_MAG     # D-1.5: a forward component (humans press fwd ~54% of air frames)
        jump = 0

    up = 0.0
    # REUSE the seam for the perpendicular-optimal REFERENCE yaw (same fwd/side as the
    # usercmd, matching --aim optimal at :613), then LEAN it toward the goal heading by
    # forward_blend so the realized wishdir is the human diagonal, not strict-perpendicular
    # (the seam alone always returns the perpendicular yaw -- see module KEY GEOMETRY).
    perp_yaw = CL.optimal_strafe_yaw(vx, vy, fwd, side, fb_yaw)
    view_yaw = _angle_lerp(perp_yaw, fb_yaw, forward_blend)
    return (fwd, side, up, jump, view_yaw)
