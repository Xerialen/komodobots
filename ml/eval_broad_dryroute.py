#!/usr/bin/env python3
"""eval_broad_dryroute.py — the DRY-ROUTE robustness gate for the BROAD BC policy.

WHAT THIS IS (and why it exists)
================================
The BROAD move-only BC policy is move-believable (it PASSES G-MV1 face-and-run in
the closed-loop gmv eval, ml/eval_broad_closedloop.py) but STALLS in closed loop:
mean speed ~146 vs human ~264 qu/s, longest stall ~11 s vs ~0.65 s. That stall is
the autonomy blocker, and until now it was NOT a control-validated gate — there was
no human-anchored, bracketed PASS/FAIL number on it.

This module wires the proven human-anchored route checker
(scripts/verify_route.py + scripts/route_metrics.py, validated to ~0.2 qu drift) to
the policy. The policy DRIVES pmove_sim down a real censused dm3 trick route while
REPLAYING the recorded human VIEW yaw/pitch per tick (move-only clone, AIM deferred —
identical to the closed-loop gmv eval), and we score how far + how fast it traverses
the human's path with the dead-stop-proof route_metrics.time_weighted_speed.

THE GATE (route% >= 80 AND speed% >= 80) — and what it deliberately is NOT
-------------------------------------------------------------------------
ALL 11 censused dm3 routes end in a HARD LEAP (~525 qu/s launch-edge speed). A
move-only BC policy replaying human yaw cannot be expected to clear that yet, so the
robustness gate does NOT require REACHED_RL. It gates on smooth, fast traversal UP TO
the leap:

    PASS  iff  route% >= 80  AND  speed% >= 80

  * route%  = route_metrics-domain arc-length progress along the human path while ON
    the route (verify_route.route_progress: within xtrack_max qu of the path AND not
    over the void), as a % of the human path arc length.
  * speed%  = 100 * bot_tws / human_tws, where *_tws = route_metrics.time_weighted_speed
    (total xy distance / total wall time over the legit segment, truncated at goal
    arrival). time_weighted_speed is dead-stop-proof: a wedged/idle bot accumulates
    time but no distance, so the stall shows up as a low speed% — exactly the
    autonomy failure we are gating.

REACHED_RL + launch-edge speed are reported as SEPARATE, HARDER diagnostics
(verify_route.classify class + route_metrics.edge_speed vs the censused required
speed) — never the robustness gate. A policy can FAIL this gate and that is the
correct, useful MEASUREMENT of the stall; success of THIS module is that the gate is
VALID (controls bracket), not that the policy passes.

CONTROLS (the proof the gate is valid)
--------------------------------------
  * POSITIVE control = the HUMAN path itself, scored directly from the route .cmds
    origins/velocities. route% = 100 and speed% = 100 by construction (human_tws is
    the speed% denominator), so the human path must PASS. We additionally confirm
    load_human's hmean and a time_weighted_speed on the human rows agree.
  * NEGATIVE control = "stall": an idle usercmd (0,0,0, no jump) driven through the
    sim from the human start every tick. A move-only idle bot does not move, so its
    route% and speed% collapse toward 0 and it must FAIL.
A gate whose controls do NOT bracket (human PASS, stall FAIL) is invalid; this module
exits NONZERO (code 4) in that case, exactly like eval_broad_closedloop's main.

HONEST CAVEATS (recorded in the report)
---------------------------------------
* AIM DEFERRED: view yaw/pitch is REPLAYED from the recorded human per tick (the
  BROAD policy clones movement/jump/attack but NOT view). route% / speed% measure
  the bot's own translation under the human's facing intent.
* SOLO-ROAM: no enemies in the sim -> encode_observation is called with
  observed_others=[] (entity channel all-pad + zero mask), same as the closed-loop
  gmv eval. No combat dynamics.
* MOVE-HEAD -> USERCMD MAGNITUDE = +-400 (the BROAD trainer's /400 move scale;
  ml.eval_broad_closedloop.MOVE_MAG). Sign drives direction; magnitude drives speed.
* over_void is computed with a straight-DOWN pmove_sim.player_trace to the route's
  censused void_floor_z (minus a margin): a tick whose down-trace hits NO solid floor
  (Trace.fraction >= 1.0) is over the void and is excluded from route% (so a bot that
  flew off into the chasm cannot be credited for passing near a late human point on
  the way down — verify_route.route_progress's own rule).

CLI
===
  # real policy (needs torch + the BSP), GPU host:
  python -m ml.eval_broad_dryroute \
      --checkpoint ~/broad_bc_policy.pt \
      --bsp /path/to/dm3.bsp --route sng_to_rl \
      --out dryroute_report.json [--cpu]

  # controls-only (NO torch): human-path + stall, proves the gate is valid deps-light
  python -m ml.eval_broad_dryroute \
      --bsp /path/to/dm3.bsp --route sng_to_rl --controls-only \
      --out dryroute_controls.json

This module is importable on bare stdlib: torch and the heavy encoders/loaders are
lazy-imported inside the policy path (exactly like eval_broad_closedloop). pmove_sim
+ verify_route + route_metrics are pure-stdlib siblings under scripts/ and are
imported at module load. The pure glue (row building, gate logic, over_void
classification, control bracket) is unit-tested deps-free with a FAKE rollout.
"""
from __future__ import annotations

import logging
import argparse
import json
import math
import sys
from pathlib import Path


LOGGER = logging.getLogger(__name__)
HERE = Path(__file__).resolve().parent          # ml/
REPO_ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# pure-stdlib siblings (the proven human-anchored scorers) + pmove_sim. These are
# stdlib-only and safe to import at module load; the unit tests confirm it.
import pmove_sim as PM                           # noqa: E402  (pure stdlib)
import verify_route as VR                        # noqa: E402  (pure stdlib)
import route_metrics as RM                       # noqa: E402  (pure stdlib)
# the move-head decode + sim-state encoders live in the closed-loop eval; import the
# DECODE constants/helpers (pure python, deps-free) so dry-route reuses the SAME
# usercmd magnitude + sign convention the closed-loop gate uses. The heavy torch
# path is reached only through run_policy_rollout, which lazy-imports torch itself.
import eval_broad_closedloop as CL               # noqa: E402  (deps-free glue)
# the SHARED turn-direction helpers (pure stdlib) — the SAME wrap180 / yaw_rate the
# offline build and the closed-loop eval use, so the dry-route policy obs AND the
# action-trace columns are parity-identical (no second copy of the angle math).
from features.agent_observation import (                                    # noqa: E402
    yaw_rate_degps as AO_yaw_rate_degps,
    wrap180 as AO_wrap180,
    _VEL_HEADING_FLOOR as AO_VEL_HEADING_FLOOR,
    # v5 sequence-history: the SHARED flat-history assembly + length, so the dry-route
    # policy SELF input is byte-identical to the offline build + the closed-loop eval.
    assemble_self_history as AO_assemble_self_history,
    SELF_HISTORY as AO_SELF_HISTORY,
)

GATE_ROUTE_PCT = 80.0
GATE_SPEED_PCT = 80.0
# ACTION-TRACE CSV header (the per-tick policy-vs-human row order). Kept as a module
# const so the writer, the analyzer's CSV reader, and the tests agree on ONE order.
TRACE_COLUMNS = [
    "t", "onground", "yaw", "yaw_rate", "vh", "vel_heading", "face_vel_angle",
    "pol_fwd", "pol_side", "pol_up", "pol_jump",
    "hum_fwd", "hum_side", "hum_jump", "hum_vh",
]
# down-trace target margin below the censused void floor (qu): far enough that a real
# floor is always caught above it, so "trace reached the bottom" cleanly means void.
VOID_TRACE_MARGIN = 32.0
# fallback void floor when a route has no censused hard gap (no void_floor_z): trace
# to the BSP's practical bottom so over_void still resolves (no route in scope hits
# this, but keep the classification total).
VOID_TRACE_FLOOR_FALLBACK = -4096.0


# =============================================================================
# PURE-PYTHON GLUE (no torch — unit-tested deps-free with a FAKE rollout).
# =============================================================================
def route_void_floor_z(route) -> float:
    """The z a straight-down trace aims for to decide over_void on this route: the
    censused final-hard-gap void_floor_z minus a margin, or a deep fallback when the
    route has no hard gap. Pure."""
    geom = route.get("geom")
    if geom and geom.get("void_floor_z") is not None:
        return float(geom["void_floor_z"]) - VOID_TRACE_MARGIN
    return VOID_TRACE_FLOOR_FALLBACK


def over_void_at(world, origin, floor_z) -> bool:
    """True iff a straight-DOWN swept player trace from `origin` to (x, y, floor_z)
    hits NO solid floor — i.e. the player is over the void. Uses the SAME
    pmove_sim.player_trace the movement sim uses; Trace.fraction >= 1.0 means the
    sweep reached the endpoint without hitting a solid plane (over the void). A
    startsolid/allsolid origin (inside geometry) is NOT over void (fraction 0)."""
    ox, oy, oz = float(origin[0]), float(origin[1]), float(origin[2])
    tr = PM.player_trace(world, [ox, oy, oz], [ox, oy, float(floor_z)])
    # fraction < 1.0 -> hit a solid floor on the way down (grounded over something);
    # fraction >= 1.0 -> swept the full way down with no solid hit -> over the void.
    return bool(tr.fraction >= 1.0)


def make_row(t, origin, vel, onground, over_void, goal):
    """Build ONE route-scorer row (the dict verify_route / route_metrics consume) from
    a per-tick sim state. Keys: t, x, y, z, vh=hypot(vx,vy), onground (0/1), over_void
    (0/1), dist_goal (3-D distance to the route goal). Pure python."""
    ox, oy, oz = float(origin[0]), float(origin[1]), float(origin[2])
    vx, vy = float(vel[0]), float(vel[1])
    gx, gy, gz = float(goal[0]), float(goal[1]), float(goal[2])
    return {
        "t": float(t),
        "x": ox, "y": oy, "z": oz,
        "vh": math.hypot(vx, vy),
        "onground": 1 if onground else 0,
        "over_void": 1 if over_void else 0,
        "dist_goal": math.sqrt((ox - gx) ** 2 + (oy - gy) ** 2 + (oz - gz) ** 2),
    }


# =============================================================================
# ACTION-TRACE (the per-tick POLICY-vs-HUMAN diagnostic). Pure python; OFF the
# normal path (only emitted when --trace-actions is set). Compares what the policy
# DID each tick to what the human actually did on the SAME route + SAME replayed
# yaw, so we can tell UNDER-PRODUCTION (low side/jump/fwd vs human) from WRONG-SIGN
# (strafes as often as the human but the wrong way) — see analyze_action_trace.
# =============================================================================
# the action-trace's wrap is THE shared agent_observation.wrap180 (single source of
# truth) so the trace's yaw_rate / face_vel_angle columns match the OBS feature math
# byte-for-byte (no second, drift-prone copy). Kept under the module-local name the
# trace builders + tests already use.
_wrap180 = AO_wrap180
# THE shared 80 qu/s velocity-heading floor from agent_observation.self_features. The
# trace's vel_heading / face_vel_angle columns MUST mirror it exactly: below this
# horizontal-speed floor the velocity heading is undefined, so self_features emits a
# ZEROED heading (vel_heading sincos = 0) AND face_vel_angle_norm = 0. Reusing the SAME
# constant (not a re-hardcoded 80.0) guarantees train/trace parity in the low-speed
# cold-start/bleed band the action-trace exists to diagnose — they cannot drift.
_VEL_HEADING_FLOOR = AO_VEL_HEADING_FLOOR


def make_trace_row(t, *, onground, yaw, yaw_prev, msec, vx, vy,
                   pol_fwd, pol_side, pol_up, pol_jump,
                   hum_fwd, hum_side, hum_jump, hum_vh):
    """Build ONE action-trace row (dict, TRACE_COLUMNS order) from a per-tick policy
    state + the human usercmd that tick. Pure python.

      * yaw_rate     = _wrap180(yaw - yaw_prev) / (msec/1000) -> deg/s view-yaw turn
        rate (yaw_prev is the PREVIOUS tick's replayed view yaw; 0.0 for the first row
        so its rate is 0 by convention).
      * vh           = hypot(vx, vy) — the POST-frame horizontal speed (the outcome).
      * vel_heading  = atan2(vy, vx) in DEGREES — the direction the bot is actually
        moving. BELOW the shared 80 qu/s velocity-heading floor (_VEL_HEADING_FLOOR, the
        SAME guard agent_observation.self_features applies) the heading is undefined, so
        BOTH vel_heading AND face_vel_angle read 0 — exactly what the OBS saw, so the
        trace does not mis-explain the slow cold-start/bleed ticks it exists to diagnose.
      * face_vel_angle = _wrap180(yaw - vel_heading) — how far the bot's facing is off
        its travel direction (the air-strafe geometry: a good strafe holds a small,
        consistent offset). 0 below the floor (mirrors self_features.face_vel_angle_norm).

    pol_* are the decoded policy usercmd (fwd_mag/side_mag/up_mag in +-MOVE_MAG/0,
    jump_bit in {0, BUTTON_JUMP}). hum_* are the human usercmd that tick (raw
    forwardmove/sidemove ints and the human jump bit (buttons & BUTTON_JUMP)). hum_vh
    is the human's RECORDED horizontal speed that tick (hypot of the human velocity) —
    the believable reference outcome the policy's vh is compared against."""
    vxf, vyf = float(vx), float(vy)
    vh = math.hypot(vxf, vyf)
    yaw_f = float(yaw)
    # SAME 80 qu/s velocity-heading floor as agent_observation.self_features: below it the
    # heading is undefined, so vel_heading AND the derived face_vel_angle BOTH read 0 (the
    # obs emitted a zeroed heading + face_vel_angle_norm=0 there). At/above the floor it is
    # atan2(vy,vx) in degrees and face_vel_angle = wrap180(yaw - vel_heading). This mirrors
    # the exact threshold + semantics so the trace cannot report a nonzero look-vs-move
    # angle on a low-speed tick the real observation scored as zero (train/trace parity).
    if vh >= _VEL_HEADING_FLOOR:
        vel_heading = math.degrees(math.atan2(vyf, vxf))
        face_vel_angle = _wrap180(yaw_f - vel_heading)
    else:
        vel_heading = 0.0
        face_vel_angle = 0.0
    dt = float(msec) / 1000.0
    yaw_rate = (_wrap180(yaw_f - float(yaw_prev)) / dt) if dt > 0.0 else 0.0
    return {
        "t": float(t),
        "onground": 1 if onground else 0,
        "yaw": yaw_f,
        "yaw_rate": yaw_rate,
        "vh": vh,
        "vel_heading": vel_heading,
        "face_vel_angle": face_vel_angle,
        "pol_fwd": float(pol_fwd),
        "pol_side": float(pol_side),
        "pol_up": float(pol_up),
        "pol_jump": 1 if pol_jump else 0,
        "hum_fwd": float(hum_fwd),
        "hum_side": float(hum_side),
        "hum_jump": 1 if hum_jump else 0,
        "hum_vh": float(hum_vh),
    }


def write_trace_csv(rows, path) -> None:
    """Write action-trace rows to a CSV at `path` (TRACE_COLUMNS order). stdlib csv;
    floats are written as-is (DictWriter str()s them). Pure I/O — only called when
    --trace-actions is set, so the normal gate path writes no CSV."""
    import csv
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=TRACE_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in TRACE_COLUMNS})


def load_trace_csv(path):
    """Load an action-trace CSV back into rows (numbers coerced to float). The inverse
    of write_trace_csv, so analyze_action_trace can be run on a CSV the runner produced
    on pinnacle. Pure stdlib."""
    import csv
    rows = []
    with Path(path).expanduser().open("r", newline="", encoding="utf-8") as fh:
        for d in csv.DictReader(fh):
            rows.append({k: float(d[k]) for k in TRACE_COLUMNS})
    return rows


def _sign(x: float) -> int:
    """-1 / 0 / +1 sign of x (0 for exactly 0). Pure."""
    if x > 0.0:
        return 1
    if x < 0.0:
        return -1
    return 0


def analyze_action_trace(rows) -> dict:
    """Compare what the POLICY did to what the HUMAN did, over an action trace — the
    diagnostic that separates UNDER-PRODUCTION from WRONG-SIGN. Pure python; takes the
    rows make_trace_row/load_trace_csv produce. Returns a dict of fractions + cadences,
    computed BOTH over all ticks and (the air-strafe question) over AIRBORNE-only ticks.

    The key reads (see each field's note in the returned dict):
      * side_sign_match_vs_human — of the AIRBORNE ticks where the human strafed
        (hum_side != 0), the fraction where sign(pol_side) == sign(hum_side). This is
        CONVENTION-FREE (sign only): it answers "when the human air-strafed, did the
        policy strafe the SAME way?" A low value with HIGH pol_side_active_frac =>
        WRONG-SIGN (the policy strafes a lot but the wrong direction — a deeper problem
        than a reweight can fix). Near 1.0 => the policy strafes the right way and any
        speed gap is UNDER-PRODUCTION, not mis-direction.
      * pol_jump_per_s vs hum_jump_per_s — jump cadence (re-jumps/s). The bunnyhop needs
        a jump every time it lands; LOW pol vs hum => it is not re-jumping (it coasts).
      * pol_fwd_press_frac vs hum_fwd_press_frac — fraction of ticks with fwd > 0.
      * pol_side_active_frac vs hum_side_active_frac — fraction with side != 0 (is it
        strafing at ALL). LOW vs human (with side_sign_match high on what it DOES do) is
        the UNDER-PRODUCTION signature a reweight lever targets.
      * mean_airborne_vh_pol vs mean_airborne_vh_hum — the OUTCOME (mean airborne
        horizontal speed). The gap this whole trace explains.

    Empty / all-grounded inputs return zeros (and the airborne denominators are 0), so
    a caller can always read the dict without guarding for division."""
    rows = list(rows)
    n = len(rows)
    air = [r for r in rows if int(r["onground"]) == 0]
    n_air = len(air)

    def _frac(seq, pred):
        s = list(seq)
        return (sum(1 for r in s if pred(r)) / len(s)) if s else 0.0

    def _per_s(seq, key):
        """jump cadence over a row subset: total jump presses / total wall time. Uses
        the trace's own dt (no msec column -> fall back to the t deltas)."""
        s = list(seq)
        if len(s) < 2:
            return 0.0
        dur = float(s[-1]["t"]) - float(s[0]["t"])
        presses = sum(1 for r in s if int(r[key]) == 1)
        return (presses / dur) if dur > 0.0 else 0.0

    def _mean(seq, key):
        s = list(seq)
        return (sum(float(r[key]) for r in s) / len(s)) if s else 0.0

    # side-sign agreement, AIRBORNE + human-strafing only (the believability question).
    air_hum_strafe = [r for r in air if _sign(r["hum_side"]) != 0]
    side_match = (
        sum(1 for r in air_hum_strafe
            if _sign(r["pol_side"]) == _sign(r["hum_side"])) / len(air_hum_strafe)
        if air_hum_strafe else 0.0)

    return {
        "n_ticks": n,
        "n_airborne_ticks": n_air,
        "n_airborne_human_strafe_ticks": len(air_hum_strafe),
        # --- the headline: same-way air-strafe agreement (sign only, convention-free) -
        "side_sign_match_vs_human": round(side_match, 6),
        # --- production fractions: is the policy doing the inputs AT ALL vs the human --
        "pol_side_active_frac": round(_frac(rows, lambda r: _sign(r["pol_side"]) != 0), 6),
        "hum_side_active_frac": round(_frac(rows, lambda r: _sign(r["hum_side"]) != 0), 6),
        "pol_side_active_frac_air": round(_frac(air, lambda r: _sign(r["pol_side"]) != 0), 6),
        "hum_side_active_frac_air": round(_frac(air, lambda r: _sign(r["hum_side"]) != 0), 6),
        "pol_fwd_press_frac": round(_frac(rows, lambda r: float(r["pol_fwd"]) > 0.0), 6),
        "hum_fwd_press_frac": round(_frac(rows, lambda r: float(r["hum_fwd"]) > 0.0), 6),
        "pol_fwd_press_frac_air": round(_frac(air, lambda r: float(r["pol_fwd"]) > 0.0), 6),
        "hum_fwd_press_frac_air": round(_frac(air, lambda r: float(r["hum_fwd"]) > 0.0), 6),
        # --- jump cadence (re-jumps/s): is the policy re-jumping like the human? -------
        "pol_jump_per_s": round(_per_s(rows, "pol_jump"), 6),
        "hum_jump_per_s": round(_per_s(rows, "hum_jump"), 6),
        "pol_jump_press_frac": round(_frac(rows, lambda r: int(r["pol_jump"]) == 1), 6),
        "hum_jump_press_frac": round(_frac(rows, lambda r: int(r["hum_jump"]) == 1), 6),
        # --- the outcome the whole trace explains: airborne horizontal speed ----------
        # pol = the bot's own post-frame speed on AIRBORNE ticks; hum = the human's
        # RECORDED speed (hum_vh) on those SAME airborne ticks (the believable target).
        "mean_airborne_vh_pol": round(_mean(air, "vh"), 6),
        "mean_airborne_vh_hum": round(_mean(air, "hum_vh"), 6),
        "mean_face_vel_angle_air": round(_mean(air, "face_vel_angle"), 6),
        "interpretation": (
            "LOW pol_side_active/jump/fwd vs human => UNDER-PRODUCTION (reweight lever). "
            "HIGH pol_side_active_frac_air but LOW side_sign_match_vs_human => WRONG-SIGN "
            "(strafes as much as the human but the wrong way — deeper than a reweight)."),
    }


def auto_seed_from_human(frames, *, min_hspeed=200.0):
    """Cold-start SUSTAIN diagnostic seed: the WORLD-FRAME velocity [vx,vy,vz] of the
    FIRST human frame whose horizontal speed hypot(vx,vy) >= `min_hspeed` (qu/s), else
    None (no frame is fast enough -> fall back to no seed). The human's own velocity is
    already world-frame AND route-aligned, and the 200 qu/s floor clears the policy's
    80 qu/s velocity-heading floor (below which agent_observation.self_features emits a
    degenerate (0,0) heading), so the seed is in-distribution. Pure python."""
    for f in frames:
        vx, vy = float(f["velocity"][0]), float(f["velocity"][1])
        if math.hypot(vx, vy) >= min_hspeed:
            return list(f["velocity"])
    return None


def human_rows_from_cmds(frames, world, route):
    """POSITIVE control rows: build scorer rows straight from the route .cmds human
    origins/velocities (NOT replayed through the sim — the human path IS the positive
    control). over_void is computed with the same down-trace as the policy/stall rows
    so all three controllers share one over_void definition. Pure python given a
    loaded `world` (the trace needs the BSP) — torch-free."""
    goal = route["goal"]
    floor_z = route_void_floor_z(route)
    rows = []
    t = 0.0
    for f in frames:
        t += float(f["msec"]) / 1000.0
        ov = over_void_at(world, f["origin"], floor_z)
        rows.append(make_row(t, f["origin"], f["velocity"],
                             onground=False, over_void=ov, goal=goal))
    return rows


def score_rows(rows, route, human_tws, *, reach=None):
    """Score one controller's rows -> the gated metrics + the harder diagnostics.

    GATED: route% (verify_route.route_progress on the route's human path geometry) and
    speed% (100 * time_weighted_speed(rows) / human_tws). PASS = route% >= 80 AND
    speed% >= 80 (the dead-stop-proof time_weighted_speed is the speed numerator).

    DIAGNOSTIC (NOT gated): verify_route.classify() class + closest-RL, and
    route_metrics.edge_speed at the censused launch edge vs the required launch speed.

    `route` must already be loaded via VR.load_route (carries human path H/cum, goal,
    tele_entrances, gap, geom). `human_tws` is the speed% denominator (the human
    path's own time_weighted_speed). Pure python.

    TELEPORT-CONSISTENCY GUARD: legit_segment() is applied ONCE here, up front, and
    EVERY metric (route%, speed%, classify, edge_speed) is computed on that SAME
    truncated `seg` -- exactly as verify_route.main() does. Without it, route% would
    see the FULL stream (including positions AFTER a STRAY teleporter, which can dump
    the bot near a late human-path point -> a high route%) while speed% saw only the
    legit pre-teleport segment time_weighted_speed truncates to (fast -> high speed%),
    so a run that legitimately covered ~10% then took a stray teleporter to the goal
    could score a FALSE PASS. Scoring every metric on one legit segment closes that."""
    H, cum, _hmean = route["_human"]
    reach = VR.REACH_RL if reach is None else reach
    # Truncate at the first STRAY (non-sanctioned) teleport ONCE, then score EVERY
    # metric on this SAME segment so route% and speed% can never disagree about which
    # part of the run is legit (time_weighted_speed re-applies legit_segment internally;
    # that re-truncation is idempotent on an already-legit segment).
    seg = VR.legit_segment(rows, route["tele_entrances"])
    route_pct = VR.route_progress(H, cum, seg)
    tws = RM.time_weighted_speed(seg, route["tele_entrances"], reach=reach)
    speed_pct = (100.0 * tws / human_tws) if human_tws else 0.0
    passed = (route_pct >= GATE_ROUTE_PCT) and (speed_pct >= GATE_SPEED_PCT)

    # harder diagnostics (reported, not gated) -- on the SAME legit segment.
    cls, closest_rl, _edge_speed_grounded, vreq = VR.classify(seg, route["geom"])
    ev = RM.edge_speed(seg, route["gap"], route["tele_entrances"])
    return {
        "passed": bool(passed),
        "route_pct": round(route_pct, 3),
        "speed_pct": round(speed_pct, 3),
        "time_weighted_speed_qu_per_s": round(tws, 3),
        "n_rows": len(seg),
        "n_rows_full": len(rows),
        "gate": {"route_pct_min": GATE_ROUTE_PCT, "speed_pct_min": GATE_SPEED_PCT,
                 "criterion": "route% >= 80 AND speed% >= 80 (time_weighted_speed)"},
        "diagnostics_not_gated": {
            "classify": cls,
            "closest_rl_qu": round(closest_rl, 3),
            "reached_rl": cls == "REACHED_RL",
            "launch_edge_speed_qu_per_s": (round(ev, 3) if ev is not None else None),
            "launch_required_speed_qu_per_s": (round(float(vreq), 3) if vreq else None),
            "cleared_launch": (ev is not None and vreq and ev >= float(vreq)) or False,
            "note": ("REACHED_RL + launch-edge speed are the HARDER diagnostics, NOT "
                     "the robustness gate (all 11 dm3 routes end in a ~525 qu/s hard "
                     "leap a move-only yaw-replay policy is not expected to clear yet)."),
        },
    }


def controls_bracket(human_result, stall_result) -> bool:
    """The gate is VALID iff the human-path control PASSES and the stall control FAILS.
    A gate that fails the policy but ALSO fails the human, or passes the do-nothing
    stall, is not a valid gate. Pure python."""
    return bool(human_result.get("passed") is True
                and stall_result.get("passed") is False)


# =============================================================================
# ROLLOUTS. The stall + human-path controllers are torch-FREE (they only need the
# BSP world). The policy controller lazy-imports torch + the encoders inside
# run_policy_rollout, exactly like eval_broad_closedloop.closed_loop_rollout.
# =============================================================================
def stall_rows(frames, world, route):
    """NEGATIVE control rows: drive pmove_sim from the human start with an IDLE
    usercmd (0,0,0, no jump) every tick, replaying the human view yaw/pitch (so the
    only difference from the policy is the move intent). A move-only idle bot does not
    translate, so route%/speed% collapse -> the gate must FAIL. torch-free (sim +
    world only). Returns the scorer rows."""
    goal = route["goal"]
    floor_z = route_void_floor_z(route)
    pm = PM.Pmove(world)
    f0 = frames[0]
    st = PM.PlayerState(list(f0["origin"]), list(f0["velocity"]))
    rows = []
    t = 0.0
    n = len(frames) - 1            # one fewer step (frame[k] view onto bot state)
    for k in range(n):
        f = frames[k]
        angles = [float(f["angles"][0]), float(f["angles"][1]), 0.0]  # human view
        cmd = PM.Cmd(int(f["msec"]), angles, [0.0, 0.0, 0.0], 0)       # idle, no jump
        pm.run_frame(st, cmd)
        t += float(f["msec"]) / 1000.0
        ov = over_void_at(world, st.origin, floor_z)
        rows.append(make_row(t, st.origin, st.velocity, st.onground, ov, goal))
    return rows


def run_policy_rollout(frames, world, route, *, model, dims, encode_obs, stats,
                       torch_mod, map_name="dm3", n_max=7, device="cpu",
                       seed_velocity=None, trace_out=None, aim_mode="replayed",
                       jump_mode="policy", tick_goals=None):
    """POLICY rollout: the trained BROAD policy drives pmove_sim closed-loop down the
    route, replaying the human view yaw/pitch per tick. Mirrors
    eval_broad_closedloop.closed_loop_rollout's loop (sim's own evolving state fed
    back each tick), but captures the route-scorer rows (t/x/y/z/vh/onground/over_void/
    dist_goal) instead of gmv ticks. NEEDS torch (caller passes the imported module +
    the encode_observation fn). Returns the scorer rows + the predicted attack classes.

    seed_velocity (the cold-start SUSTAIN diagnostic): when given, the sim is initialized
    at this WORLD-FRAME velocity (3-vector, qu/s) instead of the human's frame-0 velocity,
    so the policy rollout STARTS from motion. This splits "can't self-start" (idle from a
    standstill) from "can't sustain" (given speed, does it keep air-strafing). The sim
    evolves it from there; the policy reads the POST-frame velocity each tick via
    CL._self_state_from_sim. Seeds the POLICY rollout ONLY — never the controls.

    trace_out (the per-tick ACTION-TRACE diagnostic): when a list is passed, ONE
    make_trace_row per tick is appended — what the POLICY did (decoded fwd/side/up/jump
    + the resulting onground/yaw/vh/headings) alongside what the HUMAN did that tick
    (frames[k] move/buttons/velocity). OFF the normal path (the gate/scorer rows + exit
    behavior are unchanged whether or not trace_out is given). Used by --trace-actions.

    tick_goals (the v4/v5 route-conditioning GOAL fed to the POLICY obs): an optional
    per-tick list (len == n steps) of (gx, gy) | None, the SAME hindsight next-resource
    goal the OFFLINE build stamps (route_goals.label_episode_goals over the recorded
    positions; computed by the caller from THESE frames' origins + the SAME resource_coords
    -> train/serve parity). When given, self_state["goal"]=tick_goals[k] each tick so
    AO.self_features emits the real goal channels. When None (the goal-BLIND control) the
    goal key is never set -> the encoder's [0,0,1] free-roam default (the prior pre-fix
    behaviour). NOTE: this is the per-tick hindsight RESOURCE goal, NOT route["goal"] (the
    3-D route endpoint) — route["goal"] still drives make_row's dist_goal / the scorer, but
    the policy OBS sees the build's resource-leg goal so the conditioning matches training.
    """
    goal = route["goal"]
    floor_z = route_void_floor_z(route)
    pm = PM.Pmove(world)
    f0 = frames[0]
    st = PM.PlayerState(list(f0["origin"]),
                        list(seed_velocity) if seed_velocity is not None
                        else list(f0["velocity"]))
    rows = []
    attack_classes = []
    t = 0.0
    # previous replayed view yaw — the SINGLE source for both the OBS turn-direction
    # signal (yaw_rate in the self_state) AND the action-trace yaw_rate column. Seeded to
    # frame-0 yaw so the first tick's delta is 0 (== the build's first-tick=0 convention).
    yaw_prev = float(f0["angles"][1])
    # v5 SEQUENCE history: rolling buffer of the last SELF_HISTORY SELF feature-vectors,
    # OLDEST -> NEWEST, RESET here at rollout start. Each tick appends enc["self"] and the
    # flat [SELF_HISTORY*SELF_DIM] history is assembled by the SHARED helper (same order +
    # left-pad-repeat-first as the offline build / closed-loop eval) -> train==serve parity.
    from collections import deque
    self_hist = deque(maxlen=AO_SELF_HISTORY)
    f_ent = dims["f_ent"]
    n = len(frames) - 1
    for k in range(n):
        f = frames[k]
        yaw = float(f["angles"][1])
        pitch = float(f["angles"][0])
        angles = [pitch, yaw, 0.0]
        # turn-rate from the previous replayed yaw + this tick's dt, via the SAME shared
        # helper the offline build + closed-loop eval call (parity). On tick 0 yaw_prev==yaw
        # so the delta is 0 — byte-identical to the build's first-tick=0.0.
        yaw_rate = AO_yaw_rate_degps(yaw, yaw_prev, float(f["msec"]) / 1000.0)
        # per-tick route-conditioning goal (the build's hindsight next-resource, supplied by
        # the caller from these frames' origins + the SAME resource_coords). None -> free-roam
        # [0,0,1] (the goal-blind control). NOT route["goal"] (the route endpoint) — see the
        # docstring: the policy obs must see the build's resource-leg goal for train parity.
        tick_goal = tick_goals[k] if tick_goals is not None else None
        # SAME self_state + obs encode the closed-loop gmv eval uses (solo-roam: [] ), now
        # carrying yaw_rate (turn-direction) AND the per-tick goal (route-conditioning) so the
        # appended v3/v4 features are populated at inference exactly as in training.
        self_state = CL._self_state_from_sim(st, yaw, pitch, yaw_rate=yaw_rate, goal=tick_goal)
        enc = encode_obs(self_state, [], stats, map_name, n_max)
        # push this tick's SELF, then assemble the FLAT [SELF_HISTORY*SELF_DIM] history via
        # the SHARED helper (same oldest->newest order + left-pad-repeat-first as the build)
        # -> the v5 model SELF input, byte-identical to training.
        self_hist.append(enc["self"])
        self_in = AO_assemble_self_history(self_hist, AO_SELF_HISTORY)
        obs_t = torch_mod.tensor([self_in], dtype=torch_mod.float32, device=device)
        if f_ent > 0:
            ent_t = torch_mod.tensor([enc["ents"]], dtype=torch_mod.float32, device=device)
            em_t = torch_mod.tensor([enc["mask"]], dtype=torch_mod.float32, device=device)
        else:
            ent_t = torch_mod.zeros((1, n_max, 0), device=device)
            em_t = torch_mod.zeros((1, n_max), device=device)
        aux_t = torch_mod.zeros((1, dims["f_aux"]), device=device)
        with torch_mod.no_grad():
            logits = model(obs_t, ent_t, em_t, aux_t)
        pred_cls = [int(lg.argmax(dim=1).item()) for lg in logits]
        fwd_mag, side_mag, up_mag, jump_bit = CL.decode_move_heads(pred_cls)
        attack_classes.append(pred_cls[4])

        # AIM OVERRIDE (perfect-aim diagnostic). aim_mode="optimal" replaces the EXECUTED
        # view yaw with the speed-optimal (wishdir _|_ horizontal velocity) angle computed
        # from the bot's OWN pre-frame velocity + the policy's chosen move keys. The obs
        # above already used the REPLAYED yaw (trained distribution), and yaw_prev below keeps
        # tracking the replayed yaw -> the ONLY manipulated variable is the executed aim, so
        # this isolates "does fixing aim alone sustain speed / reach goal?". No effect when
        # aim_mode="replayed" (the default == the unchanged baseline path).
        if aim_mode == "optimal":
            exec_yaw = CL.optimal_strafe_yaw(st.velocity[0], st.velocity[1],
                                             fwd_mag, side_mag, yaw)
            angles = [pitch, exec_yaw, 0.0]

        # JUMP OVERRIDE (jump-cadence diagnostic). jump_mode="hold" forces the jump button
        # EVERY tick so the engine auto-hops on landing (pm_ktjump: pressed-while-airborne ->
        # auto-jump on land = the continuous bunnyhop cadence). Tests whether the bottleneck is
        # jump-cadence regulation (the policy under/over-jumps). "policy" = unchanged baseline
        # (the jump head decides). Only the jump button is touched; moves/aim are unchanged.
        if jump_mode == "hold":
            jump_bit = CL.BUTTON_JUMP

        cmd = PM.Cmd(int(f["msec"]), angles, [fwd_mag, side_mag, up_mag], jump_bit)
        pm.run_frame(st, cmd)
        t += float(f["msec"]) / 1000.0
        ov = over_void_at(world, st.origin, floor_z)
        rows.append(make_row(t, st.origin, st.velocity, st.onground, ov, goal))
        if trace_out is not None:
            # ACTION-TRACE: the POST-frame policy outcome (st.velocity/onground, this
            # tick's replayed yaw) vs the HUMAN usercmd + recorded speed for frame[k].
            hf = frames[k]
            hum_v = hf["velocity"]
            trace_out.append(make_trace_row(
                t, onground=st.onground, yaw=yaw, yaw_prev=yaw_prev,
                msec=int(f["msec"]), vx=st.velocity[0], vy=st.velocity[1],
                pol_fwd=fwd_mag, pol_side=side_mag, pol_up=up_mag, pol_jump=jump_bit,
                hum_fwd=hf["move"][0], hum_side=hf["move"][1],
                hum_jump=bool(int(hf["buttons"]) & CL.BUTTON_JUMP),
                hum_vh=math.hypot(float(hum_v[0]), float(hum_v[1]))))
        yaw_prev = yaw
    return rows, attack_classes


# =============================================================================
# Route loading helper (wraps verify_route.load_route + load_human, carries the
# human path/baseline + the human rows for the positive control & speed% denom).
# =============================================================================
def load_route_with_human(route_name, world):
    """Load a censused route via verify_route, attach (H, cum, hmean) and the human
    scorer rows (built from the .cmds), and compute the human time_weighted_speed
    (the speed% denominator). Confirms load_human's hmean agrees with a
    time_weighted_speed on the human rows (the docstring's required cross-check).
    Returns (route, human_frames, human_rows, human_tws, agreement_dict)."""
    route = VR.load_route(route_name)
    H, cum, hmean = VR.load_human(route)
    route["_human"] = (H, cum, hmean)
    frames = PM.load_cmds_file(str(route["human"]))
    human_rows = human_rows_from_cmds(frames, world, route)
    human_tws = RM.time_weighted_speed(human_rows, route["tele_entrances"],
                                       reach=VR.REACH_RL)
    human_amean = RM.active_mean_speed(human_rows, threshold=1.0, reach=VR.REACH_RL)
    # cross-check (required by the design): load_human's hmean — the human active-mean
    # over the .cmds speed columns to goal arrival — must agree with the dead-stop-proof
    # time_weighted_speed on the rows BUILT from the same .cmds (both are total-traversal
    # speeds to arrival; they coincide to ~0.5 qu/s because the human path has no
    # dead-stops, so the two denominators — counted-ticks vs wall-time — match). We
    # report the active_mean too, but it is the hmean<->tws agreement that validates the
    # row build (active_mean drops sub-threshold ticks, so it sits a few qu/s higher).
    agreement = {
        "load_human_hmean_qu_per_s": round(hmean, 3),
        "rows_time_weighted_speed_qu_per_s": round(human_tws, 3),
        "rows_active_mean_qu_per_s": round(human_amean, 3),
        "hmean_vs_rows_tws_agree": abs(hmean - human_tws) < 5.0,
        "hmean_minus_rows_tws_qu_per_s": round(hmean - human_tws, 3),
    }
    return route, frames, human_rows, human_tws, agreement


# =============================================================================
# Report assembly.
# =============================================================================
def build_report(route_name, route, *, human_result, stall_result, policy_result,
                 human_tws, agreement, inputs, provenance,
                 seed=None, seed_mode="none") -> dict:
    bracket = controls_bracket(human_result, stall_result)
    # the cold-start sustain diagnostic seed (POLICY rollout only) is recorded in inputs
    # so a report reader can tell a from-standstill run from a from-motion diagnostic.
    inputs = dict(inputs)
    inputs["seed_velocity"] = [round(v, 1) for v in seed] if seed else None
    inputs["seed_mode"] = seed_mode
    report = {
        "schema": "komodobots.eval_broad_dryroute.v1",
        "eval_mode": "dry_route_robustness",
        "route": route_name,
        "gate": {
            "criterion": "route%% >= %g AND speed%% >= %g" % (GATE_ROUTE_PCT, GATE_SPEED_PCT),
            "speed_metric": "route_metrics.time_weighted_speed (dead-stop-proof)",
            "route_metric": "verify_route.route_progress (arc-length on human path, on-route only)",
            "reached_rl_required": False,
            "why_not_reached_rl": ("all 11 censused dm3 routes end in a ~525 qu/s HARD "
                                   "leap; a move-only yaw-replay BC policy is not expected "
                                   "to clear it yet, so REACHED_RL + launch-edge speed are "
                                   "harder DIAGNOSTICS, not the robustness gate."),
        },
        "human_baseline": {
            "route_arc_length_qu": round(route["_human"][1][-1], 2),
            "human_time_weighted_speed_qu_per_s": round(human_tws, 3),
            "speed_pct_denominator": "human_time_weighted_speed_qu_per_s",
            "agreement_check": agreement,
        },
        "controls": {
            "human_path_positive": human_result,     # expect PASS (route~100/speed~100)
            "stall_negative": stall_result,          # expect FAIL (idle -> ~0/~0)
            "bracket_valid": bracket,
            "bracket_rule": "VALID iff human-path PASSES and stall FAILS",
        },
        "bot_policy": policy_result,                 # the MEASUREMENT (may FAIL the gate)
        "inputs": inputs,
        "caveats": _build_caveats(),
        "provenance": provenance,
    }
    return report


def _build_caveats() -> dict:
    return {
        "eval_mode": "dry_route_robustness",
        "gate_is_not_reached_rl": (
            "PASS = route% >= 80 AND speed% >= 80 (time_weighted_speed). REACHED_RL "
            "and launch-edge speed are reported as separate HARDER diagnostics, never "
            "the gate — the move-only policy is not expected to clear the hard leap."),
        "aim_head": "REPLAYED",
        "aim_head_detail": (
            "The BROAD policy clones movement/jump/attack but NOT view; view yaw/pitch "
            "is REPLAYED from the recorded human per tick. route%/speed% measure the "
            "bot's own translation under the human's facing intent."),
        "solo_roam": (
            "No enemies in the sim -> encode_observation called with observed_others=[] "
            "(entity channel all-pad + zero mask), same as the closed-loop gmv eval."),
        "move_magnitude": (
            "Move-head -> usercmd magnitude = +-400 (trainer /400 scale, "
            "eval_broad_closedloop.MOVE_MAG). Sign drives direction; magnitude drives "
            "speed (the speed% the gate keys on)."),
        "over_void": (
            "over_void is a straight-DOWN pmove_sim.player_trace to the censused "
            "void_floor_z minus a margin; Trace.fraction>=1.0 (no solid hit) -> over "
            "void, excluded from route% (verify_route.route_progress's own rule)."),
        "controls": (
            "human-path (positive, must PASS) and idle-stall (negative, must FAIL) "
            "bracket the policy so the gate is shown valid; a non-bracketing run exits "
            "nonzero (code 4)."),
    }


# =============================================================================
# Orchestration.
# =============================================================================
def run_controls_only(bsp: Path, route_name: str) -> dict:
    """Run ONLY the human-path (positive) + stall (negative) controls — NO torch. This
    proves the gate is VALID (controls bracket) on a deps-light box, and is the path
    the unit-testable / runnable-without-torch validity check uses. The policy field is
    omitted (None)."""
    world = PM.WorldModel.load(str(Path(bsp).expanduser()))
    route, frames, human_rows, human_tws, agreement = load_route_with_human(route_name, world)
    human_result = score_rows(human_rows, route, human_tws)
    s_rows = stall_rows(frames, world, route)
    stall_result = score_rows(s_rows, route, human_tws)
    from broad_bc import core as _core
    return build_report(
        route_name, route,
        human_result=human_result, stall_result=stall_result, policy_result=None,
        human_tws=human_tws, agreement=agreement,
        inputs={"bsp": str(Path(bsp).expanduser()), "route": route_name,
                "controls_only": True, "human_frames": len(frames)},
        provenance={"git_sha": _core.git_sha(REPO_ROOT), "torch": None, "device": None},
    )


def run_eval(checkpoint: Path, bsp: Path, route_name: str, *,
             norm_artifact: Path | None = None,
             map_name: str = "dm3", n_max: int = 7, cpu: bool = False,
             seed_velocity=None, seed_from_human=False, trace_actions=None,
             aim_mode="replayed", jump_mode="policy",
             goal_mode="conditioned", resource_coords_path: Path | None = None) -> dict:
    """Full dry-route robustness eval: human-path + stall controls AND the real policy
    rollout. NEEDS torch (policy forward) + the BSP world. The encoders/loaders are
    lazy-imported here (module stays importable on bare stdlib).

    seed_velocity / seed_from_human (the cold-start SUSTAIN diagnostic): start the POLICY
    rollout from MOTION instead of the human's frame-0 velocity, to split "can't
    self-start" from "can't sustain". `seed_velocity` is an explicit world-frame 3-vector
    (qu/s); `seed_from_human` instead picks the human's velocity at the first frame with
    hspeed >= 200 qu/s (auto_seed_from_human). The seed is applied to the POLICY rollout
    ONLY — the human-path and stall controls keep their recorded/zero start so the
    controls_bracket gate-validity check stays valid. A seeded run is a DIAGNOSTIC, not
    the gate; the exit-code behavior (controls must bracket) is unchanged.

    trace_actions (the per-tick ACTION-TRACE diagnostic): when a path is given, capture a
    per-tick policy-vs-human row over the POLICY rollout, write it as a CSV at that path,
    and attach analyze_action_trace(rows) to the policy result under "action_trace". OFF
    the normal path (no CSV/analysis unless set); the gate verdict + exit code are
    unchanged."""
    import torch
    from features import agent_observation as AO
    from eval_broad_believability import _build_policy_from_checkpoint
    from broad_bc import core as _core

    device = "cpu" if cpu else ("cuda" if torch.cuda.is_available() else "cpu")
    ckpt = torch.load(Path(checkpoint).expanduser(), map_location=device)
    model, dims, head_dims = _build_policy_from_checkpoint(ckpt, device)
    # the policy's normalization stats are needed by encode_observation. Prefer the
    # explicit --norm-artifact (the SAME artifact the closed-loop eval threads and the
    # trainer used); else fall back to a path embedded in the checkpoint, else the repo
    # gold artifact. Resolving the WRONG stats would silently de-normalize the obs.
    norm_path = _resolve_norm_path(ckpt, norm_artifact)
    stats = json.loads(norm_path.read_text(encoding="utf-8"))
    # Reject a stale/mismatched normalization artifact BEFORE the rollout: the v3 SELF
    # path z-scores yaw_rate_z against per_map[<map>].yaw_rate, so a v2 stats artifact
    # (no yaw_rate, or a registry_version != EXPECTS) would silently de-normalize the
    # appended turn-rate feature. The SAME shared check_norm_artifact the trainer side
    # uses (no drift); raises ValueError loudly if the key is missing.
    from broad_bc import shard_contract as _SC
    _SC.check_norm_artifact(stats, map_name, where=f"norm_artifact={norm_path}")

    world = PM.WorldModel.load(str(Path(bsp).expanduser()))
    route, frames, human_rows, human_tws, agreement = load_route_with_human(route_name, world)

    # route-conditioning v4/v5 GOAL for the POLICY obs: compute the per-tick hindsight
    # next-resource goal the SAME way the OFFLINE build does — route_goals.label_episode_goals
    # over the recorded positions (HERE: the route's human .cmds origins) using the SAME
    # resource_coords artifact (committed dm3 default unless overridden). This is the
    # train/serve parity match: the build labels goals over an episode's recorded human
    # positions, and a censused route's frames ARE such a recorded trajectory, so labelling
    # over frames reproduces the exact training goal signal for this route. goal_mode="blind"
    # passes NO goals (every tick free-roam [0,0,1]) = the controlled-A/B baseline.
    # route_goals is pure stdlib (no duckdb/pyarrow), and the default coords path is its
    # own DEFAULT_RESOURCE_COORDS — so we resolve it WITHOUT importing build_features (which
    # would pull in duckdb at module load and crash this deps-light torch+BSP evaluator).
    # goal_mode="blind" never enters this block, so blind never touches resource coords.
    tick_goals = None
    goal_coords = {}
    goal_coords_path = None          # the resolved coords path, for the report provenance
    if goal_mode == "conditioned":
        sys.path.insert(0, str(REPO_ROOT / "ml" / "pipeline"))
        import route_goals as RG
        if resource_coords_path is not None:
            goal_coords_path = Path(resource_coords_path).expanduser()
            goal_coords = RG.load_resource_coords(goal_coords_path)
        elif map_name == "dm3":
            goal_coords_path = RG.DEFAULT_RESOURCE_COORDS
            goal_coords = RG.load_resource_coords(goal_coords_path)
        if goal_coords:
            positions = [(float(f["origin"][0]), float(f["origin"][1])) for f in frames]
            tick_goals = RG.label_episode_goals(positions, goal_coords, RG.GOAL_RHO)
    n_goal_frames = (sum(1 for g in tick_goals if g is not None)
                     if tick_goals is not None else 0)

    # resolve the cold-start sustain-diagnostic seed for the POLICY rollout ONLY. The
    # controls below keep their recorded/zero start (the bracket must stay valid).
    if seed_velocity is not None:
        seed, seed_mode = list(seed_velocity), "explicit"
    elif seed_from_human:
        seed = auto_seed_from_human(frames)
        seed_mode = "from_human"
    else:
        seed, seed_mode = None, "none"

    human_result = score_rows(human_rows, route, human_tws)
    s_rows = stall_rows(frames, world, route)
    stall_result = score_rows(s_rows, route, human_tws)

    # ACTION-TRACE: only collect per-tick policy-vs-human rows when --trace-actions is
    # set, so the normal gate path is unchanged (no CSV, no extra report field).
    trace_rows = [] if trace_actions is not None else None
    p_rows, p_atk = run_policy_rollout(
        frames, world, route, model=model, dims=dims, encode_obs=AO.encode_observation,
        stats=stats, torch_mod=torch, map_name=map_name, n_max=n_max, device=device,
        seed_velocity=seed, trace_out=trace_rows, aim_mode=aim_mode, jump_mode=jump_mode,
        tick_goals=tick_goals)
    policy_result = score_rows(p_rows, route, human_tws)
    atk_rate = (round(sum(1 for a in p_atk if int(a) == 1) / len(p_atk), 6)
                if p_atk else 0.0)
    policy_result["predicted_attack_rate"] = atk_rate
    if trace_rows is not None:
        trace_path = Path(trace_actions).expanduser()
        write_trace_csv(trace_rows, trace_path)
        policy_result["action_trace"] = {
            "csv": str(trace_path),
            "columns": list(TRACE_COLUMNS),
            "analysis": analyze_action_trace(trace_rows),
        }

    return build_report(
        route_name, route,
        human_result=human_result, stall_result=stall_result, policy_result=policy_result,
        human_tws=human_tws, agreement=agreement,
        inputs={"checkpoint": str(Path(checkpoint).expanduser()),
                "bsp": str(Path(bsp).expanduser()), "route": route_name,
                "aim_mode": aim_mode, "jump_mode": jump_mode,
                "map": map_name, "n_max": n_max, "controls_only": False,
                "norm_artifact": str(norm_path), "human_frames": len(frames),
                "goal_mode": goal_mode,
                "goal_resource_coords": (str(goal_coords_path)
                                         if goal_coords_path is not None else None),
                "goal_n_resources": len(goal_coords),
                "goal_labeled_frames": n_goal_frames,
                "goal_coverage": (round(n_goal_frames / len(frames), 4) if frames else 0.0),
                "trace_actions": (str(Path(trace_actions).expanduser())
                                  if trace_actions is not None else None)},
        provenance={"git_sha": _core.git_sha(REPO_ROOT),
                    "torch": getattr(torch, "__version__", None), "device": device,
                    "norm_artifact_version": stats.get("artifact_version", "UNSET")},
        seed=seed, seed_mode=seed_mode,
    )


def _resolve_norm_path(ckpt, norm_artifact=None) -> Path:
    """Locate the normalization_stats.json the policy was trained against. Precedence:
    an explicit `--norm-artifact` (the SAME artifact the closed-loop eval threads and
    the trainer used); then a path the checkpoint embeds; then the repo gold artifact.
    Raises a clear error if none resolves (so the run never silently uses mismatched
    stats — that would de-normalize every observation)."""
    if norm_artifact is not None:
        p = Path(norm_artifact).expanduser()
        if not p.exists():
            raise SystemExit("--norm-artifact %s does not exist" % p)
        return p
    for key in ("norm_artifact", "norm_artifact_path", "normalization_stats_path"):
        p = ckpt.get(key)
        if p and Path(p).expanduser().exists():
            return Path(p).expanduser()
    gold = REPO_ROOT / "ml" / "gold" / "norm" / "normalization_stats.json"
    if gold.exists():
        return gold
    raise SystemExit(
        "could not resolve normalization_stats.json: pass --norm-artifact, or use a "
        "checkpoint that embeds the path, or place the gold artifact at %s." % gold)


def print_action_trace_summary(a, *, indent="") -> None:
    """Pretty-print analyze_action_trace's dict so the policy-vs-human comparison is
    readable in a run log. Pure I/O. `indent` prefixes each line. Shows the headline
    same-way air-strafe agreement, then the production fractions + jump cadence + the
    speed outcome, side by side (pol vs hum) so the reader can tell UNDER-PRODUCTION
    from WRONG-SIGN at a glance."""
    p = indent
    print("%saction-trace (policy vs human, %d ticks / %d airborne):"
          % (p, a["n_ticks"], a["n_airborne_ticks"]), flush=True)
    print("%s  side_sign_match_vs_human (air, hum-strafing) = %.3f  [over %d ticks]"
          % (p, a["side_sign_match_vs_human"], a["n_airborne_human_strafe_ticks"]),
          flush=True)
    print("%s  side_active_frac   pol=%.3f hum=%.3f  (air: pol=%.3f hum=%.3f)"
          % (p, a["pol_side_active_frac"], a["hum_side_active_frac"],
             a["pol_side_active_frac_air"], a["hum_side_active_frac_air"]), flush=True)
    print("%s  fwd_press_frac     pol=%.3f hum=%.3f  (air: pol=%.3f hum=%.3f)"
          % (p, a["pol_fwd_press_frac"], a["hum_fwd_press_frac"],
             a["pol_fwd_press_frac_air"], a["hum_fwd_press_frac_air"]), flush=True)
    print("%s  jump_per_s         pol=%.3f hum=%.3f  (press_frac pol=%.3f hum=%.3f)"
          % (p, a["pol_jump_per_s"], a["hum_jump_per_s"],
             a["pol_jump_press_frac"], a["hum_jump_press_frac"]), flush=True)
    print("%s  mean_airborne_vh   pol=%.1f hum=%.1f qu/s  (mean face_vel_angle air=%.1f deg)"
          % (p, a["mean_airborne_vh_pol"], a["mean_airborne_vh_hum"],
             a["mean_face_vel_angle_air"]), flush=True)
    print("%s  read: %s" % (p, a["interpretation"]), flush=True)


def main_analyze(argv=None) -> int:
    """Standalone CLI: load an action-trace CSV (written by --trace-actions) and print
    analyze_action_trace on it (and optionally dump the JSON). Lets the runner analyze a
    CSV on pinnacle without re-running the policy:

        python -m ml.eval_broad_dryroute analyze TRACE.csv [--json OUT.json]
    """
    ap = argparse.ArgumentParser(
        prog="eval_broad_dryroute analyze",
        description="analyze a per-tick action-trace CSV (policy vs human)")
    ap.add_argument("csv", type=Path, help="action-trace CSV from --trace-actions")
    ap.add_argument("--json", type=Path, default=None,
                    help="also write the analysis dict as JSON here")
    args = ap.parse_args(argv)
    rows = load_trace_csv(args.csv)
    analysis = analyze_action_trace(rows)
    print("loaded %d trace rows from %s" % (len(rows), args.csv), flush=True)
    print_action_trace_summary(analysis)
    if args.json is not None:
        outp = Path(args.json).expanduser()
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(json.dumps(analysis, indent=2), encoding="utf-8")
        print("wrote %s" % outp, flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--checkpoint", type=Path, default=None,
                    help="broad_bc_policy.pt (omit with --controls-only)")
    ap.add_argument("--bsp", type=Path, required=True,
                    help="dm3.bsp (the map the sim rolls out in)")
    ap.add_argument("--route", default="sng_to_rl",
                    help="censused dm3 route name (default sng_to_rl)")
    ap.add_argument("--out", type=Path, required=True, help="report.json path")
    ap.add_argument("--norm-artifact", type=Path, default=None,
                    help="normalization_stats.json (SAME artifact training used); "
                         "falls back to a checkpoint-embedded path or the repo gold artifact")
    ap.add_argument("--controls-only", action="store_true",
                    help="run human-path + stall controls WITHOUT torch (gate-validity check)")
    ap.add_argument("--cpu", action="store_true", help="force CPU forward")
    ap.add_argument("--map", default="dm3")
    ap.add_argument("--n-max", type=int, default=7)
    ap.add_argument("--seed-velocity", type=float, nargs=3, default=None,
                    metavar=("VX", "VY", "VZ"),
                    help="explicit world-frame starting velocity qu/s for the cold-start "
                         "sustain diagnostic")
    ap.add_argument("--seed-from-human", action="store_true",
                    help="seed the policy from the human's velocity at the first frame "
                         "with hspeed>=200 qu/s")
    ap.add_argument("--trace-actions", type=Path, default=None, metavar="PATH",
                    help="write a per-tick POLICY-vs-HUMAN action-trace CSV to PATH and "
                         "attach analyze_action_trace to the report (diagnostic; needs "
                         "the policy rollout, so not valid with --controls-only)")
    ap.add_argument("--aim", choices=("replayed", "optimal"), default="replayed",
                    help="executed view aim for the POLICY rollout: 'replayed' = human yaw "
                         "(the baseline); 'optimal' = wishdir _|_ velocity (the perfect-aim "
                         "diagnostic). The obs still sees the replayed yaw, so ONLY the "
                         "executed aim changes. Not valid with --controls-only.")
    ap.add_argument("--jump", choices=("policy", "hold"), default="policy",
                    help="jump button for the POLICY rollout: 'policy' = the jump head decides "
                         "(baseline); 'hold' = force jump every tick so the engine auto-hops on "
                         "landing (the bunnyhop-cadence diagnostic). Not valid with --controls-only.")
    ap.add_argument("--goal-mode", choices=("conditioned", "blind"), default="conditioned",
                    help="route-conditioning for the POLICY obs: 'conditioned' (default) feeds "
                         "the per-tick hindsight next-resource GOAL the offline build stamps "
                         "(route_goals.label_episode_goals over the route frames + the SAME "
                         "resource_coords; train/serve parity); 'blind' passes no goal -> "
                         "[0,0,1] free-roam every tick (the prior pre-fix behaviour; the "
                         "controlled-A/B baseline). Not valid with --controls-only.")
    ap.add_argument("--resource-coords", type=Path, default=None,
                    help="resource_coords.<map>.json for the goal label (defaults to the "
                         "committed dm3 artifact for map=dm3; ignored with --goal-mode blind)")
    args = ap.parse_args(argv)

    if args.controls_only:
        if args.trace_actions is not None:
            ap.error("--trace-actions needs the policy rollout; not valid with --controls-only")
        if args.aim != "replayed":
            ap.error("--aim optimal needs the policy rollout; not valid with --controls-only")
        if args.jump != "policy":
            ap.error("--jump hold needs the policy rollout; not valid with --controls-only")
        if args.goal_mode != "conditioned":
            ap.error("--goal-mode needs the policy rollout; not valid with --controls-only")
        report = run_controls_only(args.bsp, args.route)
    else:
        if args.checkpoint is None:
            ap.error("--checkpoint is required unless --controls-only")
        report = run_eval(args.checkpoint, args.bsp, args.route,
                          norm_artifact=args.norm_artifact,
                          map_name=args.map, n_max=args.n_max, cpu=args.cpu,
                          seed_velocity=args.seed_velocity,
                          seed_from_human=args.seed_from_human,
                          trace_actions=args.trace_actions,
                          aim_mode=args.aim, jump_mode=args.jump,
                          goal_mode=args.goal_mode,
                          resource_coords_path=args.resource_coords)

    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    hr = report["controls"]["human_path_positive"]
    sr = report["controls"]["stall_negative"]
    bracket = report["controls"]["bracket_valid"]
    print(f"wrote {out}", flush=True)
    print(f"  route = {report['route']}  human_arc = "
          f"{report['human_baseline']['route_arc_length_qu']} qu  "
          f"human_tws = {report['human_baseline']['human_time_weighted_speed_qu_per_s']} qu/s",
          flush=True)
    _gm = report["inputs"].get("goal_mode")
    if _gm is not None:
        print("  goal_mode = %s  (goal_labeled_frames=%s/%s coverage=%s, n_resources=%s)"
              % (_gm, report["inputs"].get("goal_labeled_frames"),
                 report["inputs"].get("human_frames"),
                 report["inputs"].get("goal_coverage"),
                 report["inputs"].get("goal_n_resources")), flush=True)
    print("  CONTROL human-path : route%%=%.1f speed%%=%.1f -> %s (expect PASS)"
          % (hr["route_pct"], hr["speed_pct"], "PASS" if hr["passed"] else "FAIL"),
          flush=True)
    print("  CONTROL stall      : route%%=%.1f speed%%=%.1f -> %s (expect FAIL)"
          % (sr["route_pct"], sr["speed_pct"], "PASS" if sr["passed"] else "FAIL"),
          flush=True)
    pol = report.get("bot_policy")
    if pol:
        d = pol["diagnostics_not_gated"]
        print("  POLICY (the measurement): route%%=%.1f speed%%=%.1f tws=%.1f qu/s -> %s"
              % (pol["route_pct"], pol["speed_pct"],
                 pol["time_weighted_speed_qu_per_s"], "PASS" if pol["passed"] else "FAIL"),
              flush=True)
        print("    diagnostics(not gated): class=%s closestRL=%.0f qu  edge=%s/%s qu/s cleared_launch=%s"
              % (d["classify"], d["closest_rl_qu"],
                 d["launch_edge_speed_qu_per_s"], d["launch_required_speed_qu_per_s"],
                 d["cleared_launch"]), flush=True)
        at = pol.get("action_trace")
        if at:
            print("    wrote action-trace CSV %s" % at["csv"], flush=True)
            print_action_trace_summary(at["analysis"], indent="    ")
    else:
        print("  POLICY: (skipped; --controls-only)", flush=True)
    print("  GATE = route%% >= %g AND speed%% >= %g (time_weighted_speed); REACHED_RL is a harder diagnostic."
          % (GATE_ROUTE_PCT, GATE_SPEED_PCT), flush=True)
    print("  CONTROLS must bracket: human-path PASS + stall FAIL (else the gate is invalid).",
          flush=True)

    # a gate whose controls do not bracket is invalid -> exit 4 (mirror
    # eval_broad_closedloop.main), so a CI consumer never trusts the policy verdict.
    if not bracket:
        print("  ERROR: controls did NOT bracket (need human-path PASS + stall FAIL) — "
              "the gate is INVALID; policy verdict must not be trusted.", flush=True)
        return 4
    return 0


if __name__ == "__main__":
    sys.setrecursionlimit(20000)
    # `analyze TRACE.csv` is a deps-free subcommand that runs analyze_action_trace on an
    # existing action-trace CSV (no torch / BSP); anything else is the normal eval.
    if len(sys.argv) > 1 and sys.argv[1] == "analyze":
        raise SystemExit(main_analyze(sys.argv[2:]))
    raise SystemExit(main())
