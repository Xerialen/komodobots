"""#427 (T5.1) — Phase-2 PPO reward, extracted as a pure stdlib function.

This is the information-honest *superhuman* reframe of the ROUND-6 reward that lived inline in
`ml/rl_onspeed.py:PmoveEnv.step` (commit 17c68e4, built for the superseded *believability* goal).
It is split out here so the reward logic lands in the gating stdlib test floor (no torch/numpy)
and is unit-testable in isolation (`tests/test_reward_onspeed.py`).

docs/28 names four reward signals — **Velocity+ / Progress+ / Collision− / Time−**. Mapping onto
the existing env (option C, owner-approved — "uncap speed, keep the mechanism scaffolding"):

  REPLACED (were human-imitation anchors):
    - Velocity+ `r_vel` : a human-RELATIVE speedup ratio = (v · route_tangent) / human_speed_here,
      soft-saturated above 1 and floored at −1. `ratio>1` = superhuman ON THIS STRETCH. Replaces the
      old `soft_band(252..316)` which gaussian-DECAYED above 316 (a superhuman-speed *cap*).
      Projecting onto the tangent (not raw |v|) is the anti-hack: vibrating/orbiting earns ≤0.
      Bounded both ends so an outlier tick can't wreck PPO's raw-return value fit / advantage z-score.
    - Progress+ `r_prog`: arc-length delta along the segment's human-reference polyline (was a single
      goal-point distance delta). Back-and-forth nets ~0.
  ADDED:
    - Collision− `p_collide`: a wall hit this frame (pmove `blocked` bitmask STEP|OTHER, not FLOOR).
    - Time− `w_time`     : a small constant per-tick penalty (finish fast).
  KEPT verbatim (physics mechanism — *how bhop is discovered*; ROUND-4 proved a naive speed reward
  bulldozes instead of strafe-jumping): `r_phi` (air-gated speed-gain credit), `r_strafe` (perp-wishdir
  air bonus), `r_press` (anti-bulldoze air-press barrier), `p_hack` (anti-spin). Their constants are now
  plain tunables (no longer justified as "human-plausible"); see #429.
  DROPPED by default (`w_cad=0`): `r_cad`, the L↔R cadence rhythm — a *believability* signal (M6/G-MV3)
  that the ROUND-8 diagnosis showed STEALS the sustained air-strafe speed+launch need. Still computed
  (for the `info` diagnostic the rollout logger reads) and re-enablable via `w_cad`.

stdlib only (math, logging) + route_geom. No torch/numpy.
"""

import logging
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:                       # route_geom lives alongside this module
    sys.path.insert(0, _HERE)
from route_geom import project_onto_polyline, interpolate_speed_at_arc  # noqa: E402

LOGGER = logging.getLogger(__name__)

# Collision bitmask (mirror scripts/pmove_sim.py BLOCKED_*; these mirror the engine's pml.h and
# are physics-stable). A "wall hit" = a vertical/steep plane, NOT a walkable floor landing.
BLOCKED_FLOOR = 1
BLOCKED_STEP = 2
BLOCKED_OTHER = 4
WALL_MASK = BLOCKED_STEP | BLOCKED_OTHER

# Analytic per-tick achievable horizontal-speed gain (the air-strafe mechanism credit denominator).
# PHI_C = WISHSPD_CAP**2 = 30**2 = 900 (mirror ml/rl_onspeed.py).
PHI_C = 900.0


def phi(s):
    """Analytic per-tick achievable horizontal-speed gain at speed s (greedy-perp)."""
    return math.sqrt(s * s + PHI_C) - s


# Default reward weights — the option-C baseline. All tunable via CLI / #429 hyperparameter search.
DEFAULT_WEIGHTS = {
    "w_vel": 1.0,      # Velocity+ (was r_speed 1.0)
    "w_prog": 0.5,     # Progress+ (was r_prog 0.5)
    "w_phi": 0.5,      # kept: mechanism-credit speed gain
    "w_strafe": 0.6,   # kept: perp-wishdir air bonus
    "w_cad": 0.0,      # DROPPED by default (believability rhythm); re-enablable
    "w_press": 1.0,    # kept: anti-bulldoze air-press barrier
    "w_collide": 0.5,  # NEW: Collision−
    "w_time": 0.01,    # NEW: Time− (constant per tick)
    "w_hack": 1.0,     # kept: anti-spin
    # kept-term shape params (de-anchored tunables, NOT human-match targets)
    "band_lo": 252.279,        # only used as the r_strafe "moving fast enough" gate (band_lo*0.5)
    "cad_hold_min": 14,
    "cad_hold_max": 230,
    "cad_hold_late": 240,
    "air_press_thresh": 0.40,
    "ap_rate_ema": 0.02,
    # new-term shape params
    "v_sat": 1.5,        # Velocity+ soft-saturation scale above ratio 1 (asymptote 1+v_sat)
    "prog_scale": 50.0,  # Progress+ normalization: +1 ≈ 50 qu of arc advanced this tick
}


def velocity_reward(ratio, v_sat=1.5):
    """Monotone, BOUNDED route-relative speedup reward.

    ratio = along-route speed / human along-route speed here.
      ratio >= 1 : superhuman → 1 + v_sat*(1 - exp(-(ratio-1)/v_sat)), asymptotes 1+v_sat (uncapped
                   in the sense that faster is ALWAYS strictly better, but magnitude-bounded for PPO).
      ratio <  1 : sub-human / backward → max(-1, ratio). Floored at -1 so a fast-backward tick can't
                   become an unbounded-negative outlier; still ≤0 for backward/perpendicular (anti-hack).
    Continuous at ratio==1 (both branches → 1.0). Strictly increasing in ratio everywhere.
    """
    if ratio >= 1.0:
        return 1.0 + v_sat * (1.0 - math.exp(-(ratio - 1.0) / v_sat))
    return max(-1.0, ratio)


def progress_reward(arc_now, arc_prev, prog_scale=50.0):
    """Clamped arc-length delta along the route this tick (+1 ≈ prog_scale qu advanced)."""
    return max(-1.0, min(1.0, (arc_now - arc_prev) / prog_scale))


def collision_penalty(blocked):
    """1.0 when this frame's pmove blocked-bitmask shows a wall hit (STEP|OTHER), else 0.0."""
    return 1.0 if (int(blocked) & WALL_MASK) else 0.0


def route_speedup(ox, oy, oz, vx, vy, polyline, speeds, total_len):
    """Project the bot onto its human-reference polyline; return (v_along, v_ref, ratio, arc_now).

    v_along = horizontal velocity projected onto the local route tangent (xy).
    v_ref   = the human's interpolated speed at the bot's arc (the per-stretch superhuman reference).
    ratio   = v_along / v_ref (0 if no usable reference).
    arc_now = arc-length (qu) of the projected point. Returns (0,0,0, arc fallback) on a degenerate route.
    """
    proj = project_onto_polyline(ox, oy, oz, polyline)
    if proj is None:
        return 0.0, 0.0, 0.0, None
    seg = proj["segIndex"]
    ax, ay = polyline[seg][0], polyline[seg][1]
    bx, by = polyline[seg + 1][0], polyline[seg + 1][1]
    tx, ty = bx - ax, by - ay
    tlen = math.hypot(tx, ty)
    if tlen > 1e-6:
        v_along = vx * (tx / tlen) + vy * (ty / tlen)
    else:
        v_along = 0.0
    v_ref = interpolate_speed_at_arc(proj["arcFrac"], polyline, speeds)
    v_ref = float(v_ref) if v_ref is not None else 0.0
    ratio = v_along / v_ref if v_ref > 1e-6 else 0.0
    arc_now = proj["arcFrac"] * total_len
    return v_along, v_ref, ratio, arc_now


def compute_step_reward(cur, carry, route, cfg):
    """The per-tick reward. Pure: reads `cur`/`carry`/`route`/`cfg`, returns (reward, info, next_carry).

    cur   : post-frame tick data — hspeed, vx, vy, onground, ox, oy, oz, perp_frac, side_am_mag,
            fwd_am, yaw_delta_deg, msec, blocked.
    carry : reward state threaded across ticks — prev_hspeed, prev_arc, prev_strafe_sign, strafe_hold,
            ap_rate. (The env seeds these at reset and writes back next_carry each step.)
    route : the segment's human reference — polyline (list of (x,y,z)), speeds (per-vertex |v_xy|),
            total_len (arc length, precomputed once at reset).
    cfg   : DEFAULT_WEIGHTS merged with any overrides.
    """
    hspeed = cur["hspeed"]
    onground = cur["onground"]
    perp_frac = cur["perp_frac"]
    prev_hspeed = carry["prev_hspeed"]
    strafe_hold = carry["strafe_hold"]
    prev_strafe_sign = carry["prev_strafe_sign"]
    ap_rate = carry["ap_rate"]

    # ── KEPT: mechanism-credit speed gain (r_phi) + perp-wishdir air bonus (r_strafe) ──────────
    avail = phi(prev_hspeed)
    ds = hspeed - prev_hspeed
    r_phi_raw = min(1.0, max(0.0, ds) / avail) if avail > 1e-6 else 0.0
    if onground:
        r_phi = r_phi_raw                          # ground accel: a different mechanism
        r_strafe = 0.0
    else:
        r_phi = perp_frac * r_phi_raw              # air GAIN credited only via the mechanism
        r_strafe = perp_frac if hspeed > (cfg["band_lo"] * 0.5) else 0.0
        if strafe_hold > cfg["cad_hold_max"]:      # decay a PARKED perpendicular strafe
            over = strafe_hold - cfg["cad_hold_max"]
            r_strafe *= max(0.0, 1.0 - over / float(cfg["cad_hold_max"]))

    # ── NEW: Velocity+ (route-relative speedup) + Progress+ (arc-length delta) ─────────────────
    v_along, v_ref, ratio, arc_now = route_speedup(
        cur["ox"], cur["oy"], cur["oz"], cur["vx"], cur["vy"],
        route["polyline"], route["speeds"], route["total_len"])
    if arc_now is None:                            # degenerate route → no route credit this tick
        r_vel = 0.0
        arc_now = carry["prev_arc"]
        r_prog = 0.0
    else:
        r_vel = velocity_reward(ratio, cfg["v_sat"])
        r_prog = progress_reward(arc_now, carry["prev_arc"], cfg["prog_scale"])

    # ── NEW: Collision− ────────────────────────────────────────────────────────────────────────
    p_collide = collision_penalty(cur["blocked"])

    # ── KEPT: anti-spin (p_hack) ───────────────────────────────────────────────────────────────
    dt = float(cur["msec"]) / 1000.0
    yaw_rate = abs(cur["yaw_delta_deg"]) / dt if dt > 0 else 0.0
    disp = hspeed * dt
    p_hack = 1.0 if (yaw_rate > 600.0 and disp < 1.0) else 0.0

    # ── KEPT: strafe-cadence shaping (r_cad) on the ARGMAX side sign. Mutates strafe_hold/sign. ──
    cur_sign = 1 if cur["side_am_mag"] > 0 else (-1 if cur["side_am_mag"] < 0 else 0)
    r_cad = 0.0
    if cur_sign != 0:
        if prev_strafe_sign != 0 and cur_sign != prev_strafe_sign:
            if cfg["cad_hold_min"] <= strafe_hold <= cfg["cad_hold_max"]:
                r_cad += 1.0
            strafe_hold = 0
        else:
            strafe_hold += 1
        prev_strafe_sign = cur_sign
        if strafe_hold > cfg["cad_hold_late"]:
            over = strafe_hold - cfg["cad_hold_late"]
            r_cad -= min(2.0, 0.5 + 0.01 * over)

    # ── KEPT: soft air press-barrier (r_press). Mutates ap_rate (EMA over the episode). ─────────
    air_press = (cur["fwd_am"] == 2) and (not onground)
    if not onground:
        ap_rate += cfg["ap_rate_ema"] * ((1.0 if air_press else 0.0) - ap_rate)
    r_press = max(0.0, ap_rate - cfg["air_press_thresh"])

    reward = (cfg["w_vel"] * r_vel + cfg["w_prog"] * r_prog
              + cfg["w_phi"] * r_phi + cfg["w_strafe"] * r_strafe
              + cfg["w_cad"] * r_cad
              - cfg["w_press"] * r_press - cfg["w_collide"] * p_collide
              - cfg["w_time"] - cfg["w_hack"] * p_hack)

    next_carry = {
        "prev_hspeed": hspeed,
        "prev_arc": arc_now,
        "prev_strafe_sign": prev_strafe_sign,
        "strafe_hold": strafe_hold,
        "ap_rate": ap_rate,
    }
    info = {
        "hspeed": hspeed, "onground": onground, "fwd_press": int(cur["fwd_am"] == 2),
        "r_vel": r_vel, "v_along": v_along, "r_prog": r_prog, "p_hack": p_hack,
        "r_cad": r_cad, "r_press": r_press, "strafe_sign": cur_sign,
        "perp_frac": perp_frac, "r_strafe": r_strafe, "ap_rate": ap_rate,
        "p_collide": p_collide,
    }
    return reward, info, next_carry
