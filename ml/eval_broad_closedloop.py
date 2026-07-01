#!/usr/bin/env python3
"""eval_broad_closedloop.py — CLOSED-LOOP G-MV believability gate for the BROAD BC policy.

WHAT THIS IS (and the gap it closes over the open-loop eval)
============================================================
`ml/eval_broad_believability.py` is OPEN-LOOP: it feeds the policy the REAL held-out
human `agent_observation` per tick and scores the predicted ACTION stream against the
human's. It explicitly marks G-MV1 (face-and-run), G-MV4 (speed band) and
route-retention as **N/A** there, because those need the policy to actually MOVE the
player — open-loop never advances position.

THIS harness is the closed-loop counterpart. The trained policy DRIVES the QW player
movement simulator (`scripts/pmove_sim.py`) with the sim's OWN evolving state fed back
each tick (NOT re-anchored to human state):

  1. seed a `pmove_sim.PlayerState` from a recorded clean val start (origin+velocity),
  2. per tick: read the sim's current velocity + the REPLAYED human view yaw/pitch for
     that tick, build the SAME shared `agent_observation` (normalized), argmax the
     policy's 5 heads -> usercmd (fwd/side/up move + jump button),
  3. step `pmove_sim` one frame; the NEW sim velocity/position feeds step 2 next tick.

Because the bot now produces its OWN trajectory, G-MV1 (yaw-vs-velocity face-and-run),
G-MV3 (strafe cadence) and G-MV4 (speed band) are FINALLY scorable on the bot's own
motion, via the pure-stdlib `scripts/gmv_believability.py` battery — plus a route /
anti-stall retention metric computed on the bot's own path.

HONEST CAVEATS (recorded in every report; a reader must never mistake this for more)
------------------------------------------------------------------------------------
* AIM DEFERRED: the BROAD policy clones movement/jump/attack but NOT view. The view
  yaw/pitch is REPLAYED from the recorded human for that tick (so G-MV1 measures the
  bot's yaw-vs-its-own-velocity using the human's facing intent over the bot's motion).
* SOLO-ROAM: there are no enemies in the sim, so `encode_observation` is called with
  `observed_others=[]` -> the entity channel is all-pad + zero mask (the model handles
  it; ~12% of training frames had zero observed others). No combat dynamics.
* MOVE-HEAD -> USERCMD MAGNITUDE = +-400. The trainer scaled the move target /400
  (`agent_observation._MOVE_SCALE = 400`), so the magnitude-consistent inverse of the
  sign3 class is +-400 (NOT the move-only line's 320, which trained against a /320
  scale). The SIGN is what G-MV1 keys on (yaw vs velocity direction); the magnitude
  mainly affects the speed band (G-MV4) and can be swept on pinnacle if speed lands
  off-band.
* ATTACK is not driven (fire stays stock); the predicted attack class is recorded for
  completeness only.
* PLANE: the anchor speed band is on the MVD event-rate finite-difference plane
  (~13 ms); the sim speed here is `hypot(vx,vy)` sampled at the recorded ~13 ms tick
  cadence — close but not byte-identical (gate_mv4 widens the band 5% and states this).

CONTROLS (the proof the judge is valid — these run, in part, on a deps-free box too)
------------------------------------------------------------------------------------
The SAME closed-loop harness is run with two non-policy controllers as discrimination
controls, and a synthetic negative control:
  * controller="recorded" (POSITIVE control): the recorded HUMAN usercmd drives the sim
    -> must PASS G-MV1 (a real human trajectory is believable);
  * synthetic "face_and_run" (NEGATIVE control, `gmv.synth_face_and_run`): yaw locked to
    velocity every tick -> must FAIL G-MV1. gmv is pure stdlib, so THIS control runs for
    real even on a box with no torch (and is asserted in the unit test).
A judge that fails the bot but ALSO fails the human, or passes face-and-run, is not a
valid judge — the report prints all three side by side.

The believability NUMBERS for the POLICY can only come from the pinnacle run (torch +
duckdb); this module's pure-python glue + the gmv controls are unit-tested deps-free.

CLI
===
  python -m ml.eval_broad_closedloop \
      --checkpoint ~/broad_bc_policy.pt \
      --db ~/komodobots/data/catalog/dm3_4on4_slice.sqlite \
      --norm-artifact ~/komodobots/ml/gold/norm/normalization_stats.json \
      --bsp /path/to/dm3.bsp \
      --split val --horizon 385 \
      --anchors references/dm3_4on4_anchors.json \
      --out closedloop_gmv_report.json [--player-band NAME] [--n-segments N] [--cpu]
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
EXPERIMENTS = REPO_ROOT / "experiments" / "route_observatory"
if str(EXPERIMENTS) not in sys.path:
    sys.path.insert(0, str(EXPERIMENTS))

# DEPS-FREE imports only at module load. torch / numpy / duckdb and the heavy
# encoders/loaders are imported LAZILY inside run_eval(), so this module and its
# pure-python glue import on bare stdlib python (the unit tests verify this).
from broad_bc import shard_contract as SC        # noqa: E402  (deps-free)
import gmv_believability as GMV                   # noqa: E402  (pure stdlib)
# the SHARED turn-direction helper (pure stdlib, no torch) — the SAME yaw_rate the
# offline build computes, so the closed-loop policy obs is parity-identical per tick.
# assemble_self_history + SELF_HISTORY are the SHARED v5 sequence-history helpers — the
# SAME flat-history assembly (oldest->newest, left-pad-repeat-first) the offline build
# uses, so the policy's SELF input is byte-identical between train and this rollout.
from features.agent_observation import (                                    # noqa: E402
    yaw_rate_degps as _yaw_rate_degps,
    assemble_self_history as _assemble_self_history,
    SELF_HISTORY as _SELF_HISTORY,
)
# the honest OFFLINE route-grade (D1) — pure stdlib (route_geom + reward_onspeed), so it loads at
# module level with the other deps-free glue; only exercised when --grade-route is passed.
import route_grade as RGRADE                                                # noqa: E402


# =============================================================================
# Frozen head order (the trainer's heads). head_dims order == HEAD_NAMES order.
# sign3 classes {0: back/left/down, 1: none, 2: fwd/right/up}; bin {0,1}.
# =============================================================================
HEAD_NAMES = SC.head_names()                      # ["fwd","side","up","jump","attack"]

# usercmd move magnitude (qu). The BROAD trainer scaled the move target /400
# (agent_observation._MOVE_SCALE = 400), so the magnitude-consistent inverse of the
# sign3 class is +-400. (The move-ONLY Stage-2 line used 320 because it trained a
# /320-equivalent target; the broad policy did NOT — so 400 here is correct.)
MOVE_MAG = 400.0

# pmove jump button bit (mirrors pmove_sim.BUTTON_JUMP = 2; kept as a module const so
# the decode is exercisable without importing the heavy sim).
BUTTON_JUMP = 2


# =============================================================================
# PURE-PYTHON GLUE  (no torch / numpy / duckdb — unit-tested deps-free)
# The torch CLI (run_eval) calls EXACTLY these after producing per-head argmax.
# =============================================================================
def move_class_to_mag(cls: int, mag: float = MOVE_MAG) -> float:
    """Inverse of shard_contract.encode_sign3 for a usercmd magnitude.

    encode_sign3: value > +dz -> 2, value < -dz -> 0, else 1. So the class->signed
    magnitude inverse is: 2 -> +mag, 0 -> -mag, 1 -> 0. Pure int/float math.
    """
    c = int(cls)
    if c == 2:
        return float(mag)
    if c == 0:
        return float(-mag)
    return 0.0


def decode_move_heads(pred_classes, mag: float = MOVE_MAG):
    """5 per-head argmax classes (fwd/side/up/jump/attack order) -> the usercmd the
    sim consumes: (fwd_mag, side_mag, up_mag, jump_bit).

    fwd/side/up are sign3 -> +-mag/0 via move_class_to_mag. jump is the BUTTON_JUMP
    bit when the jump head argmax == 1. attack is IGNORED for control (fire stays
    stock) — the caller may still log the predicted attack class separately. Pure.
    """
    pc = list(pred_classes)
    fwd_mag = move_class_to_mag(pc[0], mag)
    side_mag = move_class_to_mag(pc[1], mag)
    up_mag = move_class_to_mag(pc[2], mag)
    jump_bit = BUTTON_JUMP if int(pc[3]) == 1 else 0
    return fwd_mag, side_mag, up_mag, jump_bit


def optimal_strafe_yaw(vx, vy, fwd_mag, side_mag, fallback_yaw, *, min_hspeed=1.0):
    """View yaw (degrees) orienting the air-strafe wishdir PERPENDICULAR to the
    horizontal velocity -- the per-tick speed-optimal air-strafe aim in THIS engine.

    Verified vs the exact pmove_sim._air_accelerate (scripts/.. + ml/tests/
    test_optimal_aim): because accelspeed = accel*wishspeed*frametime (~41.6) EXCEEDS
    the wishspd cap (30), the air accel is always addspeed-capped, so post-tick
    |v'_h|^2 = s^2 + 900 - (v_h . wishdir)^2 -- maximal at wishdir _|_ v_h, at EVERY
    speed (the folk "angle narrows with speed" rule does NOT hold here).

    Given the usercmd move magnitudes (fwd_mag = cmd.move[0], side_mag = cmd.move[1]),
    the perpendicular condition wishvel . v = 0 reduces to A*cos(y) + B*sin(y) = 0 with
    A = fwd_mag*vx - side_mag*vy and B = side_mag*vx + fwd_mag*vy  =>  y = atan2(-A, B).
    The two perpendicular branches (y, y+180) give the SAME speed gain but opposite turn
    side; pick the one nearest `fallback_yaw` so the bot keeps following the route's
    direction. Falls back to `fallback_yaw` when stopped (|v_h| < min_hspeed) or no move
    key is pressed (wishdir undefined). Pure float math -- no sim/torch dependency.
    """
    if (fwd_mag == 0.0 and side_mag == 0.0) or math.hypot(vx, vy) < min_hspeed:
        return float(fallback_yaw)
    a = fwd_mag * vx - side_mag * vy
    b = side_mag * vx + fwd_mag * vy
    y0 = math.degrees(math.atan2(-a, b))
    y1 = y0 + 180.0

    def _adist(p, q):
        d = (p - q) % 360.0
        return min(d, 360.0 - d)

    return float(y0 if _adist(y0, fallback_yaw) <= _adist(y1, fallback_yaw) else y1)


def gmv_tick_from_state(origin, vel, onground, yaw, side_mag, msec: float = 13.0) -> dict:
    """Build the one gmv-battery tick dict from a (post-frame) sim state + the
    predicted usercmd. Keys the battery reads: vx, vy, yaw, onground, hspeed,
    sidemove, msec (origin is carried for route metrics, ignored by the gates).

    `vel` = (vx, vy, vz); hspeed = hypot(vx, vy). `side_mag` is the predicted
    sidemove magnitude (so G-MV3 cadence sees the bot's OWN strafe intent). `yaw` is
    the REPLAYED human view yaw. Pure python.
    """
    vx = float(vel[0])
    vy = float(vel[1])
    return {
        "vx": vx,
        "vy": vy,
        "yaw": float(yaw),
        "onground": bool(onground),
        "hspeed": math.hypot(vx, vy),
        "sidemove": float(side_mag),
        "msec": float(msec),
        # origin carried for route_metrics (not used by the gates):
        "_ox": float(origin[0]),
        "_oy": float(origin[1]),
    }


def route_metrics(origins, speeds, msecs, *,
                  stall_window_s: float = 0.5, stall_speed: float = 40.0) -> dict:
    """Route-retention on the bot's OWN path: total 2-D path length + an anti-stall
    check (no contiguous window of ~>= stall_window_s where speed stays near-zero).

    `origins` = list of (x, y) the bot passed through (post-frame), `speeds` =
    per-tick horizontal speed (qu/s), `msecs` = per-tick frame ms. A bot that wedges
    against a wall / stops moving is NOT route-retaining even if its instantaneous
    facing is human; this surfaces it as `stalled=True` + the longest stall length.

    Returns {path_len_qu, n_ticks, mean_speed_qu_per_s, stalled, longest_stall_s,
    longest_stall_ticks, duration_s, displacement_qu}. Pure python (no numpy) — a
    prime deps-free unit-test target.
    """
    n = len(speeds)
    path_len = 0.0
    for i in range(1, len(origins)):
        ax, ay = origins[i - 1]
        bx, by = origins[i]
        path_len += math.hypot(float(bx) - float(ax), float(by) - float(ay))

    # anti-stall: longest contiguous run of near-zero-speed ticks, measured in seconds
    # via the per-tick msec (so it is robust to frame-rate). A run that reaches
    # stall_window_s flips `stalled`.
    longest_stall_s = 0.0
    longest_stall_ticks = 0
    cur_s = 0.0
    cur_ticks = 0
    for i in range(n):
        ms = (float(msecs[i]) if i < len(msecs) and msecs[i] else 13.0) / 1000.0
        if float(speeds[i]) < stall_speed:
            cur_s += ms
            cur_ticks += 1
            if cur_s > longest_stall_s:
                longest_stall_s = cur_s
                longest_stall_ticks = cur_ticks
        else:
            cur_s = 0.0
            cur_ticks = 0

    duration_s = sum((float(m) if m else 13.0) for m in msecs) / 1000.0
    mean_speed = (sum(float(s) for s in speeds) / n) if n else 0.0
    disp = 0.0
    if len(origins) >= 2:
        disp = math.hypot(float(origins[-1][0]) - float(origins[0][0]),
                          float(origins[-1][1]) - float(origins[0][1]))
    return {
        "path_len_qu": round(path_len, 2),
        "n_ticks": n,
        "mean_speed_qu_per_s": round(mean_speed, 3),
        "stalled": bool(longest_stall_s >= stall_window_s),
        "longest_stall_s": round(longest_stall_s, 4),
        "longest_stall_ticks": longest_stall_ticks,
        "duration_s": round(duration_s, 3),
        "displacement_qu": round(disp, 2),
        "stall_window_s": stall_window_s,
        "stall_speed_qu_per_s": stall_speed,
    }


def aggregate_route_metrics(segment_routes, *,
                            stall_window_s: float = 0.5) -> dict:
    """Combine PER-SEGMENT route dicts (each from route_metrics on ONE segment's own
    origins) into a corpus-level route summary WITHOUT re-running route_metrics on a
    concatenation of segment origins.

    Why this exists: route_metrics sums hypot over CONSECUTIVE origins and takes the
    first/last origin for displacement. If segment origins are pooled by concatenation,
    every segment boundary (segment N's last origin -> segment N+1's first origin) is a
    discontinuous JUMP across the map that injects a bogus TELEPORT distance into both
    path_len_qu and displacement_qu. Each segment's own route dict is already correct,
    so we aggregate THOSE instead:

      * path_len_qu, n_ticks, longest_stall_ticks-source, duration_s : SUMMED
      * mean_speed_qu_per_s : DURATION-WEIGHTED mean of per-segment means (so a long
        segment weights proportionally — identical to a pooled per-tick mean when the
        per-tick msec is uniform, which it is here ~13ms)
      * longest_stall_s / longest_stall_ticks : MAX over segments (a stall is a within-
        segment run; the longest single contiguous stall is the meaningful figure — a
        boundary can NOT create or extend a real stall)
      * stalled : ANY segment stalled (longest single-segment stall >= window)
      * displacement_qu : NOT summable across discontinuous segments, and net A->B
        displacement is per-segment by nature -> reported as the SUM of per-segment
        |displacement| (total straight-line ground covered, segment by segment), which
        is the honest cross-segment analog and never crosses a teleport boundary.

    Pure python; deps-free unit-test target. Empty input -> a zeroed route dict.
    """
    routes = list(segment_routes)
    if not routes:
        return {
            "path_len_qu": 0.0, "n_ticks": 0, "mean_speed_qu_per_s": 0.0,
            "stalled": False, "longest_stall_s": 0.0, "longest_stall_ticks": 0,
            "duration_s": 0.0, "displacement_qu": 0.0,
            "stall_window_s": stall_window_s, "stall_speed_qu_per_s": None,
            "n_segments": 0,
        }
    path_len = sum(float(r.get("path_len_qu", 0.0)) for r in routes)
    n_ticks = sum(int(r.get("n_ticks", 0)) for r in routes)
    duration = sum(float(r.get("duration_s", 0.0)) for r in routes)
    disp = sum(float(r.get("displacement_qu", 0.0)) for r in routes)
    # duration-weighted mean speed (fall back to tick-count weight if durations are 0)
    wsum = sum(float(r.get("duration_s", 0.0)) for r in routes)
    if wsum > 0:
        mean_speed = sum(float(r.get("mean_speed_qu_per_s", 0.0)) * float(r.get("duration_s", 0.0))
                         for r in routes) / wsum
    else:
        tw = sum(int(r.get("n_ticks", 0)) for r in routes)
        mean_speed = (sum(float(r.get("mean_speed_qu_per_s", 0.0)) * int(r.get("n_ticks", 0))
                          for r in routes) / tw) if tw else 0.0
    # longest SINGLE-segment stall (max, not sum — a stall never spans a boundary)
    longest_stall_s = max((float(r.get("longest_stall_s", 0.0)) for r in routes), default=0.0)
    longest_stall_ticks = max((int(r.get("longest_stall_ticks", 0)) for r in routes), default=0)
    stalled = any(bool(r.get("stalled")) for r in routes)
    stall_speed = next((r.get("stall_speed_qu_per_s") for r in routes
                        if r.get("stall_speed_qu_per_s") is not None), None)
    return {
        "path_len_qu": round(path_len, 2),
        "n_ticks": n_ticks,
        "mean_speed_qu_per_s": round(mean_speed, 3),
        "stalled": bool(stalled),
        "longest_stall_s": round(longest_stall_s, 4),
        "longest_stall_ticks": longest_stall_ticks,
        "duration_s": round(duration, 3),
        "displacement_qu": round(disp, 2),
        "stall_window_s": stall_window_s,
        "stall_speed_qu_per_s": stall_speed,
        "n_segments": len(routes),
    }


def score_sequence_gmv(ticks, anchors=None, player_band=None) -> dict:
    """Thin wrapper over the pure-stdlib gmv battery on a built tick list. Returns the
    full `run_battery` result (gates G-MV1 HARD / G-MV3 / G-MV4, `believable`,
    `all_gates_passed`). Importable + runnable deps-free (gmv has no heavy deps)."""
    return GMV.run_battery(ticks, anchors=anchors, player_band=player_band)


# =============================================================================
# G-MV3 boundary fix (mirrors eval_broad_believability.py d4bcff3 for the OPEN-loop
# eval). G-MV1/G-MV4 are per-tick and pool correctly across segments, but G-MV3
# strafe cadence COUNTS L<->R sidemove sign-flips between CONSECUTIVE ticks. On the
# POOLED multi-segment tick stream, each of the ~N segment boundaries (segment k's
# last strafe sign vs segment k+1's first) injects one spurious flip — exactly the
# bug d4bcff3 fixed for the per-demo open-loop eval. Fix: sum each SEGMENT's own
# G-MV3 flips + eligible ticks + active seconds (a flip is only meaningful within
# one segment's continuous tick sequence), recompute the cadence from those sums,
# and overwrite the boundary-contaminated pooled G-MV3 statistic. Pure python.
# =============================================================================
def cadence_from_flip_sums(flips: int, eligible_ticks: int, active_s: float, *,
                           nonzero_strafe_ticks: int | None = None, thr=None) -> dict:
    """Rebuild a G-MV3 cadence sub-result from ALREADY-SUMMED per-segment flips +
    eligible ticks + active seconds. Returns the SAME shape `gate_mv3` reports
    (passed/status/n_strafe_ticks/statistic/margin/thresholds), so it can replace
    the pooled (boundary-contaminated) G-MV3 gate verbatim. The pooled rate is
    flips / active_s * 60 (active_s = summed sidemove-carrying wall time — the FULL
    cadence denominator, INCLUDING sidemove==0 active ticks; it is NOT the nonzero
    count). Pure.

    `nonzero_strafe_ticks` is the POOLED count of NONZERO-strafe ticks across all
    summed segments (the same quantity `gate_mv3` floors on per-segment). When given
    and below `thr["mv3_min_strafe_ticks"]`, the pooled cadence is reported
    INSUFFICIENT (passed=None) — mirroring `gate_mv3`'s own floor, but decided on the
    TOTAL nonzero base, not per-segment. When None (legacy callers), no pooled floor
    is applied and a band verdict is always returned (back-compat)."""
    thr = thr or GMV.DEFAULT_THRESHOLDS
    lo = thr["mv3_min_flips_per_min"]
    hi = thr["mv3_max_flips_per_min"]
    flips_per_min = (flips / active_s * 60.0) if active_s > 0 else 0.0
    insufficient = (nonzero_strafe_ticks is not None
                    and int(nonzero_strafe_ticks) < thr["mv3_min_strafe_ticks"])
    if insufficient:
        return {
            "gate": "G-MV3", "hard": False, "passed": None, "status": "insufficient",
            "reason": "pooled %d nonzero-strafe ticks (< %d required)"
                      % (int(nonzero_strafe_ticks), thr["mv3_min_strafe_ticks"]),
            "n_strafe_ticks": int(nonzero_strafe_ticks),
            "statistic": {
                "flips": int(flips),
                "eligible_ticks": int(eligible_ticks),
                "active_s": round(float(active_s), 3),
                "flips_per_min": round(flips_per_min, 3),
                "boundary_safe": True,  # summed per-segment, no cross-boundary flip
                "insufficient": True,
            },
            "margin": None,
            "thresholds": {"min_flips_per_min": lo, "max_flips_per_min": hi},
        }
    in_band = lo <= flips_per_min <= hi
    margin = min(flips_per_min - lo, hi - flips_per_min)
    return {
        "gate": "G-MV3", "hard": False, "passed": in_band,
        "status": "pass" if in_band else "fail",
        # n_strafe_ticks reports the pooled NONZERO-strafe count when known (the
        # quantity the floor keys on), else falls back to eligible_ticks.
        "n_strafe_ticks": int(nonzero_strafe_ticks if nonzero_strafe_ticks is not None
                              else eligible_ticks),
        "statistic": {
            "flips": int(flips),
            "eligible_ticks": int(eligible_ticks),
            "active_s": round(float(active_s), 3),
            "flips_per_min": round(flips_per_min, 3),
            "boundary_safe": True,  # summed per-segment, no cross-boundary flip
        },
        "margin": {"flips_per_min_to_nearer_edge": round(margin, 3)},
        "thresholds": {"min_flips_per_min": lo, "max_flips_per_min": hi},
    }


def aggregate_mv3_from_segments(segment_mv3_gates, *, thr=None) -> dict | None:
    """Sum a list of PER-SEGMENT `gate_mv3` results into one boundary-safe pooled
    G-MV3 gate (flips/eligible_ticks/active_s summed, cadence recomputed from the
    pooled flips / pooled active_s).

    EVERY segment that carried ANY sidemove-bearing tick contributes its flips +
    eligible_ticks + active_s to the pooled sums — INCLUDING segments whose own
    per-segment G-MV3 was `insufficient` (too few NONZERO-strafe ticks to judge ON
    THEIR OWN). This is the P1 fix: an insufficient segment still has a real
    active_s (its sidemove-carrying wall time, which counts sidemove==0 ticks) that
    is part of the cadence DENOMINATOR. Dropping it would strip that time base from
    the pool and INFLATE the pooled flips_per_min (a long zero-sidemove segment
    pooled with a short real-flip segment would read far too high — the opposite of
    the de-biasing intent). Its (typically zero) flips pool correctly and never
    invent a cross-boundary flip.

    Pooled SUFFICIENCY is decided on the TOTAL NONZERO-strafe count across all
    segments (`n_strafe_ticks` summed) vs `thr["mv3_min_strafe_ticks"]`, NOT
    per-segment: many individually-thin segments can be jointly sufficient. Returns
    None only when NO segment carried any sidemove-bearing tick at all (eligible
    sum 0 -> the pool has no cadence base, so the caller keeps the pooled gate's own
    insufficient verdict). Pure python."""
    thr = thr or GMV.DEFAULT_THRESHOLDS
    flips = 0
    eligible = 0
    nonzero = 0
    active_s = 0.0
    saw_any = False
    for g in segment_mv3_gates:
        if not g:
            continue
        st = g.get("statistic")
        if not st:
            # No statistic at all (genuinely empty / legacy None) -> no cadence base
            # from this segment; skip it. (Post-fix gate_mv3 ALWAYS emits a statistic
            # for any sidemove-bearing segment, incl. insufficient ones.)
            continue
        eligible_ticks = int(st.get("eligible_ticks", 0) or 0)
        if eligible_ticks <= 0:
            # carried no sidemove tick -> contributes nothing to the pooled denom.
            continue
        saw_any = True
        flips += int(st.get("flips", 0) or 0)
        eligible += eligible_ticks
        active_s += float(st.get("active_s", 0.0) or 0.0)
        # pooled NONZERO-strafe base (the floor's domain). gate_mv3 reports the
        # nonzero count at top-level `n_strafe_ticks` in BOTH branches.
        nonzero += int(g.get("n_strafe_ticks", 0) or 0)
    if not saw_any:
        return None
    return cadence_from_flip_sums(flips, eligible, active_s,
                                  nonzero_strafe_ticks=nonzero, thr=thr)


def overwrite_pooled_mv3(battery: dict, segment_mv3_gates, *, thr=None) -> dict:
    """Replace `battery`'s pooled (boundary-contaminated) G-MV3 gate with the
    boundary-safe per-segment sum, IN PLACE, and return the battery. No-op when the
    battery has no G-MV3 gate or no segment carried a measurable cadence (then the
    pooled gate — typically `insufficient` — is left untouched). G-MV1/G-MV4 and the
    `believable`/`all_gates_passed` flags are left as-is: `believable` is gated on
    G-MV1 (unaffected), and `all_gates_passed` already required every gate True, so a
    corrected G-MV3 pass/fail keeps that flag honest (recomputed below to stay
    consistent with the overwritten gate). Pure python."""
    gates = battery.get("gates")
    if not gates or "G-MV3" not in gates:
        return battery
    agg = aggregate_mv3_from_segments(segment_mv3_gates, thr=thr)
    if agg is None:
        return battery
    gates["G-MV3"] = agg
    # keep all_gates_passed consistent with the corrected gate (believable is G-MV1).
    battery["all_gates_passed"] = bool(gates) and all(
        g.get("passed") is True for g in gates.values())
    return battery


def summarize_gmv(battery: dict) -> dict:
    """Compact, report-friendly view of a battery result: per-gate pass + the headline
    statistic, so the printed control table stays small. Pure python."""
    gates = battery.get("gates", {})

    def _g(name):
        g = gates.get(name)
        if not g:
            return {"present": False}
        return {"present": True, "passed": g.get("passed"),
                "status": g.get("status"), "statistic": g.get("statistic")}
    return {
        "believable_G_MV1": battery.get("believable"),
        "all_gates_passed": battery.get("all_gates_passed"),
        "n_ticks": battery.get("n_ticks"),
        "G_MV1": _g("G-MV1"),
        "G_MV3": _g("G-MV3"),
        "G_MV4": _g("G-MV4"),
    }


# =============================================================================
# Start-state selection (pure python over the loaded val episodes). Picks segments
# long enough (>= horizon) with enough airborne-moving ticks that gate_mv1 (needs
# >= mv1_min_ticks airborne-moving over the horizon) can actually be scored.
# =============================================================================
def _airborne_moving_count(ticks, *, hspeed_floor: float = None) -> int:
    """How many ticks are airborne (onground falsey) AND moving (hspeed >= floor) in a
    recorded segment — the gate_mv1 domain proxy used to pick startable segments."""
    if hspeed_floor is None:
        hspeed_floor = GMV.DEFAULT_THRESHOLDS["mv1_min_hspeed_qu_per_s"]
    c = 0
    for t in ticks:
        self_state = t.get("self", {})
        og = self_state.get("onground")
        if og:
            continue
        hs = self_state.get("hspeed")
        if hs is None:
            vx = float(self_state.get("vx", 0.0) or 0.0)
            vy = float(self_state.get("vy", 0.0) or 0.0)
            hs = math.hypot(vx, vy)
        if float(hs) >= hspeed_floor:
            c += 1
    return c


def select_start_segments(episodes, *, horizon: int, n_segments: int,
                          min_airborne_moving: int = None) -> list:
    """From {eid: [tick_obs,...]} pick up to `n_segments` (eid, start_index, segment)
    triples, each a horizon-length slice with enough airborne-moving ticks to give
    gate_mv1 a verdict. Deterministic: episodes sorted, first qualifying window per
    episode taken (one segment per episode keeps coverage broad). Pure python."""
    if min_airborne_moving is None:
        # gate_mv1 needs >= mv1_min_ticks airborne-moving ticks; require at least that
        # many in the chosen window so the bot's G-MV1 is scorable, not "insufficient".
        min_airborne_moving = GMV.DEFAULT_THRESHOLDS["mv1_min_ticks"]
    out = []
    for eid in sorted(episodes):
        ticks = episodes[eid]
        if len(ticks) < horizon + 1:
            continue
        # scan stride = horizon (non-overlapping) for the first window that qualifies.
        start = 0
        while start + horizon + 1 <= len(ticks):
            seg = ticks[start:start + horizon + 1]   # +1 so a post-frame end exists
            if _airborne_moving_count(seg) >= min_airborne_moving:
                out.append((eid, start, seg))
                break
            start += horizon
        if len(out) >= n_segments:
            break
    return out


# =============================================================================
# TORCH + NUMPY + DUCKDB PATH — the only part that needs the heavy deps (pinnacle).
# Everything above is pure python and unit-tested without torch/numpy/duckdb.
# =============================================================================
def _self_state_from_sim(st, yaw, pitch, yaw_rate=0.0, goal=None) -> dict:
    """agent_observation self_state for the CURRENT sim state + the REPLAYED human
    view. Keys match what agent_observation.self_features reads. health/armor/team
    are unknown in solo-roam -> left out (encoder zero-fills them).

    yaw_rate (deg/s) is the turn-direction signal for THIS tick — the caller tracks the
    PREVIOUS replayed view yaw and computes it via the SHARED _yaw_rate_degps so it
    matches the offline build byte-for-byte. Defaults to 0.0 (first tick / no prev yaw).

    goal (gx, gy) | None is the v4/v5 route-conditioning target for THIS tick — the SAME
    hindsight next-resource goal the OFFLINE build stamps (build_features._load_episode_ticks
    -> route_goals.label_episode_goals). AO.self_features turns it into the 3 appended goal
    channels via the SHARED goal_vector (parity). None (free-roam / the goal-BLIND control)
    -> the encoder's [0,0,1] default; a (gx,gy) tuple -> the real goal channels. The key is
    ONLY set when a goal is supplied, so the goal-blind path is byte-identical to the prior
    (pre-fix) behaviour."""
    vx, vy, vz = st.velocity[0], st.velocity[1], st.velocity[2]
    ss = {
        "ox": st.origin[0], "oy": st.origin[1], "oz": st.origin[2],
        "vx": vx, "vy": vy, "vz": vz,
        "yaw": float(yaw), "pitch": float(pitch),
        "hspeed": math.hypot(vx, vy),
        "onground": bool(st.onground),
        "yaw_rate": float(yaw_rate),
    }
    if goal is not None:
        ss["goal"] = (float(goal[0]), float(goal[1]))
    return ss


def _recorded_usercmd(act_state):
    """Recorded HUMAN usercmd magnitudes for the POSITIVE control: read the raw
    forwardmove/sidemove/upmove + jump button from the `actions` row. Returns
    (fwd_mag, side_mag, up_mag, jump_bit). A None action -> idle."""
    if not act_state:
        return 0.0, 0.0, 0.0, 0
    fwd = float(act_state.get("forwardmove", 0.0) or 0.0)
    side = float(act_state.get("sidemove", 0.0) or 0.0)
    up = float(act_state.get("upmove", 0.0) or 0.0)
    buttons = int(act_state.get("buttons", 0) or 0)
    jump_bit = BUTTON_JUMP if (buttons & BUTTON_JUMP) else 0
    return fwd, side, up, jump_bit


def closed_loop_rollout(pm_module, world, segment, controller, *,
                        model=None, dims=None, norm=None, map_name="dm3",
                        n_max=7, device="cpu", torch_mod=None,
                        goal_mode="conditioned", aim_mode="replayed"):
    """Drive `pmove_sim` closed-loop over one recorded segment, mirroring the Stage-2
    `eval_closedloop.closed_loop_run` skeleton but with the BROAD obs + heads.

    controller in {"policy","recorded"}. Returns (gmv_ticks, origins, speeds, msecs,
    predicted_attack_classes, fwd_press_frac, traj) — `traj` is the per-tick
    {ox,oy,oz,vx,vy,onground,fwd_am(CLASS)} stream the D1 route-grade consumes (fwd_am is
    None for the recorded control). The gmv tick is captured from the POST-frame sim state
    so the gates see the bot's own resulting motion.

    goal_mode (the v4/v5 goal-conditioning A/B, policy controller only):
      * "conditioned" (default, the FIX): feed the policy the per-tick hindsight goal the
        OFFLINE build stamped onto segment[k]["self"]["goal"] (via _load_episode_ticks ->
        route_goals.label_episode_goals over THIS episode's recorded positions), so the
        goal-conditioned SELF channels match training byte-for-byte instead of the
        free-roam [0,0,1] default.
      * "blind": pass NO goal (the prior, pre-fix behaviour) -> the encoder's [0,0,1]
        free-roam default every tick. This is the controlled-A/B baseline: same checkpoint,
        same segment, same seed/yaw — ONLY the goal channels differ — so the run isolates
        the goal-conditioning effect.
    A segment tick with no leg (goal absent/None even when conditioned) stays free-roam,
    exactly as in training (goal_coverage < 1.0). The goal is taken from the RECORDED
    self row (segment[k]["self"]) — the SAME hindsight label the build used — NOT from the
    sim's evolving position, mirroring the build's hindsight-over-recorded-positions
    definition.
    """
    pm = pm_module.Pmove(world)
    t0 = segment[0]["self"]
    st = pm_module.PlayerState(
        [float(t0.get("ox", 0.0)), float(t0.get("oy", 0.0)), float(t0.get("oz", 0.0))],
        [float(t0.get("vx", 0.0)), float(t0.get("vy", 0.0)), float(t0.get("vz", 0.0))],
    )

    gmv_ticks = []
    origins = []
    speeds = []
    msecs = []
    attack_classes = []
    traj = []                # per-tick {ox,oy,oz,vx,vy,onground,fwd_am} for the D1 route-grade
    fwd_press_n = 0          # policy ticks with fwd head == press-forward (class 2)
    policy_ticks = 0

    # one fewer step than len(segment) so segment[k+1] is never needed (we replay
    # segment[k]'s view onto the bot's own state); the +1 tick in the segment is the
    # post-frame anchor headroom only.
    n = len(segment) - 1
    prev_yaw = None   # previous EXECUTED view yaw (for the turn-direction signal)
    # aim_mode="policy" (RL): the policy owns its view yaw. policy_yaw is the running
    # executed yaw the policy integrates from its per-tick turn DELTA (the yaw head); it
    # drives BOTH the obs (yaw_sin/cos, face_vel_angle, yaw_rate) AND the pmove wishdir =
    # the air-strafe SPEED mechanism. Seeded at the segment's first human yaw so the bot
    # starts pointed down the route. (replayed/optimal leave it unused.)
    policy_yaw = float(segment[0]["self"].get("yaw", 0.0) or 0.0)
    # v5 SEQUENCE history: a rolling buffer of the last SELF_HISTORY SELF feature-vectors,
    # OLDEST -> NEWEST. RESET here at rollout start (so the first tick left-pad-repeats the
    # only available SELF, exactly like the offline build's first window tick). Each policy
    # tick appends this tick's enc["self"] and the flat history is assembled by the SHARED
    # AO.assemble_self_history -> byte-identical to training. (Only the policy controller
    # needs it; the recorded control drives the sim from the human usercmd directly.)
    from collections import deque
    self_hist = deque(maxlen=_SELF_HISTORY)
    for k in range(n):
        fwd_am_cls = None        # policy +forward CLASS this tick (route-grade); stays None for recorded
        rec_self = segment[k]["self"]
        pitch = float(rec_self.get("pitch", 0.0) or 0.0)
        # the OBS/EXECUTED view yaw: the policy's own running yaw under aim_mode="policy"
        # (self-yaw), else the replayed human yaw. The obs is built from THIS yaw, then the
        # yaw head (policy mode) produces the turn delta that updates policy_yaw for the
        # executed cmd + the next tick (causally correct: see what you face -> decide the turn).
        yaw = policy_yaw if (controller == "policy" and aim_mode == "policy") \
            else float(rec_self.get("yaw", 0.0) or 0.0)
        angles = [pitch, yaw, 0.0]
        rec_act = segment[k].get("act")
        msec = 13
        if rec_act and rec_act.get("msec"):
            msec = rec_act["msec"]
        # turn-rate from the PREVIOUS executed view yaw + this tick's dt (the SAME shared
        # helper the offline build calls -> parity). prev_yaw None on tick 0 -> rate 0.0.
        yaw_rate = _yaw_rate_degps(yaw, prev_yaw, float(msec) / 1000.0)

        if controller == "policy":
            # per-tick route-conditioning goal: the hindsight next-resource the OFFLINE
            # build stamped onto this recorded tick (segment[k]["self"]["goal"]). In
            # goal_mode="blind" we deliberately pass None -> [0,0,1] (the controlled-A/B
            # baseline == the prior behaviour); in "conditioned" we feed the real goal.
            tick_goal = (segment[k]["self"].get("goal")
                         if goal_mode == "conditioned" else None)
            self_state = _self_state_from_sim(st, yaw, pitch, yaw_rate=yaw_rate,
                                              goal=tick_goal)
            enc = norm["_AO"].encode_observation(self_state, [], norm["_stats"], map_name, n_max)
            # push this tick's SELF into the rolling history, then assemble the FLAT
            # [SELF_HISTORY*SELF_DIM] vector via the SHARED helper (same oldest->newest order
            # + same left-pad-repeat-first as the build) -> the v5 model SELF input.
            self_hist.append(enc["self"])
            self_in = _assemble_self_history(self_hist, _SELF_HISTORY)
            obs_t = torch_mod.tensor([self_in], dtype=torch_mod.float32, device=device)
            f_ent = dims["f_ent"]
            if f_ent > 0:
                ent_t = torch_mod.tensor([enc["ents"]], dtype=torch_mod.float32, device=device)
                em_t = torch_mod.tensor([enc["mask"]], dtype=torch_mod.float32, device=device)
            else:
                ent_t = torch_mod.zeros((1, n_max, 0), device=device)
                em_t = torch_mod.zeros((1, n_max), device=device)
            aux_t = torch_mod.zeros((1, dims["f_aux"]), device=device)
            with torch_mod.no_grad():
                if aim_mode == "policy":
                    # SELF-YAW: the policy's yaw head proposes a per-tick turn DELTA (sincos);
                    # integrate it onto policy_yaw and execute that. The bot OWNS its aim — the
                    # speed mechanism (RL). Requires a yaw-head ckpt (forward_with_yaw).
                    logits, yaw2 = model.forward_with_yaw(obs_t, ent_t, em_t, aux_t)
                    yd = float(torch_mod.atan2(yaw2[0, 0], yaw2[0, 1]).item()) * (180.0 / math.pi)
                    yd = max(-90.0, min(90.0, yd))
                    policy_yaw = yaw + yd            # integrate the turn onto the obs yaw
                    angles = [pitch, policy_yaw, 0.0]
                else:
                    logits = model(obs_t, ent_t, em_t, aux_t)
            pred_cls = [int(lg.argmax(dim=1).item()) for lg in logits]
            fwd_am_cls = int(pred_cls[0])    # +forward CLASS (2==held) for the route-grade clean_mechanism
            fwd_mag, side_mag, up_mag, jump_bit = decode_move_heads(pred_cls)
            attack_classes.append(pred_cls[4])
            policy_ticks += 1
            if int(pred_cls[0]) == 2:    # fwd head class 2 == press +forward (over-press metric)
                fwd_press_n += 1
            if aim_mode == "optimal":
                # greedy speed-optimal air-strafe yaw from the bot's OWN pre-frame velocity +
                # chosen move keys (the RL STEP-0 ceiling diagnostic; obs used replayed yaw).
                exec_yaw = optimal_strafe_yaw(st.velocity[0], st.velocity[1],
                                              fwd_mag, side_mag, yaw)
                angles = [pitch, exec_yaw, 0.0]
        else:  # "recorded" positive control
            fwd_mag, side_mag, up_mag, jump_bit = _recorded_usercmd(rec_act)
            # recorded +forward CLASS from the human's ACTUAL forwardmove -> the recorded control
            # exercises clean_mechanism too (not hardwired via fwd_am=None). 2=held, 0=back, 1=neutral.
            fwd_am_cls = 2 if fwd_mag > 1e-6 else (0 if fwd_mag < -1e-6 else 1)
            attack_classes.append(None)

        cmd = pm_module.Cmd(msec, angles, [fwd_mag, side_mag, up_mag], jump_bit)
        pm.run_frame(st, cmd)

        # capture the gmv tick from the POST-frame sim state + the EXECUTED view yaw
        # (angles[1] = the replayed / policy-self / optimal yaw actually sent to pmove, so
        # G-MV1 measures the real face-vs-velocity) + the predicted strafe intent.
        exec_view_yaw = float(angles[1])
        tick = gmv_tick_from_state(st.origin, st.velocity, st.onground, exec_view_yaw,
                                   side_mag, msec=msec)
        gmv_ticks.append(tick)
        origins.append((tick["_ox"], tick["_oy"]))
        speeds.append(tick["hspeed"])
        msecs.append(float(msec))
        # the route-grade trajectory: POST-frame sim state + this tick's +forward CLASS.
        traj.append({"ox": float(st.origin[0]), "oy": float(st.origin[1]), "oz": float(st.origin[2]),
                     "vx": float(st.velocity[0]), "vy": float(st.velocity[1]),
                     "onground": bool(st.onground), "fwd_am": fwd_am_cls})
        # next tick's "previous yaw" = the yaw THIS tick's OBS was built from (the pre-turn
        # yaw). In aim_mode="policy" the bot integrates its turn AFTER the obs (policy_yaw =
        # yaw + yd), so next tick's obs yaw == this exec_view_yaw; tracking exec_view_yaw here
        # would make yaw_rate==0 on every policy tick (the turn-direction feature would vanish
        # in closed-loop, breaking train/eval parity). Track the PRE-turn obs yaw instead, so
        # next tick's yaw_rate = (policy_yaw - this.yaw) = this tick's turn delta — matching
        # eval_broad_dryroute (yaw_prev = yaw) and the rl_onspeed env (prev_yaw = cur_yaw
        # pre-turn). For replayed/recorded modes yaw == exec_view_yaw, so this is a no-op.
        prev_yaw = yaw

    fwd_press_frac = (fwd_press_n / policy_ticks) if policy_ticks else None
    return gmv_ticks, origins, speeds, msecs, attack_classes, fwd_press_frac, traj


def _controller_report(pooled_ticks, route, anchors, player_band, *,
                       attack_pressed=None) -> dict:
    """Score one controller: gmv battery on the POOLED tick stream + a precomputed
    `route` summary. The gmv gates are per-tick (velocity/yaw/onground/sidemove) and
    pool correctly across segments, but route metrics CANNOT — origins concatenated
    across segments inject a teleport distance at each boundary. So the caller passes
    the route already aggregated from the per-segment route dicts (aggregate_route_metrics);
    this function no longer re-runs route_metrics on pooled origins."""
    battery = score_sequence_gmv(pooled_ticks, anchors=anchors, player_band=player_band)
    rep = {"gmv": battery, "gmv_summary": summarize_gmv(battery), "route": route,
           "n_ticks": len(pooled_ticks)}
    if attack_pressed is not None:
        rep["predicted_attack_rate"] = attack_pressed
    return rep


def run_eval(checkpoint: Path, bsp: Path, db: Path, norm_artifact: Path, *,
             split: str = "val", horizon: int = 385, n_segments: int = 12,
             anchors: Path | None = None, player_band: str | None = None,
             map_name: str = "dm3", n_max: int = 7, cpu: bool = False,
             goal_mode: str = "conditioned",
             resource_coords_path: Path | None = None,
             aim_mode: str = "replayed", grade_route: bool = False) -> dict:
    """Closed-loop believability eval. NEEDS torch (policy forward) + numpy (parity) +
    duckdb (catalog start states) + the BSP world. Flow:

      1. load checkpoint -> rebuild BroadBCPolicy (import from eval_broad_believability),
         load norm artifact (json), load the dm3 BSP into pmove_sim.WorldModel.
      2. read val episodes via _load_episode_ticks (the SAME loader the feature build
         uses); pick start segments with enough airborne-moving ticks for gate_mv1.
      3. per segment: closed-loop rollout for controller "policy" and "recorded"
         (positive control); collect each controller's gmv ticks + route data.
      4. score each controller pooled (gmv battery + route metrics); add the synthetic
         face-and-run NEGATIVE control (must FAIL G-MV1). Emit the report + provenance.
    """
    import torch
    import numpy as np  # noqa: F401  (parity w/ the trainer tensor-build path)
    from features import agent_observation as AO
    sys.path.insert(0, str(REPO_ROOT / "ml" / "pipeline"))
    from build_features import _load_episode_ticks
    import route_goals as RG
    # default coords path from the deps-light route_goals (== build_features._DEFAULT_RESOURCE_COORDS)
    _DEFAULT_RESOURCE_COORDS = RG.DEFAULT_RESOURCE_COORDS
    from eval_broad_believability import _build_policy_from_checkpoint
    import pmove_sim
    from broad_bc import core as _core

    device = "cpu" if cpu else ("cuda" if torch.cuda.is_available() else "cpu")
    ckpt = torch.load(Path(checkpoint).expanduser(), map_location=device)
    model, dims, head_dims = _build_policy_from_checkpoint(ckpt, device)
    stats = json.loads(Path(norm_artifact).expanduser().read_text(encoding="utf-8"))
    world = pmove_sim.WorldModel.load(str(Path(bsp).expanduser()))
    anchors_obj = (json.loads(Path(anchors).expanduser().read_text(encoding="utf-8"))
                   if anchors else None)

    # route-conditioning v4/v5 GOAL coords — resolved EXACTLY as build_observation_shard
    # does (explicit path wins; else dm3 defaults to the committed artifact), so the per-tick
    # hindsight goal _load_episode_ticks stamps here is byte-identical to the training label.
    # In goal_mode="blind" we deliberately load NO coords (every tick free-roam [0,0,1]) so the
    # controlled A/B baseline reproduces the prior (pre-fix) goal-blind behaviour exactly.
    if goal_mode == "conditioned":
        if resource_coords_path is not None:
            coords = RG.load_resource_coords(Path(resource_coords_path).expanduser())
        elif map_name == "dm3":
            coords = RG.load_resource_coords(_DEFAULT_RESOURCE_COORDS)
        else:
            coords = {}
    else:
        coords = {}

    # SAME loader the feature build uses, NOW passing resource_coords so each tick's
    # self_state carries the hindsight "goal" key (the build's parity). With coords={} (blind
    # or non-dm3) no goal key is stamped -> free-roam, identical to the prior call.
    episodes, ep_demo = _load_episode_ticks(
        Path(db).expanduser(), split=split, resource_coords=coords)
    n_goal_ticks = sum(1 for et in episodes.values()
                       for t in et if t["self"].get("goal") is not None)
    n_all_ticks = sum(len(et) for et in episodes.values())
    segments = select_start_segments(episodes, horizon=horizon, n_segments=n_segments)

    # carry the encoder + stats through the rollout without re-importing per tick.
    norm_bundle = {"_AO": AO, "_stats": stats}

    per_segment = []
    # pooled TICK streams per controller (gmv gates pool correctly per-tick). Route
    # data is NOT pooled by concatenation — origins from different segments are
    # discontinuous, so we keep each segment's OWN route dict and aggregate those
    # (aggregate_route_metrics) to avoid a teleport distance at every segment boundary.
    pool = {
        "policy": {"ticks": [], "attack": [], "routes": [], "mv3_gates": [], "fwd_press": []},
        "recorded": {"ticks": [], "routes": [], "mv3_gates": []},
    }
    route_grades = []      # per-segment D1 honest route-grade dicts (populated only when grade_route)
    recorded_grades = []   # recorded-human positive control = the SIM-FIDELITY CEILING (sim-human's own
    #                        ratio, well under the raw-human 1.0 bar) -> the RELATIVE bar the policy is judged against (#428)
    for (eid, start, seg) in segments:
        pol = closed_loop_rollout(
            pmove_sim, world, seg, "policy", model=model, dims=dims,
            norm=norm_bundle, map_name=map_name, n_max=n_max, device=device,
            torch_mod=torch, goal_mode=goal_mode, aim_mode=aim_mode)
        rec = closed_loop_rollout(
            pmove_sim, world, seg, "recorded", map_name=map_name, n_max=n_max)

        p_ticks, p_org, p_spd, p_ms, p_atk, p_fwd_press, p_traj = pol
        r_ticks, r_org, r_spd, r_ms, _, _, r_traj = rec
        if p_fwd_press is not None:
            pool["policy"]["fwd_press"].append((p_fwd_press, len(p_ticks)))
        # per-segment route dicts (each on ITS OWN origins -> correct, no boundary jump)
        p_route = route_metrics(p_org, p_spd, p_ms)
        r_route = route_metrics(r_org, r_spd, r_ms)
        if grade_route:
            # per-segment human-reference route, built the SAME way as the reward's
            # rl_onspeed._reset_state (poly = self ox/oy/oz, speeds = hypot(vx,vy),
            # total_len = sum segment dist) -> route_speedup gives the identical v_ref, so the
            # grade's speedup ratio == the reward's by construction.
            _poly = [(float(s["self"]["ox"]), float(s["self"]["oy"]), float(s["self"]["oz"]))
                     for s in seg]
            _spd = [math.hypot(float(s["self"].get("vx", 0.0)), float(s["self"].get("vy", 0.0)))
                    for s in seg]
            _tot = sum(math.dist(a, b) for a, b in zip(_poly, _poly[1:])) if len(_poly) > 1 else 0.0
            _route = {"polyline": _poly, "speeds": _spd, "total_len": _tot}
            # Positive control FIRST: grade the recorded HUMAN usercmd RE-SIMULATED on the SAME route.
            # The offline sim reproduces only ~half the real engine's along-route speed, so this control
            # does NOT score ~1.0 vs the raw human -> its median ratio is the per-segment SIM-FIDELITY
            # CEILING and the RELATIVE bar the policy must beat (#428), cancelling the common sim factor.
            _rec_grade = RGRADE.grade_trajectory(RGRADE.prep_traj_for_grade(r_traj, _route), _route)
            recorded_grades.append(_rec_grade)
            # The control is a valid SPEED reference only if it was itself a valid route anchor on this
            # segment: on_route AND completed_route (Codex #471 P1 — an off-route / incomplete control with
            # a healthy ratio must NOT license a policy relative-pass). clean_mechanism is NOT required: the
            # control is a speed reference, not a bhop-purity exemplar.
            _ref_valid = bool(_rec_grade["on_route"] and _rec_grade["completed_route"])
            # Policy graded RELATIVE to that control: faster_than_human == beat the SIM-human (not the raw
            # human) -> a trustworthy ranking, NOT a superhuman claim (which needs a live recording; docs/28).
            route_grades.append(
                RGRADE.grade_trajectory(RGRADE.prep_traj_for_grade(p_traj, _route), _route,
                                        human_ref_ratio=_rec_grade["median_speedup_ratio"],
                                        human_ref_valid=_ref_valid))
        # per-segment gmv batteries (scored ONCE here): the summary feeds per_segment[]
        # AND each segment's own G-MV3 gate is kept so the pooled cadence can be summed
        # from PER-SEGMENT flips (no cross-boundary L<->R flip — see overwrite_pooled_mv3).
        p_batt = score_sequence_gmv(p_ticks, anchors=anchors_obj, player_band=player_band)
        r_batt = score_sequence_gmv(r_ticks, anchors=anchors_obj, player_band=player_band)
        pool["policy"]["ticks"].extend(p_ticks)
        pool["policy"]["attack"].extend([a for a in p_atk if a is not None])
        pool["policy"]["routes"].append(p_route)
        pool["policy"]["mv3_gates"].append(p_batt.get("gates", {}).get("G-MV3"))
        pool["recorded"]["ticks"].extend(r_ticks)
        pool["recorded"]["routes"].append(r_route)
        pool["recorded"]["mv3_gates"].append(r_batt.get("gates", {}).get("G-MV3"))

        per_segment.append({
            "episode_id": int(eid),
            "demo_id": str(ep_demo.get(eid, eid)),
            "start_index": int(start),
            "n_ticks": len(p_ticks),
            "policy": {"gmv_summary": summarize_gmv(p_batt), "route": p_route},
            "recorded": {"gmv_summary": summarize_gmv(r_batt), "route": r_route},
        })

    # aggregate controller reports: gmv on pooled ticks, route from per-segment dicts.
    # The pooled gmv battery's G-MV3 is then OVERWRITTEN with the boundary-safe
    # per-segment flip sum (overwrite_pooled_mv3): pooling tick streams across the
    # ~N segments would otherwise count one spurious strafe flip at each boundary
    # (the same bug class fixed for the open-loop eval in d4bcff3).
    atk = pool["policy"]["attack"]
    atk_rate = round(sum(1 for a in atk if int(a) == 1) / len(atk), 6) if atk else 0.0
    bot_policy = _controller_report(
        pool["policy"]["ticks"], aggregate_route_metrics(pool["policy"]["routes"]),
        anchors_obj, player_band, attack_pressed=atk_rate)
    overwrite_pooled_mv3(bot_policy["gmv"], pool["policy"]["mv3_gates"])
    bot_policy["gmv_summary"] = summarize_gmv(bot_policy["gmv"])
    # tick-weighted forward-press fraction across segments (the over-press metric; the bar
    # this whole RL line targets is fwd-press into the human band ~0.07-0.50). M3 source.
    _fp = pool["policy"]["fwd_press"]
    _fp_tot = sum(nn for _, nn in _fp)
    bot_policy["fwd_press_frac"] = (round(sum(f * nn for f, nn in _fp) / _fp_tot, 6)
                                    if _fp_tot else None)
    bot_policy["aim_mode"] = aim_mode
    recorded_human = _controller_report(
        pool["recorded"]["ticks"], aggregate_route_metrics(pool["recorded"]["routes"]),
        anchors_obj, player_band)
    overwrite_pooled_mv3(recorded_human["gmv"], pool["recorded"]["mv3_gates"])
    recorded_human["gmv_summary"] = summarize_gmv(recorded_human["gmv"])

    # synthetic NEGATIVE control — gmv is stdlib so this runs for real anywhere.
    face_run = GMV.synth_face_and_run(n=max(2000, horizon * 4))
    face_run_battery = score_sequence_gmv(face_run, anchors=anchors_obj,
                                          player_band=player_band)

    report = {
        "schema": "komodobots.eval_broad_closedloop.v1",
        "eval_mode": "closed_loop",
        "inputs": {
            "checkpoint": str(Path(checkpoint).expanduser()),
            "bsp": str(Path(bsp).expanduser()),
            "db": str(Path(db).expanduser()),
            "norm_artifact": str(Path(norm_artifact).expanduser()),
            "split": split, "horizon_ticks": horizon,
            "approx_horizon_secs": round(horizon * 0.013, 2),
            "n_segments_requested": n_segments,
            "n_segments_used": len(segments),
            "map": map_name, "n_max": n_max,
            "anchors": str(anchors) if anchors else None,
            "player_band": player_band or "pool",
        },
        "goal_conditioning": {
            "goal_mode": goal_mode,
            "note": ("'conditioned' = the policy sees the per-tick hindsight next-resource "
                     "GOAL the offline build stamped (route_goals.label_episode_goals via "
                     "_load_episode_ticks; the SAME resource_coords); 'blind' = no goal -> "
                     "encoder [0,0,1] free-roam every tick (the prior pre-fix behaviour, the "
                     "controlled-A/B baseline). Goal taken from the recorded self row, NOT "
                     "the route endpoint."),
            "resource_coords": (str(Path(resource_coords_path).expanduser())
                                if resource_coords_path is not None
                                else (str(_DEFAULT_RESOURCE_COORDS)
                                      if (goal_mode == "conditioned" and map_name == "dm3")
                                      else None)),
            "n_resources": len(coords),
            "goal_labeled_ticks": n_goal_ticks,
            "all_ticks": n_all_ticks,
            "goal_coverage": (round(n_goal_ticks / n_all_ticks, 4) if n_all_ticks else 0.0),
        },
        "checkpoint_meta": {
            "arch": ckpt.get("arch"), "dims": dims, "head_dims": head_dims,
            "head_names": ckpt.get("head_names"),
            "contract_version": ckpt.get("contract_version"),
            "trained_val_action_accuracy": ckpt.get("val_acc"),
        },
        "decode": {
            "move_magnitude_qu": MOVE_MAG,
            "note": ("sign3 class -> usercmd: 2->+MAG, 0->-MAG, 1->0; MAG=400 matches "
                     "the BROAD trainer's /400 move scale (agent_observation._MOVE_SCALE). "
                     "jump head==1 -> BUTTON_JUMP; attack head NOT driven (logged only). "
                     + _aim_plane_note(aim_mode)),
            "button_jump_bit": BUTTON_JUMP,
        },
        "anchor_bands": _anchor_band_summary(anchors_obj, player_band),
        # the three-way discrimination view (the proof the judge is valid):
        "bot_policy": bot_policy,
        "recorded_human": recorded_human,          # POSITIVE control (expect G-MV1 pass)
        "face_and_run_synthetic": {                 # NEGATIVE control (expect G-MV1 FAIL)
            "gmv_summary": summarize_gmv(face_run_battery),
            "n_ticks": face_run_battery.get("n_ticks"),
            "expect": "G-MV1 must FAIL (yaw locked to velocity every tick)",
        },
        "per_segment": per_segment,
        "caveats": _build_caveats(aim_mode),
        "provenance": {
            "git_sha": _core.git_sha(REPO_ROOT),
            "norm_artifact_version": stats.get("artifact_version", "UNSET"),
            "registry_version": stats.get("registry_version"),
            "torch": getattr(torch, "__version__", None),
            "device": device,
        },
    }
    if grade_route:
        report["route_grade"] = {
            "summary": RGRADE.aggregate_route_grades(route_grades),
            "recorded_control": RGRADE.aggregate_route_grades(recorded_grades),
            "per_segment": route_grades,
            "aim_mode": aim_mode,
            "measurement_plane": _aim_head_label(aim_mode),
            "superhuman_claim": False,
            "note": ("D1/#428 honest OFFLINE route-grade of the policy rollout on the `measurement_plane` "
                     "above (on_route + faster_than_human + clean_mechanism + completed_route, per segment; "
                     "prep_traj_for_grade guards the superhuman-overrun + v_ref~0 misgrade traps). "
                     "`recorded_control` grades the SAME routes with the recorded HUMAN usercmd re-simulated "
                     "(fwd class from the recorded forwardmove, so it exercises ALL four gates) — the positive "
                     "control showing the SIM-FIDELITY CEILING. The policy's `faster_than_human` is judged "
                     "RELATIVE to that control (#428: beat the sim-human, cancelling the ~half-speed sim "
                     "factor that makes the raw-human 1.0 bar unreachable in-sim; see per-segment "
                     "`faster_basis`). An INTERNAL ranking instrument that de-circularises training decisions "
                     "— NOT the superhuman CLAIM (`superhuman_claim:false`), which still needs an owner-gated "
                     "live recorded run + pov_fuse (docs/28)."),
        }
    return report


def _anchor_band_summary(anchors_obj, player_band) -> dict:
    """Echo the G-MV4 speed band that will judge the run (pool or per-player)."""
    if not anchors_obj:
        return {"present": False, "reason": "no --anchors provided"}
    try:
        thr = GMV.DEFAULT_THRESHOLDS
        avg_lo, avg_hi, avg_src = GMV._band_for(anchors_obj, thr["mv4_avg_field"], player_band)
        p95_lo, p95_hi, p95_src = GMV._band_for(anchors_obj, thr["mv4_p95_field"], player_band)
    except Exception as e:  # noqa: BLE001
        return {"present": True, "error": str(e)}
    return {
        "present": True,
        "avg_horizontal_speed_qu_per_s": {"min": avg_lo, "max": avg_hi, "source": avg_src},
        "p95_horizontal_speed_qu_per_s": {"min": p95_lo, "max": p95_hi, "source": p95_src},
        "plane": "mvd_event_rate_finite_difference (~13ms); sim sampled at recorded ~13ms tick",
        "schema": anchors_obj.get("schema"),
    }


def _aim_head_label(aim_mode: str) -> str:
    """Measurement-plane label for the executed view yaw (provenance: which aim plane the grade saw)."""
    return {"policy": "POLICY_SELF_YAW", "optimal": "OPTIMAL_ANALYTIC"}.get(aim_mode, "REPLAYED")


def _aim_plane_note(aim_mode: str) -> str:
    """One-line description of the executed-view-yaw plane, keyed on aim_mode (NOT hard-coded replayed)."""
    if aim_mode == "policy":
        return ("view yaw = the POLICY's OWN self-yaw head (forward_with_yaw), integrated per tick -> the "
                "route-grade is measured on the policy's SELF-YAW plane, NOT replayed human aim.")
    if aim_mode == "optimal":
        return ("view yaw = the greedy speed-OPTIMAL analytic air-strafe yaw (RL STEP-0 ceiling diagnostic); "
                "the obs used the replayed human yaw.")
    return ("view yaw/pitch REPLAYED from the recorded human (AIM deferred): movement/jump heads are the "
            "policy's, the view is the human's.")


def _build_caveats(aim_mode: str = "replayed") -> dict:
    return {
        "eval_mode": "closed_loop",
        "what_closed_loop_means": (
            "The policy DRIVES pmove_sim with the sim's own evolving state fed back "
            "each tick (not re-anchored to human state), so G-MV1/G-MV3/G-MV4 and route "
            "retention are scored on the BOT's own resulting trajectory."),
        "aim_head": _aim_head_label(aim_mode),
        "aim_head_detail": _aim_plane_note(aim_mode),
        "solo_roam": (
            "No enemies in the sim -> encode_observation is called with observed_others=[] "
            "(entity channel all-pad + zero mask). Combat dynamics are out of scope here."),
        "move_magnitude": (
            "Move-head -> usercmd magnitude = +-400 (trainer /400 scale). The SIGN drives "
            "G-MV1 (yaw vs velocity); magnitude mainly affects G-MV4 speed band — sweepable "
            "on pinnacle if speed lands off-band."),
        "attack_not_driven": "Predicted attack class is logged but does not fire in the sim.",
        "speed_plane": (
            "anchor speed band is mvd_event_rate_finite_difference (~13ms); sim hspeed is "
            "hypot(vx,vy) at the recorded ~13ms tick — close, not byte-identical (G-MV4 "
            "widens the band 5%)."),
        "controls": (
            "recorded-human (positive, must PASS G-MV1) and synthetic face-and-run "
            "(negative, must FAIL G-MV1) bracket the policy so the judge is shown valid."),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--checkpoint", type=Path, required=True,
                    help="broad_bc_policy.pt (train_broad_bc.py output)")
    ap.add_argument("--bsp", type=Path, required=True,
                    help="dm3.bsp (the map the sim rolls out in)")
    ap.add_argument("--db", type=Path, required=True,
                    help="catalog .sqlite with held-out `val` episodes (start states)")
    ap.add_argument("--norm-artifact", type=Path, required=True,
                    help="normalization_stats.json (SAME artifact training used)")
    ap.add_argument("--split", default="val")
    ap.add_argument("--horizon", type=int, default=385, help="rollout ticks (~5s @ 13ms)")
    ap.add_argument("--n-segments", type=int, default=12,
                    help="max start segments to roll out")
    ap.add_argument("--out", type=Path, required=True, help="report.json path")
    ap.add_argument("--anchors", type=Path, default=None,
                    help="references/dm3_4on4_anchors.json (enables G-MV4 speed band)")
    ap.add_argument("--player-band", default=None,
                    help="anchor player name for the G-MV4 band (else pool envelope)")
    ap.add_argument("--map", default="dm3")
    ap.add_argument("--n-max", type=int, default=7)
    ap.add_argument("--cpu", action="store_true", help="force CPU forward")
    ap.add_argument("--goal-mode", choices=("conditioned", "blind"), default="conditioned",
                    help="route-conditioning for the POLICY: 'conditioned' (default) feeds "
                         "the per-tick hindsight next-resource GOAL the offline build stamped "
                         "(train/serve parity); 'blind' passes no goal -> [0,0,1] free-roam "
                         "every tick (the prior pre-fix behaviour; the controlled-A/B baseline).")
    ap.add_argument("--resource-coords", type=Path, default=None,
                    help="resource_coords.<map>.json for the goal label (defaults to the "
                         "committed dm3 artifact for map=dm3; ignored with --goal-mode blind)")
    ap.add_argument("--aim", choices=("replayed", "optimal", "policy"), default="replayed",
                    help="executed view yaw: 'replayed' human (default), 'optimal' greedy "
                         "speed-optimal air-strafe (RL STEP-0 ceiling), or 'policy' = the "
                         "policy's OWN yaw head (self-yaw; the RL movement-v5 mechanism). "
                         "'policy' needs a yaw-head ckpt (forward_with_yaw).")
    ap.add_argument("--grade-route", action="store_true",
                    help="ALSO emit the D1 honest OFFLINE route-grade of the policy rollout "
                         "(on_route + faster_than_human + clean_mechanism + completed_route, per "
                         "segment). Additive (leaves the G-MV battery untouched); use with --aim policy. "
                         "The INTERNAL instrument, NOT the superhuman claim (that needs a live recording).")
    args = ap.parse_args(argv)

    report = run_eval(
        args.checkpoint, args.bsp, args.db, args.norm_artifact,
        split=args.split, horizon=args.horizon, n_segments=args.n_segments,
        anchors=args.anchors, player_band=args.player_band,
        map_name=args.map, n_max=args.n_max, cpu=args.cpu,
        goal_mode=args.goal_mode, resource_coords_path=args.resource_coords,
        aim_mode=args.aim, grade_route=args.grade_route,
    )
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    bot = report["bot_policy"]["gmv_summary"]
    rec = report["recorded_human"]["gmv_summary"]
    far = report["face_and_run_synthetic"]["gmv_summary"]
    print(f"wrote {out}", flush=True)
    gc = report["goal_conditioning"]
    print("  goal_mode = %s  (goal_labeled_ticks=%s/%s coverage=%s, n_resources=%s)"
          % (gc["goal_mode"], gc["goal_labeled_ticks"], gc["all_ticks"],
             gc["goal_coverage"], gc["n_resources"]), flush=True)
    print(f"  segments used = {report['inputs']['n_segments_used']} "
          f"horizon = {report['inputs']['horizon_ticks']} ticks", flush=True)
    print("  G-MV1 (face-and-run, HARD)   bot=%s  recorded=%s  face_and_run=%s"
          % (bot["G_MV1"].get("passed"), rec["G_MV1"].get("passed"),
             far["G_MV1"].get("passed")), flush=True)
    print("  G-MV3 (strafe cadence)       bot=%s  recorded=%s"
          % (bot["G_MV3"].get("passed"), rec["G_MV3"].get("passed")), flush=True)
    print("  G-MV4 (speed band)           bot=%s  recorded=%s"
          % (bot["G_MV4"].get("passed"), rec["G_MV4"].get("passed")), flush=True)
    print("  route(bot): path_len=%s qu  stalled=%s  longest_stall=%ss"
          % (report["bot_policy"]["route"]["path_len_qu"],
             report["bot_policy"]["route"]["stalled"],
             report["bot_policy"]["route"]["longest_stall_s"]), flush=True)
    print("  CONTROLS: recorded-human should PASS G-MV1; face-and-run should FAIL G-MV1.",
          flush=True)
    print("  CAVEATS: closed-loop; AIM=%s; solo-roam; MOVE mag=400; attack not driven." % args.aim,
          flush=True)
    if args.grade_route and "route_grade" in report:
        _rg = report["route_grade"]["summary"]
        print("  ROUTE-GRADE (#428 offline; faster=RELATIVE to sim-human): seg_passed=%d/%d  all_passed=%s  median_ratio=%s  median_rmse=%s qu"
              % (round(_rg["seg_passed_frac"] * _rg["n_segments"]), _rg["n_segments"],
                 _rg["all_passed"], _rg["median_speedup_ratio"], _rg["median_route_rmse_qu"]), flush=True)
        _rc = report["route_grade"]["recorded_control"]
        print("    CONTROL (recorded human re-simulated): seg_passed=%d/%d  median_ratio=%s  (SIM-FIDELITY CEILING = the relative bar; sim reproduces ~half real speed)"
              % (round(_rc["seg_passed_frac"] * _rc["n_segments"]), _rc["n_segments"], _rc["median_speedup_ratio"]),
              flush=True)
        print("    (offline ranking instrument only; superhuman_claim=false — the CLAIM needs a live recording + pov_fuse.)",
              flush=True)
    # exit non-zero if the discrimination controls are wrong (the judge is invalid),
    # so a CI consumer never trusts a run whose controls failed.
    rec_ok = rec["G_MV1"].get("passed") is True
    far_fail = far["G_MV1"].get("passed") is False
    if not (rec_ok and far_fail):
        print("  WARNING: discrimination controls did not bracket as expected "
              "(recorded PASS + face-and-run FAIL) — treat policy verdict with care.",
              flush=True)
        return 4
    return 0


if __name__ == "__main__":
    sys.setrecursionlimit(20000)
    raise SystemExit(main())
