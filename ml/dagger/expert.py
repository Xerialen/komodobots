"""ml/dagger/expert.py -- the analytic optimal air-strafe EXPERT (DAgger oracle, D-1).

The DAgger relabeler answers "what is the RIGHT action in THIS visited state?". Ours is
analytic (no human-in-the-loop, fully offline): the per-tick speed-optimal air-strafe
controller for THIS engine. It is a thin wrapper over the sim-proven
`eval_broad_closedloop.optimal_strafe_yaw` seam (wishdir _|_ horizontal velocity; proven
maximal vs the exact `pmove_sim._air_accelerate` by ml/tests/test_optimal_aim) -- it does
NOT reimplement the air-accel math. It only ADDS the move-key override that the policy's
over-press attractor gets wrong:

    AIR  (the load-bearing action): fwd=0, side=+-MOVE_MAG (full strafe), up=0, jump=0,
         view_yaw = optimal_strafe_yaw(vx, vy, 0.0, side, fallback=goal_dir_yaw).
    GROUND: jump=BUTTON_JUMP (auto-hop on land = the continuous bunnyhop), and -- only when
         nearly stopped -- a small forward to regain launch ground-speed (the cold-start
         launch convention). fwd=0 once moving so the expert never bulldozes.

WHY fwd=0 in the air: the diagnosed v5 failure is the over-press bulldoze (closed-loop
fwd-press ~0.99 -> wishdir ~aligned with velocity -> ~0 speed gain -> 162 qu/s; G-MV4
FAILS). Air-strafe wants the wishdir PERPENDICULAR to velocity, which (in this engine,
with the move keys fed through the view yaw) is achieved by side-only + the optimal yaw.

SIGN CONVENTION (matched to the live `--aim optimal` path, ml/eval_broad_dryroute.py:613,
NOT guessed): the SAME `side_mag` is passed both INTO optimal_strafe_yaw (which picks the
perpendicular yaw branch that, with this side key, makes wishdir _|_ v AND bends toward
`fallback`) AND into the engine usercmd `cmd.move[1]`. So whichever sign we pick for
`side`, the yaw adapts to keep it perpendicular-optimal; the sign only flips WHICH side
the bot leans, and the branch-nearest-fallback already turns the chosen perpendicular
toward the route goal. We pick +MOVE_MAG by convention (see expert_action's `side` doc).

Pure: stdlib `math` only. Imports `optimal_strafe_yaw`, `MOVE_MAG`, `BUTTON_JUMP` from
eval_broad_closedloop, which is itself torch/numpy/duckdb-free at import time (torch is
imported lazily inside its torch CLI, not at module scope). No torch here.

=============================================================================
D-1 VALIDATION VERDICT (2026-06-21, ml/dagger/validate_expert.py on pinnacle) -- UNSOUND
as a closed-loop DAgger oracle AS SPECCED. Keep this module as the faithful realization of
the spec'd expert (so the validation measures what was specified); DO NOT teach D-2 from it
unmodified. Evidence (every number from a real run):
  * check (a) human-agreement (64,503 real human air frames): the human strafes the optimal
    DIRECTION (side-key sign agreement 89.4%, >=75% target PASS) BUT at a DIAGONAL wishdir
    (median human wishdir-vs-velocity 58.9 deg, NOT 90; only 46% within +-30 of perp), with
    forward pressed on 54.4% of air frames. => elite humans deliberately sub-optimize
    per-tick (mix fwd+side) for DIRECTIONALITY; the strict-perp expert is MORE extreme.
  * check (b) expert-alone closed-loop (11 routes): pure expert FAILS G-MV4 on ALL routes
    (pooled avg 99 qu/s vs band 252-316) and G-MV3 flips/min=0 (constant side, no L/R weave).
    ROOT CAUSE (proven geometrically, /tmp/probe_circle.py): a wishdir held STRICTLY
    perpendicular to velocity only ROTATES velocity -- it never aligns it to a goal -- so a
    fixed side key makes the bot ORBIT (velang -> 90 deg off the goal, then circles). It is
    per-tick speed-optimal but TRAJECTORY-DIVERGENT: it stalls at ~80 qu/s and ~13% route.
  * check (c) fixes-over-press (875 cs10 air over-press states, pol_fwd>=360 on 97.8% of
    cs10 air frames): expert emits fwd<=human-band AND side!=0 on 100% -- but this is the
    air-strafe ACTION SHAPE only; (b) shows that shape circles. Not a rescue.
THE FIX (the concrete blend-toward-human rec for D-1.5 / D-2, grounded in (a)'s numbers):
the oracle must (1) allow a FORWARD component (humans press fwd ~54% of air frames; target
wishdir ~45-60 deg off velocity, not 90) to get net progress toward the goal, and (2)
ALTERNATE the side key L/R to WEAVE along the route (the G-MV3 cadence humans show, flips
in [8,360]/min) instead of holding one side. I.e. a goal-tracking, believability-capped
near-optimal strafe -- NOT the strict per-tick maximum. This is the owner CHECK-IN decision.
=============================================================================
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

# Below this horizontal ground-speed the bot is treated as "needs a launch push" and the
# GROUND action issues forward to regain speed before the next hop (the cold-start launch
# convention). At/above it the ground action is fwd=0 (already moving -> don't bulldoze).
# A pure launch heuristic; the AIR action is the load-bearing one for the over-press fix.
GROUND_LAUNCH_SPEED_QU = 100.0


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


def expert_action(state: dict, *, side_sign: int = +1,
                  ground_launch_speed: float = GROUND_LAUNCH_SPEED_QU) -> tuple:
    """Optimal air-strafe expert action for one visited sim state.

    Returns (fwd, side, up, jump, view_yaw) -- the SAME shape the rollout feeds the
    engine: fwd/side/up are usercmd magnitudes (+-MOVE_MAG / 0 = cmd.move[0..2]), jump is
    the BUTTON_JUMP bit (0 = released), view_yaw is the engine view yaw in DEGREES (the
    angles[1] passed to PM.Cmd). Pure float math.

    `state` keys (the visited pmove_sim state + the v5 goal):
        vx, vy      : world-frame horizontal velocity (qu/s).            REQUIRED.
        onground    : bool, the sim onground flag for THIS state.        REQUIRED.
        goal        : (gx, gy) route goal in world coords, or None.      optional.
        origin/ox,oy: ego position for the goal heading.                 optional.
        goal_dir_yaw: precomputed fallback yaw (deg); overrides goal/origin if given.

    `side_sign` (+-1): which way the bot strafes. Perpendicular-optimal at EITHER sign
    (the yaw adapts -- see module docstring); +1 by convention. The DAgger loop may flip
    it per-state if a turn direction is preferred, but speed-gain is identical.

    AIR  : fwd=0, side=side_sign*MOVE_MAG, up=0, jump=0, view_yaw=optimal_strafe_yaw(...).
    GROUND: jump=BUTTON_JUMP (auto-hop on land); fwd=MOVE_MAG ONLY when |v_h| <
            ground_launch_speed (regain launch speed), else fwd=0; side as in AIR so the
            launch already leans into the strafe; view_yaw=optimal yaw (fallback when
            stopped -> goal heading).
    """
    vx = float(state["vx"])
    vy = float(state["vy"])
    onground = bool(state["onground"])

    # fallback view yaw = the v5 goal heading (so the perpendicular branch bends to goal)
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

    side = float(side_sign) * MOVE_MAG

    if onground:
        hspeed = math.hypot(vx, vy)
        fwd = MOVE_MAG if hspeed < float(ground_launch_speed) else 0.0
        jump = BUTTON_JUMP
    else:
        fwd = 0.0          # the over-press fix: NO forward in the air
        jump = 0

    up = 0.0
    # SAME `side` magnitude into the seam AND (by the caller) into the usercmd -> the yaw
    # is the perpendicular-optimal aim FOR THIS key set (matches --aim optimal at :613).
    view_yaw = CL.optimal_strafe_yaw(vx, vy, fwd, side, fb_yaw)
    return (fwd, side, up, jump, view_yaw)
