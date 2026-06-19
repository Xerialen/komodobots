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

import argparse
import json
import math
import sys
from pathlib import Path

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

GATE_ROUTE_PCT = 80.0
GATE_SPEED_PCT = 80.0
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
                       seed_velocity=None):
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
    f_ent = dims["f_ent"]
    n = len(frames) - 1
    for k in range(n):
        f = frames[k]
        yaw = float(f["angles"][1])
        pitch = float(f["angles"][0])
        angles = [pitch, yaw, 0.0]
        # SAME self_state + obs encode the closed-loop gmv eval uses (solo-roam: [] ).
        self_state = CL._self_state_from_sim(st, yaw, pitch)
        enc = encode_obs(self_state, [], stats, map_name, n_max)
        obs_t = torch_mod.tensor([enc["self"]], dtype=torch_mod.float32, device=device)
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

        cmd = PM.Cmd(int(f["msec"]), angles, [fwd_mag, side_mag, up_mag], jump_bit)
        pm.run_frame(st, cmd)
        t += float(f["msec"]) / 1000.0
        ov = over_void_at(world, st.origin, floor_z)
        rows.append(make_row(t, st.origin, st.velocity, st.onground, ov, goal))
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
             seed_velocity=None, seed_from_human=False) -> dict:
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
    the gate; the exit-code behavior (controls must bracket) is unchanged."""
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

    world = PM.WorldModel.load(str(Path(bsp).expanduser()))
    route, frames, human_rows, human_tws, agreement = load_route_with_human(route_name, world)

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

    p_rows, p_atk = run_policy_rollout(
        frames, world, route, model=model, dims=dims, encode_obs=AO.encode_observation,
        stats=stats, torch_mod=torch, map_name=map_name, n_max=n_max, device=device,
        seed_velocity=seed)
    policy_result = score_rows(p_rows, route, human_tws)
    atk_rate = (round(sum(1 for a in p_atk if int(a) == 1) / len(p_atk), 6)
                if p_atk else 0.0)
    policy_result["predicted_attack_rate"] = atk_rate

    return build_report(
        route_name, route,
        human_result=human_result, stall_result=stall_result, policy_result=policy_result,
        human_tws=human_tws, agreement=agreement,
        inputs={"checkpoint": str(Path(checkpoint).expanduser()),
                "bsp": str(Path(bsp).expanduser()), "route": route_name,
                "map": map_name, "n_max": n_max, "controls_only": False,
                "norm_artifact": str(norm_path), "human_frames": len(frames)},
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
    args = ap.parse_args(argv)

    if args.controls_only:
        report = run_controls_only(args.bsp, args.route)
    else:
        if args.checkpoint is None:
            ap.error("--checkpoint is required unless --controls-only")
        report = run_eval(args.checkpoint, args.bsp, args.route,
                          norm_artifact=args.norm_artifact,
                          map_name=args.map, n_max=args.n_max, cpu=args.cpu,
                          seed_velocity=args.seed_velocity,
                          seed_from_human=args.seed_from_human)

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
    raise SystemExit(main())
